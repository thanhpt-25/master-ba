# Spec 16 — Blocker-aware stops, resume and token limits

Status: approved and implemented (2026-11-13).

## Goal

Avoid spending another full writer/QA round when the current blocker needs a customer decision or has not changed after a targeted repair. Preserve the current draft and token count so a person can answer the blocker and resume the same run.

## Decisions

1. A QA issue marked `customer_question: true` and still blocking after checklist severity is applied means the team must wait for input. It is recorded as a `qa_blocker` question, the validated draft is checkpointed, no business artifact is committed, and the run ends `waiting_for_input`.
2. Answering or withdrawing every `qa_blocker` question for that run unlocks Resume. Resume continues the same run with its checkpoint, confirmed facts and cumulative token count. Starting a new run while the unanswered blocker exists is refused.
3. A repair has made no progress when the same non-empty set of `(checklist_id, ref)` blockers remains after a writer revision. Stop then as `escalated` with a `no progress` reason; do not spend the remaining configured rounds on the same feedback.
4. A resume from the dashboard adds one round by default. CLI callers may explicitly request more. Token usage and budget are cumulative for the run; changing the project budget is an audited admin action.
5. New projects default to a 100,000-token hard budget per run. Admins can change or disable it. Existing projects keep their stored budget (including `null`) until an admin changes it. Emit one warning at 80%; the hard limit still stops before the next model call.
6. These stops do not weaken checklist gates. A person may answer or withdraw a blocker; only a successful QA run can produce business documents.

## Data and flow

- Add `waiting_for_input` to `TeamRunStatus` and the job result status. Old run records remain valid.
- Save the last validated draft and the exact role feedback before finishing a waiting run. The next call after an answer is routed only to the role(s) whose artifact was blocked; QA checks the revised artifact again.
- On a waiting run, the Activity view lists its open blocker-question IDs and disables Resume until they are answered or withdrawn. The Questions view links each objection to its run.
- The stage overview shows `waiting_for_input` separately from `escalated`; both preserve their run and checkpoint.
- `team_token_budget` is shown at project creation and is editable by admins from the project overview. A budget change is committed with the project config and never resets usage already recorded in a run.

## Acceptance criteria

- A blocking customer question ends the run in `waiting_for_input`, records the question, preserves checkpoint, and writes no business document.
- The API refuses a fresh stage run or resume while a waiting run has an open QA blocker; after answer/withdrawal, the same run resumes and the answer reaches the model.
- If the exact blocking `(checklist_id, ref)` set is unchanged after a repair, the run escalates before starting another round; a reduced blocker set continues normally.
- Writer, tester and QA calls all count toward the hard budget. A resume does not reset tokens; a project budget edit is auditable.
- New project creation defaults to 100,000 tokens; an admin can edit the budget or set it to unlimited. Viewer and approver roles cannot change it.
- Tests cover both team loops, API resume rules, question ledger, UI labels/actions, and old project/run files without the new fields.

## Non-goals

- Chunking large documents or patching individual generated items (planned for the convergence-and-scale phase).
- Automatic approval or waiver of QA blockers.
- Provider price conversion; the budget is in tokens, not currency.
