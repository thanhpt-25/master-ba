# Spec 07 — Change management: Decision Records, impact analysis, propagation

Status: v0.2 (2026-10-31), implemented; all Acceptance Criteria pass. Section 9 records the live run, section 11 the decisions taken while implementing. Sources: [concept-design.md](../docs/concept-design.md) sections 7, 13.3, 13.4 (Vietnamese), [roadmap-phases.md](../docs/roadmap-phases.md) Phase 7, [00-constitution.md](00-constitution.md) (ID Stability Rule, versioning), [01-data-contracts.md](01-data-contracts.md) (`DecisionRecord`, `query_impact`, diff), [04-srs-qa-and-team-runtime.md](04-srs-qa-and-team-runtime.md).

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

Make change safe and traceable. A change to a requirement, a design, a defect or an open customer question becomes a **Decision Record** (DR). A human approves it; the system computes which items and documents are affected (no LLM); on a second human action it revises exactly those documents as new versions, keeping every id stable, re-rendering the Excel files and showing the difference. This delivers original requirement 5 and the `manual_gate` mode of concept-design section 13.4.

## Non-goals

- No dashboard (Phase 8); everything is CLI first and written so the dashboard can call the same functions. Roles (admin, approver, viewer) are enforced there, not here; the CLI records the approver's name it is given.
- No `auto_low_risk` propagation mode (the setting stays in `ProjectConfig`, unused).
- No change to approved history: documents are never overwritten, only new versions are added.
- No new intake text or new BRD generation; a change request is a DR, not an intake.
- No LLM in impact analysis or in the DR lifecycle. The only LLM-driven step is the revision of a document (section 5).

## 1. Lifecycle

```
proposed --approve--> approved --propagate--> propagated --close--> closed
    \--reject------------------------------------------------------^   (closed without propagation)
```

| Command | Effect | Commit |
|---|---|---|
| `masterba dr new --project P --trigger T --description D [--item ID ...]` | creates `DR-####` (`proposed`); `affected_documents` filled by impact analysis | `dr(P): create DR-####` |
| `masterba dr from-run --project P --run RUN-####` | creates a `clarification` DR from an escalated run (section 2.2) | same |
| `masterba dr approve DR --approver NAME --decision TEXT [--rationale TEXT]` | `approved`; impact analysis runs automatically and is stored (section 3) | `dr(P): approve DR-####` |
| `masterba dr reject DR --approver NAME --decision TEXT [--rationale TEXT]` | `closed`; no propagation ever | `dr(P): reject DR-####` |
| `masterba dr propagate DR [--model M --qa-model M]` | revises the affected documents one by one (section 5); `propagated` when all are done | per step, see section 5 |
| `masterba dr close DR` | `closed` after a human has checked the result | `dr(P): close DR-####` |
| `masterba dr list`, `dr show DR`, `dr diff DR` | read only (section 6) | none |

Rules (code, tested): only the transitions above; `approve`, `reject` need non-empty `approver` and `decision` (already enforced by the `DecisionRecord` model once the status leaves `proposed`); `propagate` requires `approved`; a DR is never deleted; ids are `max + 1` and never reused. `date` is the creation day (ISO 8601); the clock is injectable for tests.

New trace-store functions (spec 01 decision): `save_decision_record(store, dr, action)` (rewrite an existing DR as one commit), `list_decision_records(store)`, `update_requirement(store, req)` (same id, new text or status; one commit).

## 2. Creating a DR

`trigger` is one of `requirement_change`, `design_change`, `defect`, `clarification`. `--item` is repeatable and is a `REQ-####` or an item ref (`DOC-SRS-0001#item.3`, or a test id such as `TC-IT-0002`, normalised to its item ref); every id must exist. At least one item is required except for `clarification`.

### 2.1 `affected_documents`

Computed by the impact analysis of section 3 over `impacted_items`, in V-model order. It is recomputed at approval, because the trace graph may have changed since the proposal.

### 2.2 `dr from-run`

For a run whose `team-summary.json` is `escalated`: `trigger = clarification`, `description` = the run id, its stage and the escalation lines, `impacted_items` = every item ref found in those lines and in the run's `mailbox.json` messages that are `question` messages or QA feedback on the last round, no duplicates. This closes the gap left by Phase 4 and 5: an escalation or an unresolved customer question now has a place in the change flow. A clarification DR normally ends with `reject`/`close` by a human who records the customer's answer in `decision`; if the answer changes a requirement, a `requirement_change` DR is created for it.

## 3. Impact analysis (`masterba.change.impact`)

Pure graph query over `query_impact` (no LLM, no writes except the stored result):

| Trigger | Direction followed from each impacted item |
|---|---|
| `requirement_change`, `design_change`, `clarification` | downstream |
| `defect` | both (the cause may be upstream) |

