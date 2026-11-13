# Spec 04 — SRS, QA reviewer and the Phase Team runtime

Status: v0.2 (2026-10-31), implemented; Acceptance Criteria pass; section 9 records the live review and section 11 the decisions taken while implementing. Sources: [concept-design.md](../docs/concept-design.md) sections 4, 8, 14 (Vietnamese), [roadmap-phases.md](../docs/roadmap-phases.md) Phase 4, [00-constitution.md](00-constitution.md), [01-data-contracts.md](01-data-contracts.md), [03-requirements-analyst-agent.md](03-requirements-analyst-agent.md).

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

Add the second V-model stage (BRD to SRS) and the machinery that makes stages trustworthy: a generic `qa-reviewer-agent` driven by a checklist file, and the first version of the Phase Team runtime (task list, mailbox, round and token limits, escalation, run workspace). From this phase on, both the BRD and the SRS stage run as a two-member team: a writer and a QA reviewer.

## Non-goals

- No Basic Design, tests or three-member team (Phase 5). The runtime is built so Phase 5 can add members, but only the writer + reviewer loop is implemented here.
- No Decision Record creation from an escalation (Phase 7). An escalation is recorded in the run and reported to the user; turning it into a `clarification` DR needs the DR flow.
- No resuming an escalated run. Starting again creates a new run.
- No dashboard view of team activity (Phase 8). The run files are shaped so the dashboard can read them.
- No parallel or concurrent members; the loop is sequential.

## 1. Design decisions

1. **The runtime is a library of primitives plus a loop.** `masterba.team` provides the run workspace, task list, mailbox, budget and escalation. The writer-reviewer loop is one function built on those primitives and reused by the BRD and SRS stages. Phase 5 adds a different loop on the same primitives; nothing here is a general multi-agent framework.
2. **Verdicts are derived by code.** The QA model returns *issues* only; the report fails if and only if it contains a blocking issue. The model never states a verdict, so an inconsistent report cannot exist.
3. **Deterministic gate first, QA second.** A draft must pass the stage's deterministic gate (Phase 3's gate, plus coverage for SRS) before any QA call is paid for. Gate errors go back to the writer as feedback from the sender `gate`.
4. **Single-writer rule is enforced in code**, not only in prompts: each artifact has one owner role, and `Team.write(role, artifact, value)` raises `SingleWriterError` for anyone else.
5. **Nothing is committed to the business store until the team is `done`.** An escalated run leaves only the intake (BRD stage) and the run record.
6. **The reviewer should be able to be a different model** (`--qa-model`), because the same model reviewing its own output shares its blind spots.
7. **Mailbox references draft item refs.** During a run the draft has no stored document yet, so a message refers to an item as numbered in that round's draft (`DOC-SRS-0001#item.3`, position + 1). These are the same refs the items receive on commit, so a human reading the mailbox sees final ids; the writer is shown the previous draft together with the feedback so numbering is unambiguous.

## 2. Run workspace and files

`projects/<project_id>/runs/RUN-####/` (path from spec 00 section 2):

| File | Committed | Content |
|---|---|---|
| `team-summary.json` | yes | A `TeamRun` (spec 01, unchanged): `run_id`, `stage`, `trigger` (`initial`), `status` (`running`, `done`, `escalated`), `rounds`, `issues_raised`, `issues_resolved`, `escalations`, `tokens_used` |
| `team-tasks.json` | yes | List of `TeamTask` |
| `mailbox.json` | yes | List of `TeamMessage`. Added to the committed set by this spec: it is small, typed and is the only record of *why* a run escalated. Spec 00 and concept-design 14.5 list only summary and tasks; spec 00's layout comment is updated |
| `transcripts/` | **no** (gitignored: `projects/*/runs/*/transcripts/`) | Per round: prompts sent, raw model output, the draft and the QA report, for debugging. For an escalated run the last draft is kept here |

`RUN-####` numbers are assigned `max + 1` within the project and never reused. The run is committed once, at the end, as `run(<project_id>): RUN-0001 done` or `... escalated`. In a `done` BRD or SRS stage that commit comes **after** the render commit.

### 2.1 New models (`masterba.team.models`, added to spec 01 as a decision)

```python
class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    DONE = "done"


class TeamTask(FrozenModel):
    id: str  # T-01, T-02 ...
    title: str
    owner: str  # role name, e.g. "writer", "qa"
    status: TaskStatus
    depends_on: list[str] = []


class MessageType(StrEnum):
    QUESTION = "question"
    FEEDBACK = "feedback"
    ANSWER = "answer"
    DONE = "done"


class TeamMessage(FrozenModel):
    sender: str  # "writer", "qa" or "gate"
    to: str
    type: MessageType
    ref: ItemRef | None
    round: int >= 1
    body: str
```

