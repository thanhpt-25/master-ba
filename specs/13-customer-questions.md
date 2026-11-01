# Spec 13 — Customer questions ledger

Status: v0.1 (2026-11-01), draft for the owner's approval. Sources: dry-runs 4 and 5 ([11-hardening.md](11-hardening.md) section 10.3 and section 11), [architecture/04-team-runtime-control-flow.md](../docs/architecture/04-team-runtime-control-flow.md), [architecture/05-change-management-flow.md](../docs/architecture/05-change-management-flow.md), [07-change-management.md](07-change-management.md). The number 12 stays with the local RAG phase in [../docs/next-steps.md](../docs/next-steps.md); this spec does not depend on it.

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

A point that only the customer or the product owner can settle is written into a project **ledger of questions** as soon as an agent finds it. The run does not wait for it and does not loop on it: what is clear goes on, what is unclear is recorded. When the product owner answers, the answer is finalised as an approved **Decision Record**, and every later run and every propagation uses it as a confirmed fact.

The rule, in the owner's words: clear parts keep running; unclear parts go into the Q&A ledger; the answers are fixed as decision records.

## Non-goals

- No automatic delivery of questions to the product owner (mail, chat). The ledger is read in the CLI, the API and the dashboard.
- No waiting state and no new run status. A stage still ends `done` or `escalated` exactly as today.
- No answers written by a model. Only a signed-in person (or the CLI `--by`) answers.
- No threads, comments or editing of a question's text.
- No change to the loops, the gates or the QA normalisation of [11-hardening.md](11-hardening.md).

## 1. Problem

Questions for the customer are produced in four places and only reported:

| Producer | Today |
|---|---|
| BRD analyst: `open_questions` with intake lines | printed in `StageResult.open_questions` |
| SRS writer: `open_questions` with requirement ids | same |
| QA: an issue with `customer_question` set | downgraded to advisory, collected in `TeamRun.customer_questions` |
| Tester: a question about an item the designer already answered | posted to the `customer` mailbox, returned as `unresolved` |

Nothing reads an answer. In dry-run 5 the team collected 13, then 17, then 27 open questions while it looped for 12 rounds and 513,292 tokens, and a person had no place to answer ("is deleting an employee in scope?", "what does the three business days count from?"). The only way to carry a decision into the documents is a `clarification` Decision Record written by hand, and it reaches documents that already exist, not the next run of a stage that escalated.

## 2. The ledger

A question is one file, `projects/<project_id>/questions/Q-####.json`, in the project like every other store entity (specs 00 and 01).

| Field | Meaning |
|---|---|
| `id` | `Q-####`, assigned by code, unique in the project, never reused |
| `stage` | the `DocType` of the stage that raised it |
| `run_id` | the team run that raised it |
| `refs` | item references, requirement ids or intake lines the question concerns (may be empty) |
| `text` | the question, as the agent wrote it |
| `status` | `open`, `answered` or `withdrawn` |
| `asked` | the date it was recorded, ISO `YYYY-MM-DD` |
| `answer`, `answered_by`, `answered` (ISO date), `dr_id` | set together when the status becomes `answered`; none of them is set otherwise |

`Question` is a frozen Pydantic model; `schemas/Question.schema.json` is generated from it and drift-tested. Commits follow section 5 of the constitution: `question(PRJ-001): add Q-0007`, `question(PRJ-001): answer Q-0007`, `question(PRJ-001): withdraw Q-0007`.

## 3. Capturing questions

After `team.finish` of any stage run (done or escalated), the pipeline records the run's questions: `record_questions(store, run_id, stage, drafts)`. The producers above return structured drafts (`refs`, `text`) instead of formatted strings; the strings of `StageResult.open_questions` are built from them, so the printed output stays the same.

- **Deduplication.** Two questions are the same when their normalised text is the same (NFKC, lower case, no spaces or punctuation, as in `calibration.normalise`). A draft that matches an `open` or `answered` question adds nothing. A draft that matches an `answered` one is counted in `StageResult.reasked`: it means the confirmed facts of section 5 did not reach the prompt or the model ignored them.
- **Nothing blocks.** The writer still states only what the source says and the QA reviewer still downgrades a `customer_question` issue. The ledger is written after the run record and changes nothing inside the loop.
- **Escalated runs too.** The rule that nothing business-related is written on escalation keeps its meaning: a question is not a requirement, a document or a link, and it explains the escalation.
- `StageResult` gains `question_ids` (the questions of this run, new or existing) and `reasked`.

## 4. Answering: the answer becomes a Decision Record

`answer_question(store, question_id, answer, by)`:

1. The question must be `open`; `answer` and `by` must be non-empty.
2. `new_dr` creates a `clarification` DR. Its description is `Q-0007: <question text>`; its impacted items are the question's `refs` that are known trace nodes (intake lines and unknown references are dropped; a clarification may have none).
3. `approve_dr` approves it with `approver = by` and `decision = answer`. The impact analysis is stored as for any DR.
4. The question is saved as `answered` with the answer, the name, the date and the DR id.

`dr propagate` stays a separate, explicit step (`manual_gate`, spec 07): it revises the documents the DR reaches, if any exist. When the stage escalated and no document exists yet, the DR has no affected documents and simply records the decision; the next run uses it (section 5).