Result: `Impact(entries, documents)` where each entry is `{node_id, doc_id, depth, link_type, direction}` and `documents` lists every document that holds an impacted item or an affected node, in the fixed order `BRD, SRS, BASIC_DESIGN, TEST_IT, TEST_ST, DETAIL_DESIGN, TEST_UT`. It is stored at approval in `decision-records/DR-####.impact.json` (derived data, committed with the approve commit) and shown by `dr show`.

## 4. Revision patches

A revision does not regenerate a document; it patches it, so untouched items keep their text and their ids (ID Stability Rule).

```python
class PatchOp(FrozenModel):
    op: Literal["update", "add", "remove"]
    item_id: ItemRef | None = None  # required for update and remove
    fields: dict[str, Any] = {}  # update: only the changed fields; add: all fields
    reason: str


class RevisionPatch(FrozenModel):
    operations: list[PatchOp] = []  # empty = nothing in this document needs to change
    summary: str
```

Rules applied by code (`masterba.change.patch`):

- `update` and `remove` name an existing **active** item, at most once per patch. `remove` sets `status: removed`; the item is never deleted and its number is never reused.
- `update` may not change identity fields (`item_id`, `status`, `test_id`, `level`, `requirement_id`); unknown field names are rejected; the updated item must validate against its model.
- `add` creates an item with the next free item number (`max + 1`, removed items count). Per document type the code assigns what the model must not: for a BRD item a new `REQ-####` (next number) with a `RequirementItem` (category from `fields["category"]`, default `functional`, text = the description) and `source_ref` defaulting to the DR id; for a test case the next `TC-<LEVEL>-####`; for other types nothing further.
- After the patch every reference the content makes (`requirement_id`/`derives_from`, `realizes`, `refines`, `verifies`) must name an **active** node that exists in the project; otherwise the patch is rejected.

`apply_patch` is a pure function returning the new content (never mutating) plus the requirements to create or update. Applying and validating the patch is the deterministic gate of section 5.

### 4.1 Trace links of a revised document

`links_for_document(doc_type, content)` derives the links a document implies, with the same rules the stage pipelines use (BRD: `REQ -> item realizes`; SRS: each cited `REQ -> item realizes`; Basic and Detail Design: each `realizes`/`refines` ref `-> item realizes`; test documents: each `verifies` target `-> TC tests`). After a revision the missing links are added; **no link is ever deleted** (links to a removed item stay as history).

## 5. Propagation (`masterba.change.propagate`)

For each document of `affected_documents` in V order, one **team run** (writer = `document-reviser`, reviewer = the stage-neutral QA with the checklist of the document type) exactly as in spec 04:

```
inputs to the reviser: the DR (description, decision, rationale), the items of this document in impact
  (focus), the active items of the document, and the summary of the changes already made to upstream
  documents in this propagation
loop: reviser returns a RevisionPatch -> gate (apply_patch + validation) -> QA review of the patch
      (blocking issues go back as feedback) -> up to team_max_rounds / team_token_budget
on done: empty patch   -> no new version; recorded as "unchanged"
         non-empty     -> add_document(version + 1, status draft, same template) [id stability enforced],
                          create/update requirements (BRD), add missing links, render the new version
```

- The run is recorded like every team run (`RUN-####`, `trigger` = the DR id, `stage` = the document type); the QA checklist per type: BRD `brd`, SRS `srs`, Basic Design `basic_design`, IT and ST `tests`, Detail Design `detail_design`, UT `unit_tests`.
- Progress is stored in `decision-records/DR-####.propagation.json` (`{doc_id: {"outcome": "revised" | "unchanged", "version": n | null, "run_id": ...}}`), committed after each document as `dr(P): propagate DR-#### <DOC_ID>`. `dr propagate` skips documents already recorded, so after an escalation the command can simply be run again (the escalated document is retried, as a new run).
- If a document's team escalates, propagation stops there; the DR stays `approved`; the exit code is 3 and the reasons are printed. Documents already revised keep their new versions (each is a complete, QA-passed change).
- When every affected document is recorded, the DR becomes `propagated` (`dr(P): propagate DR-####`).
- Model options: `--model` (reviser), `--qa-model` (reviewer).

The new document versions are what the dashboard and `dr diff` compare with the previous ones.

## 6. Showing the difference (`dr diff`, `dr show`)

`dr diff DR` prints, for every revised document, the table `item id | field | old | new | classification` from `diff_documents` (spec 01 section 5: structural diff by stable id, `reworded_only` versus `structural_change`), with added and removed items. `--structural-only` hides `reworded_only` rows (concept-design 13.3). `dr show` prints the DR, its stored impact and the propagation progress. Both are read-only and return JSON with `--json`.

## 7. Layout

```
agents/document-reviser.md   skills/document-revision/SKILL.md
src/masterba/change/
  __init__.py  lifecycle.py  impact.py  patch.py  links.py  reviser.py  propagate.py  diffview.py
src/masterba/trace_store/store.py   (save_decision_record, list_decision_records, update_requirement)
src/masterba/team/workspace.py      (Team gets a `trigger`, default "initial")
src/masterba/cli.py                 (dr subcommands)
schemas/RevisionPatch.schema.json
tests/change/  tests/test_cli_dr.py
```

