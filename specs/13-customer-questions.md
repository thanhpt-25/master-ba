# Spec 13 — Customer questions ledger

Status: v0.3 (2026-11-01), approved by the owner and implemented; v0.3 drops the unused name option of withdraw (section 4). v0.2 answers a review of v0.1 (13 findings, see section 12). Sources: dry-runs 4 and 5 ([11-hardening.md](11-hardening.md) section 10.3 and section 11), [architecture/04-team-runtime-control-flow.md](../docs/architecture/04-team-runtime-control-flow.md), [architecture/05-change-management-flow.md](../docs/architecture/05-change-management-flow.md), [07-change-management.md](07-change-management.md). The number 12 stays with the local RAG phase in [../docs/next-steps.md](../docs/next-steps.md); this spec does not depend on it.

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

A point that only the customer or the product owner can settle is written into a project **ledger of questions** as soon as an agent finds it. The run does not wait for it: what is clear goes on, what is unclear is recorded. When a run escalates, the objections that QA still held are recorded too, so a person can settle them instead of the team spending more rounds. When the product owner answers, the answer is finalised as an approved **Decision Record**, and every later run and every propagation uses it as a confirmed fact.

The rule, in the owner's words: clear parts keep running; unclear parts go into the Q&A ledger; the answers are fixed as decision records.

What this does and does not change: it gives open points a place to be answered, and it ends the cheapest kind of waste, a run that escalates with its reasons visible only in a log. It does not stop a run from looping on a point that no agent or reviewer flagged as unclear; the review of v0.1 and open point 4 say so plainly.

## Non-goals

- No automatic delivery of questions to the product owner (mail, chat). The ledger is read in the CLI, the API and the dashboard.
- No waiting state and no new run status. A stage still ends `done` or `escalated` exactly as today, and a later stage may run while questions are open (nothing at the start of a stage reads the ledger).
- No answers written by a model. Only a signed-in person (or the CLI `--by`) answers.
- No threads, comments or editing of a question's text.
- No change to the loops, the gates or the QA normalisation of [11-hardening.md](11-hardening.md).
- DR propagation runs ([07-change-management.md](07-change-management.md)) are not covered: the questions their reviewers raise stay in the run record.

## 1. Problem

Questions for the customer are produced in four places and only reported:

| Producer | Today |
|---|---|
| BRD analyst: `open_questions` with intake lines | printed in `StageResult.open_questions` |
| SRS writer: `open_questions` with requirement ids | same |
| QA: an issue with `customer_question` set | downgraded to advisory, collected as a string in `TeamRun.customer_questions` |
| Tester: a question about an item the designer already answered | posted to the `customer` mailbox, returned as the string list `unresolved` |

Nothing reads an answer. In dry-run 5 the team collected 13, then 17, then 27 open questions while it looped for 12 rounds and 513,292 tokens, and a person had no place to answer ("is deleting an employee in scope?", "what does the three business days count from?"). The only way to carry a decision into the documents is a `clarification` Decision Record written by hand, and it reaches documents that already exist, not the next run of a stage that escalated.

## 2. The ledger

A question is one file, `projects/<project_id>/questions/Q-####.json`, in the project like every other store entity (specs 00 and 01).

| Field | Meaning |
|---|---|
| `id` | `Q-####`, assigned by code, unique in the project, never reused |
| `origin` | `agent` (an open question an agent raised) or `qa_blocker` (an objection QA still held when the run escalated, section 3) |
| `stage` | the `DocType` of the stage that raised it |
| `run_id` | the team run that raised it |
| `refs` | stable references the question concerns (section 3); may be empty |
| `text` | the question, as the agent wrote it |
| `status` | `open`, `answered` or `withdrawn` |
| `asked_on` | the date it was recorded, ISO `YYYY-MM-DD` |
| `answer`, `answered_by`, `answered_on` (ISO date), `dr_id` | set together when the status becomes `answered`; none of them is set otherwise |
| `source` | optional, only on an answered question: who gave the answer outside the system and where ("Tanaka, meeting 2026-11-02") |

`answered_by` is the signed-in person who recorded the answer; `source` is the person or occasion it came from. The DR's `approver` is `answered_by`; `source` goes into the DR's `rationale`.

