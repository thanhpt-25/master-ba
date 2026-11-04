# Spec 15 — Phase review gates

Status: v0.2 (2026-11-04), approved by the owner; v0.2 records the approval of v0.1 without other changes. Sources: the owner's request of 2026-11-04 ("the system needs to ask the user for a review between phases before going to the next step") and the owner's answers to four design questions (section 9), [00-constitution.md](00-constitution.md), [01-data-contracts.md](01-data-contracts.md), [07-change-management.md](07-change-management.md) (Decision Records and propagation), [08-dashboard.md](08-dashboard.md) (roles, jobs), [13-customer-questions.md](13-customer-questions.md) (open questions).

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

A person reviews the documents of each phase before the next phase starts. When a stage run ends `done`, its documents wait for review. An approver either approves them, which lets the next stage start, or rejects them with comments, which sends the comments to a writer and QA team that produces a new version for another review.

## Non-goals

- Reviewing documents written by Decision Record propagation. A DR is already signed by an approver; its revised versions follow spec 07 unchanged.
- Partial approval (some items of a document, or one of the three Basic Design documents).
- Notifying the reviewer by mail or chat.
- A command that runs every stage in one go. Stages are already run one at a time; this spec makes the hand-over between them explicit.

## 1. Phases and their documents

| Phase (`--stage`) | Documents reviewed together | Next phase |
|---|---|---|
| `brd` | `DOC-BRD-0001` | `srs` |
| `srs` | `DOC-SRS-0001` | `basic` |
| `basic` | `DOC-BASIC_DESIGN-0001`, `DOC-TEST_IT-0001`, `DOC-TEST_ST-0001` | `detail` |
| `detail` | `DOC-DETAIL_DESIGN-0001`, `DOC-TEST_UT-0001` | none |

A phase is reviewed as a whole: its documents were written by one team run and check each other (design and tests), so they are approved or rejected together.

## 2. The setting

`ProjectConfig.review_gates: bool`, additive. The model default is `false`, so a `project.json` written before this spec loads unchanged and its project behaves as before. `masterba init-project` and the dashboard's project creation write `true` unless `--no-review-gates` is given (owner decision 3: on by default for new projects; scripted dry runs and live tests may turn it off).

With `review_gates: false` nothing in this spec applies: documents are stored as `draft` and every stage starts as soon as its upstream document exists.

## 3. Life of a phase with gates on

```text
run <stage> ─▶ done ─▶ documents in_review ─┬─ review approve ─▶ approved ─▶ next stage may start
                                            └─ review reject  ─▶ revision run ─▶ version n+1 in_review ─▶ (review again)
```

1. **Stage run.** When the team run ends `done`, the stage stores its documents with `status: in_review` instead of `draft`. An escalated run stores nothing, as today. The stage summary and the dashboard say the phase is waiting for review.
2. **Gate on start.** `run srs`, `run basic` and `run detail` refuse to start unless the latest version of every document of the previous phase has `status: approved`. The error names each document, its version and status, and the command to approve it, for example: `DOC-BRD-0001 v1 is in_review; approve the brd phase first: masterba review approve --project PRJ-001 --stage brd --by NAME`. The check runs before the team opens, so a refused start writes nothing.
3. **Approve.** `review approve` sets the latest version of each document of the phase to `approved` and records a review (section 4). The next stage may then start.
4. **Reject.** `review reject` records a review with the reviewer's comments and starts a revision run (section 5). The revised documents come back as version n+1 in `in_review`; the rejected version is set to `superseded`.

Only the latest version of a document can be approved or rejected, and only while its status is `in_review`. A phase whose next phase has already started can no longer be rejected: changing it from then on goes through a Decision Record, as for any stored document (spec 07).

## 4. Review records

Each approve or reject writes `reviews/REV-####.json` (a new id kind, `REV-` plus four digits, assigned by code, never reused) and changes the documents' `status`, in one commit:

- `review(PRJ-001): approve srs (DOC-SRS-0001 v1)`
- `review(PRJ-001): reject basic (DOC-BASIC_DESIGN-0001 v1, DOC-TEST_IT-0001 v1, DOC-TEST_ST-0001 v1)`

`Review` (frozen model): `id: ReviewId`, `stage: brd|srs|basic|detail`, `documents: list[{doc_id, version}]`, `decision: approved|rejected`, `by: str` (the signed-in user on the dashboard, `--by` on the CLI), `at: datetime` (UTC, to the second, serialised `2026-11-04T03:14:29Z`), `comments: list[ReviewComment]` (required and non-empty for `rejected`, empty for `approved`), `open_questions: list[QuestionId]` (the open questions of the ledger at the time of the decision), `revision_run: RunId | None` (set when the revision run ends).

`ReviewComment`: `ref: ItemRef | None` (an item of one of the phase's documents, or none for the whole phase) and `text: str` (1 to 2,000 characters, no control characters).

Changing `status` rewrites only the `document.status` field of the stored version file; the content of a version never changes, and a test checks that. Status is metadata about the version, not part of what was written.

## 5. Rejecting with comments: the revision run

Owner decision 1: the comments go to a writer and QA team, which writes a new version that comes back for review.

The revision reuses the Decision Record propagation of spec 07, so item ids stay stable (the ID Stability Rule) and every change is a reviewed patch:

1. `review reject` creates a Decision Record with the new trigger `review_feedback`. Its description is the reviewer's comments, its impacted items are the item refs the comments name (or the phase's documents when no comment names an item), its affected documents are exactly the documents of the phase, and the reviewer approves it at once with the decision "Revise the <stage> documents as the review comments ask (REV-####)". The DR, the review record and the status changes are separate commits in this order: `dr(P): create DR-####`, `dr(P): approve DR-####`, `review(P): reject ...`.
2. Propagation runs as a background job on the dashboard, or in the foreground on the CLI: one writer and QA team run per affected document, in V order, each producing version n+1. The reviser receives the comments through the DR text; QA reviews the patch with the stage's checklist. The revised version is stored as `in_review`, and the DR ends `propagated`.
3. If a revision run escalates, the document keeps its rejected version (`superseded` is not set until a new version exists), the review record names the escalated run, and the reviewer can reject again with clearer comments or resume the propagation (`masterba dr propagate`).