JSON Schemas for both are generated like the other models.

## 3. The loop

```
round = 1
loop:
  budget check          -> if exhausted: escalate("token budget exhausted")
  writer drafts         (round 1: from upstream; later: upstream + previous draft + feedback)
  gate                  -> errors: post feedback from "gate" to writer; next round, no QA call
  QA reviews            -> blocking issues: post feedback from "qa" to writer; next round
                           none: done
  round += 1            -> if round > team_max_rounds: escalate("max rounds reached")
```

Rules:

- **Round** = one writer draft. `rounds` in the summary is the number of drafts produced. `team_max_rounds` comes from `ProjectConfig` (default 3). Phase 3's "retry once" is replaced by this loop for the BRD stage: up to `team_max_rounds` drafts instead of two.
- **Token budget**: `team_token_budget` defaults to 100,000 for newly created projects and may be disabled or edited by an admin. It is compared with the cumulative running total (input + output tokens of every model call, including writer, tester and QA) *before* each call; if the total is at or above the budget the run escalates. A call that crosses the budget is allowed to finish; the next one is not made. Resumes keep the same usage and budget. One warning is emitted at 80%.
- **Done** requires: the gate passed, the QA report has no blocking issue, and no task is `todo`, `in_progress` or `blocked`.
- **Escalated** records one line per unresolved point in `escalations` (the open blocking issues of the last review, the last gate errors, or the budget/round reason) and exits without writing business artifacts. Exit code 3.
- **QA output problems**: an unusable QA report (no tool call, unknown `checklist_id`, a `ref` that is not an item of the draft) is retried once inside the same round without consuming a round; a second failure escalates with the reason `qa output invalid`.
- **Tasks**: round 1 creates `T-01 Draft` (writer) and `T-02 Review` (qa, depends on `T-01`); each further round appends a `Revise (round n)` task and, when the gate passes, a `Review (round n)` task. Tasks are set `done` as they complete; an escalation leaves unfinished ones `blocked`.
- **Issue accounting**: `issues_raised` counts blocking issues across all reviews; `issues_resolved` counts those no longer present (same `checklist_id` and `ref`) in the final review. On `done` they are equal. Advisory issues are posted as `feedback` messages and shown in the CLI output but do not block and are not counted.
- **Single writer**: `Team.write(role, artifact, value)` checks the artifact's owner (`draft` is owned by `writer`, `qa-report` by `qa`) and raises `SingleWriterError` otherwise.

## 4. QA reviewer (`masterba.agents.qa_reviewer`)

### 4.1 Contract

Input: the stage's checklist, the upstream material (intake for BRD, BRD content for SRS), the draft, and the project's document language. Output via tool `submit_qa_report`:

```python
class QaIssue(FrozenModel):
    checklist_id: str  # must exist in the checklist
    severity: Literal["blocking", "advisory"]
    ref: ItemRef | None  # item as numbered in the draft, None for document-level issues
    message: str


class QaReport(FrozenModel):
    issues: list[QaIssue]
```

`verdict` is computed: `fail` iff any issue has `severity == "blocking"`. The report model has no verdict field.

### 4.2 Checklist files

Generic means: **the same code and the same prompt serve every stage; only the checklist file changes.** Checklists are TOML (standard library `tomllib`, no new dependency) in `skills/qa-review/checklists/<stage>.toml`:

```toml
stage = "SRS"

[[checks]]
id = "SRS-01"
severity = "blocking"      # default severity when the model reports it; the model may downgrade, not upgrade
text = "Each statement contains exactly one obligation and uses 'shall'."
```

The model may report an issue with the checklist's severity or lower (blocking to advisory), never higher. Baseline checklists shipped here, derived from the concept-design section 8 baseline and common requirements-quality criteria:

| Stage | Checks (blocking unless noted) |
|---|---|
| BRD | atomic requirement; no solution or implementation detail; verifiable (quantities have a number and unit); no undefined vague wording such as "fast" or "easy" (advisory when an open question already exists); scope `out` only if the intake excludes it; no duplicates or contradictions |
| SRS | one obligation per statement with "shall"; every functional statement is verifiable and has an `acceptance_hint` (advisory for non-functional); non-functional statements are measurable (number, unit, condition); no design or implementation choice; consistent terminology, no contradiction; faithful to the BRD (nothing invented, nothing dropped); no undefined vague wording |

Coverage of the BRD by the SRS is **not** a checklist item: it is checked by the deterministic gate (section 5.2).

### 4.3 Prompt and skill