`Question` is a frozen Pydantic model; `schemas/Question.schema.json` is generated from it and drift-tested. Commits follow section 5 of the constitution: `question(PRJ-001): add Q-0007`, `question(PRJ-001): answer Q-0007`, `question(PRJ-001): withdraw Q-0007`.

## 3. Capturing questions

After `team.finish` of a BRD, SRS, basic design or detail design run (done or escalated), the pipeline records the run's questions: `record_questions(store, run_id, stage, drafts)`. The ledger is written after the run record and changes nothing inside the loop.

**Structured drafts.** Today QA and the tester produce strings such as `ref: message`, and the run record keeps them as strings (`TeamRun.customer_questions` does not change, so `team-summary.json` and its schema stay as they are). The runtime gains a second, structured channel: `Team.question_drafts`, a list of `QuestionDraft(origin, refs, text)`. The BRD analyst and SRS writer drafts, `QaReview` (a `question_drafts` field next to its strings) and the design loop's unresolved questions fill it. The strings of `StageResult.open_questions` stay as they are.

**References.** A reference is stored only if it is stable when it is recorded: a requirement id or an item of a stored document that is a known trace node at that moment, or an intake line. A draft's own item numbers are positional, so in an escalated run they do not name anything yet and a later run may give the same number to a different item; such references are not stored, and the question text keeps the context. When the run is done, its own documents are stored before the questions are recorded, so its references are kept.

**Objections at escalation.** When a run ends `escalated`, the blocking issues QA still held in its last review are recorded as `qa_blocker` questions. The text names the checklist rule, the issue and where it sits, in words (for example `QA, RUN-0008, item 4 of the draft test list: <issue>. Specify the missing detail or accept the draft as it is.`). At most 10 are recorded, in the order QA gave them; the number left out is added to the run's escalation reasons. Gate errors are not recorded: they say what the writer must fix, not what a person must decide.

**Deduplication.** Two questions are the same when their normalised text is the same (NFKC, lower case, no spaces or punctuation, as in `calibration.normalise`); references are not part of the key and are not merged into an existing question. A draft that matches an `open`, `answered` or `withdrawn` question adds nothing, so a withdrawn question that agents keep raising does not come back. A draft that matches an `answered` one is counted in `StageResult.reasked`.

**Result.** `StageResult` gains `question_ids` (the questions of this run, new or existing) and `reasked`.

**Escalated runs too.** The rule that nothing business-related is written on escalation keeps its meaning: a question is not a requirement, a document or a link, and it explains the escalation.

## 4. Answering: the answer becomes a Decision Record

`answer_question(store, question_id, answer, by, source=None)`:

1. The question must be `open`; `answer` and `by` must be non-empty and the answer must pass the checks of section 5.
2. A `clarification` DR is created. Its description is `Q-0007: <question text>`; its impacted items are the question's `refs` that are trace nodes (intake lines are dropped; a clarification may have none). If an earlier attempt already left a `proposed` or `approved` clarification DR whose description starts with `Q-0007:`, it is reused instead of creating another.
3. The DR is approved with `approver = by`, `decision = answer` and `rationale = source`. The impact analysis is stored as for any DR.
4. The question is saved as `answered` with the answer, the name, the source, the date and the DR id.

The steps are separate commits, so a failure between them leaves the DR in the state reached and the question `open`; running the same answer again resumes from there and creates no second DR.

`dr propagate` stays a separate, explicit step (`manual_gate`, spec 07): it revises the documents the DR reaches, if any exist. When the stage escalated and no document exists yet, the DR has no affected documents and simply records the decision; the next run uses it (section 5).

`withdraw_question(store, question_id)` moves an `open` question to `withdrawn` without a DR, for a question that no longer applies. It takes no name: the question has no field for who withdrew it, and the git history of the commit is the record.

Who may answer: approver or admin. The person at the keyboard is often a business analyst writing down what the product owner said, which is why `source` exists. In the API the recorded name is the signed-in user, never a field the client sends (as for `dr approve`). Separating the answerer from the approver is possible with the `dr` commands by hand and is outside this spec.

## 5. Using the answers

