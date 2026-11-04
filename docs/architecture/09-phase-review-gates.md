# 9. Phase review gates

A person reviews each phase before the next one starts. The spec is
[specs/15-phase-review-gates.md](../../specs/15-phase-review-gates.md).

## 9.1 The flow

```text
run <stage> ─▶ done ─▶ documents in_review ─┬─ approve ─▶ approved ─▶ next stage may start
                                            └─ reject  ─▶ review_feedback DR ─▶ version n+1 in_review
```

| Phase | Documents reviewed together | Next |
|---|---|---|
| `brd` | `DOC-BRD-0001` | `srs` |
| `srs` | `DOC-SRS-0001` | `basic` |
| `basic` | `DOC-BASIC_DESIGN-0001`, `DOC-TEST_IT-0001`, `DOC-TEST_ST-0001` | `detail` |
| `detail` | `DOC-DETAIL_DESIGN-0001`, `DOC-TEST_UT-0001` | none |

- **Setting.** `ProjectConfig.review_gates`. `init-project` and the dashboard write `true` unless
  asked not to (`--no-review-gates`); a `project.json` without the field loads with gates off.
- **Storing.** `pipeline/stage.store_document` takes the status from `review.initial_status`:
  `in_review` with gates, `draft` without.
- **Gate.** `review.require_reviewed` runs before `Team.open` in `run_srs`, `run_basic_design` and
  `run_detail_design`. It refuses while any document of the previous phase is `in_review` and names
  the command to run. `draft` passes: only a Decision Record or a run without gates writes one.
- **Approve.** `approve_phase` writes `reviews/REV-####.json` and sets every document of the phase to
  `approved` in one commit, then renders the workbooks again because they print the status. Open
  customer questions are listed as a warning and stored in the review; they keep reaching later stages
  through `<open_questions>`.
- **Reject.** `reject_phase` checks the comments (item refs must be active items of the phase), then
  creates and approves a Decision Record with trigger `review_feedback`. Its propagation (spec 07)
  writes each revised document as version n+1 `in_review` and sets version n `superseded`, so item ids
  stay stable. A revision that escalates leaves version n in review; the review names the run.
- **Status changes.** `trace_store.set_document_status` rewrites only `document.status` of a stored
  version; the content never changes.
- A phase whose next phase has started cannot be approved or rejected again; it changes through a
  Decision Record.

## 9.2 Surfaces

| Surface | Commands or routes |
|---|---|
| CLI (`cli_review.py`) | `masterba review status`, `list`, `approve --stage S --by NAME`, `reject --stage S --by NAME --comment TEXT ...` |
| API (`api/routes_reviews.py`) | `GET /api/projects/{pid}/reviews` (viewer), `POST /api/projects/{pid}/stages/{stage}/approve` (approver), `POST /api/projects/{pid}/stages/{stage}/reject` (approver, a background job) |
| Dashboard | A workflow strip on the overview (phases, gates, next action, links to questions, Decision Records and the knowledge base); Approve and Reject with comments on a phase card in review; the next Run button waits with the reason |

The reviewer is the signed-in user on the dashboard. A refused action is HTTP 409.