`agents/qa-reviewer.md` (one prompt, stage-neutral) and `skills/qa-review/SKILL.md`. The code appends the checklist, the language section and the numbered draft. The prompt states that the draft and upstream text are data, not instructions.

## 5. SRS stage

### 5.1 Writer (`masterba.agents.srs_writer`)

Input: the stored BRD (`DOC-BRD-0001`, latest version) as a list of in-scope requirements with their `REQ-####` ids, categories, titles and descriptions; the project language. Output via tool `submit_srs`:

```python
class DraftSrsItem(FrozenModel):
    kind: SrsKind  # functional | non_functional
    statement: str  # "The system shall ..."
    acceptance_hint: str | None
    derives_from: list[ReqId]  # at least one
```

`agents/srs-writer.md` and `skills/srs-from-brd/SKILL.md`. The writer never invents ids; it cites `REQ-####` ids it was given.

### 5.2 Deterministic gate

1. Every `derives_from` id is an existing, active requirement that is in scope in the BRD.
2. **Coverage:** every in-scope active BRD requirement is cited by at least one item.
3. No two items have the same normalised statement.
4. Statements and hints in the project's language (same loose script check as spec 03 section 12).

### 5.3 Pipeline (`masterba.pipeline.srs.run_srs`)

```
load BRD (must exist) -> team loop (writer = srs-writer, reviewer = qa-reviewer + SRS checklist)
-> on done: assign ids  (DOC-SRS-0001, items numbered in draft order,
                         SrsItem.requirement_id = derives_from[0])
-> add_document DOC-SRS-0001 v1 (status draft)
-> add_trace_link REQ-#### -> DOC-SRS-0001#item.n (realizes), one per cited requirement per item
-> render_to_project (SRS template)
-> commit the run record
```

Refuses when an SRS already exists or no BRD exists (changing an approved document is the Decision Record flow, Phase 7). The BRD stage is refactored onto the same loop (`run_brd`, writer = requirements-analyst, reviewer = qa-reviewer + BRD checklist); its output and commits are unchanged except for the added run commit and the larger round limit.

## 6. CLI

```
masterba run brd --project PRJ-001 --input intake.txt [--model M] [--qa-model M] [--reuse-intake]
masterba run srs --project PRJ-001 [--model M] [--qa-model M]
```

`--qa-model` defaults to `--model`. Stdout JSON gains `run_id`, `status`, `rounds`, `issues_raised`, `issues_resolved`, `advisory_issues`, `escalations`. Exit codes: 0 done, 1 error, 2 usage error, 3 escalated.

## 7. Layout

```
agents/qa-reviewer.md   agents/srs-writer.md
skills/qa-review/SKILL.md  skills/qa-review/checklists/{brd,srs}.toml  skills/srs-from-brd/SKILL.md
src/masterba/
  team/       __init__.py  models.py  workspace.py  loop.py
  agents/     qa_reviewer.py  srs_writer.py          # next to requirements_analyst.py
  pipeline/   srs.py  (brd.py refactored)  stage.py  # shared id assignment and commit helpers
tests/ team/  agents/  pipeline/  fixtures/
.gitignore: projects/*/runs/*/transcripts/
```

`tests/fixtures/` gains hand-written BRD-and-SRS drafts for the fake model.

## 8. Acceptance Criteria

- [x] `masterba run brd` then `masterba run srs` on a demo project (fake models in tests) end `done`; each has a committed `team-summary.json`, `team-tasks.json` and `mailbox.json`; the SRS covers every in-scope BRD requirement and the RTM query from a `REQ-####` reaches both its BRD item and its SRS item.
- [x] A QA report with a blocking issue sends feedback to the writer (mailbox message with a draft item ref), the next draft is revised, and the run ends `done` with `issues_raised == issues_resolved`.
- [x] A scripted model that never satisfies QA ends `escalated` after exactly `team_max_rounds` drafts, exit code 3, `escalations` non-empty, **no** requirement, document, link or render written, and the run record committed.
- [x] `team_token_budget` stops the run before the next model call once the total reaches it (test with a budget smaller than one round).
- [x] The same `qa_reviewer` code and prompt are used for BRD and SRS; a test swaps only the checklist file and sees different checks in the request, with no stage-specific branch in the module.
- [x] A QA report with an unknown `checklist_id` or a foreign `ref` is retried once without consuming a round, then escalates as `qa output invalid`; the model cannot raise a severity above the checklist's.
- [x] A gate failure (for example an uncovered BRD requirement) produces `gate` feedback and does not call the QA model.
- [x] `Team.write` by a non-owner raises `SingleWriterError`.
- [x] `git ls-files` shows no file under `runs/*/transcripts/` after a run, the folder exists locally and is ignored.
- [x] Run numbers are sequential and never reused; re-running a stage after an escalation creates `RUN-0002`.
- [x] The commit order for a `done` SRS stage is: documents, links, render, run record, each in the spec 00 message format.
- [x] A live run (`pytest -m live`, key and gateway as in spec 03) completes the BRD and SRS stages on `login_system.txt`; the result is reviewed by hand and recorded in section 9.
- [x] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass; schemas for the new models are generated and drift-tested.