`withdraw_question(store, question_id, by)` moves an `open` question to `withdrawn` without a DR, for a question that no longer applies.

Who may answer: approver or admin. In the API the recorded name is the signed-in user, never a field the client sends (as for `dr approve`). The answerer signs the decision; separating the answerer from the approver is possible with the `dr` commands by hand and is outside this spec.

## 5. Using the answers

`confirmed_facts(store)` lists the answered questions whose DR is approved or later (`approved`, `propagated`, `closed`). Every model call that reads the project's source material gets them as a block:

```text
<confirmed>
Q-0007 [DOC-SRS-0001#item.5]: What does the three business days count from? -> From the moment the manager receives the request. (DR-0004)
</confirmed>
```

- It is added to the user message of each writer (requirements analyst, SRS writer, designer, tester, detail designer, unit-test designer, document reviser) and to the `upstream` that QA receives.
- The prompts say that a confirmed fact is part of the source: the writer does not ask about it again and does not treat it as an invention, and QA raises no `customer_question` about it.
- The block is built for every call, so a resumed run sees answers given after it escalated. Answers do not change `RunCheckpoint.upstream`: they are meant to be used by the run that waits for them.
- The block carries the whole ledger of answers. If it grows past what a prompt can hold, selecting the relevant ones is a job for retrieval (open point 5).

## 6. Surfaces

- **CLI:** `masterba question list --project P [--status open|answered|withdrawn]`, `question show Q-0007`, `question answer Q-0007 --by NAME --text TEXT`, `question withdraw Q-0007 --by NAME`. Stage output gains `question_ids` and `reasked`.
- **API** under `/api/projects/{pid}/questions`: `GET` (viewer; `?status=` filter), `GET /{qid}`, `POST /{qid}/answer` with `{"answer": "..."}` (approver), `POST /{qid}/withdraw` (approver). Same error mapping and CSRF header as the other routes.
- **Dashboard:** a Questions tab that shows the number of open questions, lists open questions first with their references (each a link to its document or requirement), the stage and run that raised it, and an answer form. An answered question shows its DR as a link. The overview stage card shows "N open questions" with a link to the tab.

## 7. Tests

- Model: field rules for each status; the `Q-####` id pattern; schema drift.
- Store: add, deduplicate by normalised text, count a re-asked answered question, id assignment that never reuses a number, one commit per action.
- Pipelines (fake model): each of the four producers lands in the ledger; an escalated run records its questions; `question_ids` and `reasked` in the result.
- Answer: the DR is `clarification`, approved, with the answer as decision and the answerer as approver; an unknown or intake ref does not fail the call; a second answer to the same question is refused; a failure creating the DR leaves the question `open`.
- Prompts: the `<confirmed>` block reaches every writer and QA call, including after `--resume`; absent when there is no answer.
- CLI end to end and API permissions (a viewer cannot answer or withdraw).

## 8. Acceptance criteria

- [ ] A stage run records its open questions in `questions/` with no change to the loop, the gates or the exit code.
- [ ] Answering a question creates and approves a clarification DR carrying the answer, and links it from the question.
- [ ] A run, and a resumed run, started after an answer has the confirmed fact in every writer and QA prompt.
- [ ] `masterba question list|show|answer|withdraw`, the API routes and the dashboard tab work, with the roles of section 4.
- [ ] A live run on the HRM intake ends with its questions in the ledger, and after answering them a second run shows `reasked` of zero. Recorded in section 10 with counts.
- [ ] `uv run pytest`, `ruff` and `mypy` pass; coverage stays above 80%.

## 9. Constitution changes needed (Vietnamese file, separate commit)

`specs/00-constitution.md` gets, in its "Sửa đổi" section: the ID `Q-####` in the table of section 3, the folder `questions/` in the project layout of section 2, and the commit scope `question` in section 5.

## 10. Review record

Empty until the implementation.

## 11. Open points

1. Near-duplicate questions (the same doubt worded differently each round) stay separate; only equal normalised text is merged.
2. A person cannot add a question by hand yet; the ledger holds only what agents raised.
3. Notifying the product owner (mail, chat) is not covered.
4. Stopping a run early when only open questions are left (`needs_input`) is left out: the dry-runs showed the loops spending rounds on other things, and the ledger already keeps the run from depending on an answer.
5. A long ledger of answers will not fit every prompt; choosing the relevant answers belongs with the local RAG phase.

## Delivery order

1. Constitution amendment (Vietnamese), then models, the id pattern and the store (add, list, answer, withdraw).
2. Pipelines record questions; `StageResult` fields.
3. `confirmed_facts` and the prompt and QA changes.
4. CLI, then API, then the dashboard tab.
5. Live run, review record, `docs/architecture` updates.

## Risks and rollback

- A flood of near-duplicate questions makes the ledger noisy (open point 1). Withdrawing a question is cheap.
- An answer typed carelessly becomes a confirmed fact for every later run. The DR keeps who said it and when; a wrong answer is overridden by a new clarification DR, and the ledger keeps both.
- Rollback: the ledger is additive files plus one extra block in prompts. Removing the block returns every prompt to its present text.