`confirmed_facts(store)` lists the `clarification` Decision Records that count as decided, in id order. A DR counts when its status is `approved` or `propagated`, or `closed` with a stored impact analysis: a rejected DR is also `closed`, but it never had an impact analysis, so it does not count. A DR written by hand with `dr new --trigger clarification` counts the same as one made from a question, which is how an earlier answer is overridden: a later DR on the same point wins.

Every model call that reads the project's source material gets the facts as a block:

```text
<confirmed>
DR-0004 [DOC-SRS-0001#item.5]: Q-0007: What does the three business days count from? -> From the moment the manager receives the request.
</confirmed>
```

- It is added to the user message of each writer (requirements analyst, SRS writer, designer, tester, detail designer, unit-test designer, document reviser) and to the `upstream` that QA receives.
- The prompts say that the block is data, never instructions, and that a confirmed fact is part of the source: the writer does not ask about it again, does not treat it as an invention, and applies the later decision when two disagree. QA raises no `customer_question` about it.
- Input rules: an answer is at most 2,000 characters, has no control characters, and may not contain `</confirmed>`; when the block is rendered, angle brackets in the question and answer text are replaced, so text from a model or a person cannot close the block. The text is shown in the dashboard as text nodes, like every other model output.
- The block is built for every call, so a resumed run sees answers given after it escalated. Answers do not change `RunCheckpoint.upstream`: they are meant to be used by the run that waits for them.
- The BRD gate still requires every requirement to cite intake lines, so a confirmed fact can clarify the wording of a BRD requirement but cannot be the source of a new one.
- The block carries every fact. If it grows past what a prompt can hold, selecting the relevant ones is a job for retrieval (open point 5).

## 6. Surfaces

- **CLI:** `masterba question list --project P [--status open|answered|withdrawn]`, `question show Q-0007`, `question answer Q-0007 --by NAME --text TEXT [--source TEXT]`, `question withdraw Q-0007`. Stage output gains `question_ids` and `reasked`.
- **API** under `/api/projects/{pid}/questions`: `GET` (viewer; `?status=` filter), `GET /{qid}`, `POST /{qid}/answer` with `{"answer": "...", "source": "..."}` (approver), `POST /{qid}/withdraw` (approver). Same error mapping and CSRF header as the other routes.
- **Dashboard:** a Questions tab that shows the number of open questions, lists open questions first, marks `qa_blocker` ones as objections, shows their references (each a link to its document or requirement), the stage and run that raised them, and an answer form with a source field. An answered question shows its DR as a link. The overview stage card shows "N open questions" with a link to the tab.

## 7. Tests

- Model: field rules for each status and origin; the `Q-####` id pattern; schema drift.
- Store: add, deduplicate by normalised text (including a withdrawn match), count a re-asked answered question, id assignment that never reuses a number, one commit per action.
- References: an unknown draft reference in an escalated run is not stored; the same reference in a done run is; intake lines are kept and dropped from the DR.
- Pipelines (fake model): each of the four producers lands in the ledger; an escalated run records at most 10 `qa_blocker` questions and notes the rest; gate errors are not recorded; `question_ids` and `reasked`; `TeamRun` and its schema are unchanged.
- Answer: the DR is `clarification`, approved, with the answer as decision, the answerer as approver and the source as rationale; a second answer to the same question is refused; an answer run again after a failure between steps reuses the DR and creates no second one.
- Facts: a hand-made clarification DR counts; a rejected DR does not; the later of two DRs on one point comes last; the block neutralises angle brackets and refuses an answer containing `</confirmed>` or over 2,000 characters.
- Prompts: the `<confirmed>` block reaches every writer and QA call, including after `--resume`; absent when there is no fact.
- CLI end to end and API permissions (a viewer cannot answer or withdraw).

## 8. Acceptance criteria