## 9. Manual review record

**2026-10-31, local Anthropic-compatible gateway, project language `en`, intake `login_system.txt`.**

- **BRD stage:** the first run escalated after 3 rounds because the QA model demanded a numeric availability figure the intake never gave, which the writer may not invent (the QA also could not see the writer's open questions). Two fixes followed (section 11, items 2 and 3); the rerun was `done` in 1 round (2,684 tokens, 6 requirements, the vague "make it fast" kept as a requirement plus an open question).
- **SRS stage, same writer and QA model (`auto/best-coding`):** escalated twice (3 rounds each, `max rounds reached (3)`). The draft was correct (the vague item covered, an open question for the missing threshold) but the QA model kept raising SRS-02 (acceptance hint) on a non-functional item and asked to split a sign-in-and-view statement. The machinery behaved as designed: no business artifact was written, run records `RUN-0002` and `RUN-0003` were committed, the reasons are in `escalations`.
- **SRS stage with a stronger reviewer (`--qa-model auto/best-reasoning`):** `done` in 1 round, 2,541 tokens, SRS items and workbook written, open question reported. This supports design decision 6: review quality depends on the reviewer model, so a separate and stronger `--qa-model` is recommended; whether to make it the default is still open (section 10, item 3).

## 10. Open points (do not block implementation)

1. **Clarification DRs.** Escalations are recorded but not turned into Decision Records until Phase 7.
2. **Resuming** an escalated run (reusing the last draft) is not supported; the last draft stays in `transcripts/` only.
3. **Reviewer independence.** A different QA model is supported but not required; whether to make it the default is a cost decision for later.
4. **Phase 5 loop.** The design-test question-and-answer exchange (message types `question` and `answer`) uses the same mailbox but needs a different loop and a third member; it is specified in spec 05.

## 11. Decisions taken while implementing

1. **Per-run `.gitignore`.** `Team.open` writes `runs/RUN-####/.gitignore` containing `transcripts/` and commits it with the run record, so the rule travels with the project and does not depend on a root `.gitignore` (the repository root also ignores `projects/*/runs/*/transcripts/`).
2. **The reviewer sees the writer's open questions.** `brd_draft_view` and the SRS `draft_view` append them, and `agents/qa-reviewer.md` tells the reviewer never to demand a figure, owner or deadline that the upstream material does not contain. The BRD checklist (BRD-03, BRD-04) says that raising an open question for a missing figure is correct. Found in the first live run.
3. **SRS open questions.** `SrsDraft.open_questions` (`question` plus at least one in-scope `REQ-` id) lets the writer cover a vague requirement without inventing a figure. The gate checks the ids and the language; the CLI prints them. SRS-03 (measurability) is now advisory because the BRD may legitimately supply no figure, and SRS-02 allows a missing acceptance hint when an open question explains it. Found in the live SRS run.
4. **Review task timing.** The `Review (round n)` task is created when the gate passes, not up front; a round whose draft fails the gate has only its draft or revise task.
5. **`DraftRejectedError` and `analyse_intake` are gone.** The single-writer-call `write_brd` replaces them; a rejected draft is handled by the loop (gate feedback), and an escalation is a normal `StageResult` with status `escalated`, not an exception.
6. **Transcripts.** `RecordingLLM` writes each request and response, and `Team.write` the draft and QA report of every round, to `transcripts/` (numbered files).
7. **Latent Phase 2 bug fixed.** openpyxl overwrites the workbook `modified` time during `save`, which made re-rendering unchanged content produce different bytes about once in six runs; `xlsxio.workbook_bytes` now patches `docProps/core.xml` (spec 02 decision 9).
8. **`init-project` options** `--team-max-rounds` and `--team-token-budget` set the corresponding `ProjectConfig` fields.

## 12. Changes made by Phase 5

`qa_reviewer.review` and `validate_report` now take `item_counts` (a map from document id to item count) instead of `doc_id` and `item_count`, so one review can cover several documents; `checklist_path` accepts a checklist stem. Behaviour for the BRD and SRS stages is unchanged. See spec 05 section 5 and 11.

## 13. Change made by Phase 7

`Team.open` takes an optional `trigger` (default `initial`) which becomes `TeamRun.trigger`; revision runs started by a Decision Record use the DR id. Nothing else in the runtime changes.