A `review_feedback` DR never reaches documents of later phases, because none exist yet (section 3).

## 6. Open questions at approval

Owner decision 2: a phase may be approved while customer questions are still open. The approval lists them as a warning (CLI output, and a confirmation on the dashboard) and stores their ids in the review record. They stay in the ledger and keep reaching every later stage through the `<open_questions>` block (spec 13 section 5.1), so no later stage can decide them.

## 7. Surfaces

### CLI

| Command | Effect | Exit code |
|---|---|---|
| `masterba review status --project P` | Each phase: not started, running, escalated, in review, approved, with its documents' versions and statuses | 0 |
| `masterba review approve --project P --stage S --by NAME` | Section 3 step 3; prints the open questions as a warning | 0, or 1 when the phase is not in review |
| `masterba review reject --project P --stage S --by NAME --comment TEXT [--comment ...]` | Section 5; a comment may start with an item ref (`DOC-SRS-0001#item.12: ...`) | 0 when the revision is done, 3 when it escalated, 1 on error |
| `masterba review list --project P` | The review records | 0 |
| `masterba init-project ... [--no-review-gates]` | Section 2 | 0 |

`reject` takes `--model` and `--qa-model` like `dr propagate`.

### API and dashboard

| Route | Role | Effect |
|---|---|---|
| `GET /api/projects/{pid}/reviews` | viewer | The review records and the review state of each phase |
| `POST /api/projects/{pid}/stages/{stage}/approve` | approver | Approve; the response lists the open questions |
| `POST /api/projects/{pid}/stages/{stage}/reject` | approver | Reject with `{"comments": [{"ref": ..., "text": ...}]}`; the revision runs as a background job and the response carries the job |

`by` is the signed-in user; the body has no such field. The project overview shows a phase waiting for review with Approve and Reject controls for approvers. Approve asks for confirmation and lists the open questions; Reject takes comments, each with an optional item. The Run button of the next stage is disabled, with the reason, until the phase before it is approved.

## 8. Tests

- With gates on, a `done` stage stores `in_review`; the next stage refuses to start with the message of section 3 and writes no run folder and no commit.
- Approve sets every document of the phase to `approved` in one commit with the review record; the next stage then runs.
- Reject records the comments, creates and approves a `review_feedback` DR, and produces version n+1 in `in_review` with the comments in the reviser's prompt; version n becomes `superseded`; every item id of version n is present in version n+1.
- An escalated revision leaves version n as it was and names the run in the review record.
- Approving or rejecting a phase that is not in review, an old version, or a phase whose next phase has started is refused and changes nothing.
- Approval with open questions succeeds and stores their ids.
- With gates off the pipeline behaves as before (documents `draft`, no gate); a `project.json` without the field loads with gates off.
- A status change leaves the content of the version file unchanged.
- API: roles (a viewer cannot approve or reject, an approver can), `by` from the session, the `X-MasterBA` header, 404 for an unknown stage, 409 for a phase not in review.
- Live tests and dry-run scripts create their projects with `--no-review-gates` or approve between stages.

## 9. Owner decisions (2026-11-04)

1. On reject, the comments go back to a writer and QA team, which writes a new version for review (not "record only and change through a DR").
2. A phase may be approved with open customer questions, with a warning.
3. The gate is a project setting, on by default for new projects.
4. Implemented after PR #6 is merged (done: `be3462b`).

## 10. Open points

1. Whether the last phase needs a role above `approver`, or a second reviewer. Not in this version.
2. The revision writer is the DR reviser (a patch over the stored document), not the stage's original writer. This keeps item ids stable; the original writers only write whole drafts without ids.
3. Rejecting a phase after the next phase has started is refused; the reviewer uses a Decision Record instead.

## Changes to other documents

- `00-constitution.md` and `01-data-contracts.md` (Vietnamese, in one commit, no code): the `REV-####` id, the `reviews/` folder, the commit scope `review`, `Review`, `ReviewComment`, `ProjectConfig.review_gates`, `DrTrigger.REVIEW_FEEDBACK`, and document `status` set by review actions.
- `docs/architecture/03-pipeline-data-flow.md`, `05-change-management-flow.md`, `06-interfaces-and-deployment.md`, `CLAUDE.md`, `README.md`.

## Delivery order

1. This spec, approved by the owner.
2. The `00` and `01` amendments in one commit, no code.
3. Models and store (`Review`, `review_gates`, status change), then the gate in the four pipelines, then approve and reject with the DR revision, then the CLI, then the API and the dashboard, then the documents.

## Risks and rollback

- A project created with gates on cannot run its stages from an old script that does not approve between stages; the error says what to run. Setting `review_gates` to `false` in `project.json` restores the old behaviour.
- Rewriting the `status` field of a stored version file is new; the content test guards it. If it proves fragile, the status can move to the review records alone without changing the commands.