- [ ] A stage run records its open questions in `questions/` with no change to the loop, the gates or the exit code, and an escalated run also records its objections (at most 10).
- [ ] Answering a question creates and approves a clarification DR carrying the answer, and links it from the question; running the answer again after a failure creates no second DR.
- [ ] A run, and a resumed run, started after an answer has the confirmed fact in every writer and QA prompt, and a rejected DR is not among the facts.
- [ ] `masterba question list|show|answer|withdraw`, the API routes and the dashboard tab work, with the roles of section 4.
- [ ] A live run on the HRM intake ends with its questions in the ledger. After they are answered, a second run raises fewer new questions than the first, and the owner reads both lists to check that none of them repeats an answered point in other words. Both counts are recorded in section 10.
- [ ] `uv run pytest`, `ruff` and `mypy` pass; coverage stays above 80%.

## 9. Changes to other documents

- `specs/00-constitution.md` (Vietnamese, separate commit), in its "Sửa đổi" section: the ID `Q-####` in the table of section 3, the folder `questions/` in the project layout of section 2, the commit scope `question` in section 5.
- `specs/01-data-contracts.md` (Vietnamese, same commit): `Question` in the entity table of section 2, the file in the layout of section 3, the store functions in section 4.
- `docs/architecture/`: the ID table and layout of document 2, the question flow in documents 3 and 4, the answer-to-DR flow in document 5, the new tab and routes in document 6.

## 10. Review record

Empty until the implementation.

## 11. Open points

1. Near-duplicate questions (the same doubt worded differently each round) stay separate; only equal normalised text is merged.
2. A person cannot add a question by hand yet; the ledger holds only what agents and QA raised.
3. Notifying the product owner (mail, chat) is not covered.
4. A run can still loop on a point that neither an agent nor QA marked as unclear, and objections are recorded only when the run escalates. Stopping earlier (a `needs_input` state, or recording an objection that survives two reviews) is left out until the ledger shows how often it would help.
5. A long list of facts will not fit every prompt; choosing the relevant ones belongs with the local RAG phase.
6. A DR written by hand with `dr new --trigger clarification` becomes a prompt fact as soon as it is approved, which is intended, but a long free-text description is not limited the way an answer is.

## 12. What changed from v0.1

| # | Finding of the review | Change |
|---|---|---|
| 1 | A draft's own item numbers in an escalated run point at nothing, or at another item later | section 3: only stable references are stored |
| 2 | The ledger does not stop a loop that nobody flagged | Goal made precise; section 3 records QA's objections at escalation; open point 4 |
| 3 | An override by a new DR never reached the prompts | section 5: facts come from clarification DRs, not from answered questions |
| 4 | "`reasked` is zero" could not be measured | section 8: compare the new questions of two runs by reading them |
| 5 | QA and the tester only produce strings | section 3: a structured channel in `Team`; `TeamRun` unchanged |
| 6 | The typist and the source of an answer are different people | `source` field, passed to the DR rationale |
| 7 | Typed answers entering a prompt | section 5: data not instructions, a length limit, bracket neutralising |
| 8 | A withdrawn question could be re-added; references on a match were undefined | section 3: withdrawn matches too; references are not merged |
| 9 | The BRD gate needs intake lines | section 5 says facts only clarify the BRD |
| 10 | DR propagation questions had no home | non-goal |
| 11 | Answering is three commits and can fail between them | section 4: a retry reuses the DR |
| 12 | Spec 01 and the architecture documents also change | section 9 |
| 13 | The date field `answered` shared its name with a status | `asked_on`, `answered_on` |

## Delivery order

1. Constitution and data-contracts amendments (Vietnamese), then models, the id pattern and the store (add, list, answer, withdraw).
2. The structured channel, the pipelines record questions and escalation objections; `StageResult` fields.
3. `confirmed_facts`, the `<confirmed>` block and the prompt and QA changes.
4. CLI, then API, then the dashboard tab.
5. Live run, review record, `docs/architecture` updates.

## Risks and rollback

- A flood of near-duplicate questions makes the ledger noisy (open point 1). Withdrawing a question is cheap, and a withdrawn one is not added again.
- An answer typed carelessly becomes a confirmed fact for every later run. The DR keeps who recorded it, the source and when; a wrong answer is overridden by a new clarification DR, which now reaches the prompts.
- An objection recorded at escalation asks a person to decide something the writer could have fixed. The cap of 10 and the origin mark keep it readable; a person can withdraw it.
- Rollback: the ledger is additive files plus one extra block in prompts. Removing the block returns every prompt to its present text.