## 8. Acceptance Criteria

- [x] The lifecycle works as in section 1 with the exact commit messages; invalid transitions are rejected; approving or rejecting without approver or decision fails; DR ids are sequential and never reused; every `--item` must exist.
- [x] `dr from-run` on an escalated run creates a `clarification` DR with the escalation text and the item refs found; on a `done` run it is refused.
- [x] Impact analysis from a `REQ-####` on the demo chain lists the BRD, SRS, Basic Design, IT, ST, Detail Design and UT items downstream, documents in V order; a `defect` DR also follows upstream; the result is stored at approval and is identical when recomputed.
- [x] `apply_patch` keeps every untouched item byte-identical, never reuses a removed item's number, assigns the next `REQ-####` and `TC-` ids, rejects unknown fields, identity-field changes, double operations, inactive targets and dangling references.
- [x] `links_for_document` reproduces the links the Phase 3 to 6 pipelines wrote for each document type (test on the demo chain), and a revision adds only the missing ones.
- [x] End to end on the demo project (fake models): a `requirement_change` DR on one requirement is approved, propagated through every affected document, each gets a new version `v2` with unchanged items identical, the old version files are untouched in git, the xlsx of `v2` is rendered, requirements and links are updated, the DR is `propagated`, `dr diff` shows the changed rows with the right classification, then `dr close`.
- [x] An empty patch creates no new version and is recorded as `unchanged`; a document not in the impact is never touched.
- [x] A document whose team escalates stops the propagation (exit code 3), leaves the DR `approved`, and a second `dr propagate` skips the finished documents and retries the rest.
- [x] `dr propagate` on a `proposed` or `closed` DR is refused and writes nothing.
- [x] The QA reviewer code is unchanged (no stage branch); a unit test shows the checklist chosen per document type.
- [x] A live attempt (CLI with a key) is made on a demo project that has at least a BRD and SRS and is recorded in section 9.
- [x] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass; `RevisionPatch` schema generated and drift-tested.

## 9. Manual review record

**2026-10-31, local Anthropic-compatible gateway, project language `en`, demo project with BRD and SRS (6 requirements), reviser `auto/best-coding`, QA `auto/best-reasoning`.**

DR-0001, `requirement_change`, item `REQ-0006` ("fast" had been left as an open question): "95% of sign-ins complete within 2 seconds". `dr new` computed `affected_documents = [BRD, SRS]`; `dr approve` stored the impact; `dr propagate` revised both documents in one attempt each (RUN-0009, RUN-0010), final status `propagated`.

`dr diff` shows the smallest possible change: BRD item 6 `description` (the open-ended sentence became the 2-second target) and SRS item 5 `statement` plus a new `acceptance_hint`, all other items untouched; both rows classified `structural_change`. This is the first end-to-end proof that a customer decision flows through the traced documents with stable ids and QA review. The Basic Design stage was not part of this project (it did not reach `done`, spec 05 section 9), so the longer chain is covered by the offline tests only.

## 10. Open points (do not block implementation)

1. **Who may approve.** Enforced by the dashboard roles in Phase 8; the CLI trusts the name given. The DR file keeps it for audit.
2. **Large documents.** The reviser receives the whole active document; very large documents may need chunking by kind later.
3. **Requirement text mirror.** `RequirementItem.text` mirrors the BRD description by convention (Phase 3); revising a BRD item updates it. If the two ever need to differ, `update_requirement` is the single place to change.
4. **Cross-document consistency after partial propagation.** After an escalation some documents are on the new version and others not; `dr show` reports the progress, and the DR stays `approved` until finished.

## 11. Decisions taken while implementing

1. **Work-in-progress files per DR.** `DR-####.impact.json` (written with the approve commit) and `DR-####.propagation.json` (one commit per finished document) sit next to the DR; both are derived data. `get_dr_extra` / `write_dr_extra` read and write them.
2. **Empty patches skip QA.** A patch with no operations passes the gate and the review step returns an empty report without calling the model, so an unaffected document costs one reviser call and no QA call.
3. **New versions are `draft`.** A revised document starts again as `draft` regardless of the status of the version it replaces, so a later approval step (Phase 8) can act on it.
4. **`Team` has a `trigger`.** `Team.open(..., trigger="DR-0001")` records the DR id in `TeamRun.trigger` (the field already allowed `DR-####`).
5. **Test chain fixture.** The offline tests build the full demo chain once per test session and copy it per test (`tests/conftest.py`: `chain_source`, `chain`), which keeps the suite at a few minutes.
6. **`from-run` filters refs.** Item refs that exist only in a discarded draft (typical for an escalation before anything was stored) are dropped from `impacted_items`; the escalation text stays in the description.
