# Spec 06 — Detail Design and unit tests (UT)

Status: v0.2 (2026-10-31), implemented; all Acceptance Criteria pass except the live attempt (section 9). Sources: [concept-design.md](../docs/concept-design.md) sections 2, 8, 14 (Vietnamese), [roadmap-phases.md](../docs/roadmap-phases.md) Phase 6, [05-basic-design-and-tests.md](05-basic-design-and-tests.md) (this spec repeats its pattern and refers to it for everything not restated), [04-srs-qa-and-team-runtime.md](04-srs-qa-and-team-runtime.md).

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

Add the fourth and last document stage of the V-model: from the stored Basic Design, produce the Detail Design (詳細設計書) and its unit-test specification (単体テスト仕様書, UT), written by the same kind of three-member team as Phase 5 (designer, tester, QA) with the same designer-tester question exchange. After this phase the system can generate the full set of deliverables from a customer intake: BRD, SRS, Basic Design with IT and ST tests, Detail Design with UT tests (the original requirement items 1 to 3).

## Non-goals

- No UAT (the right-hand side of the BRD) and no dev or code generation (Phase 10 backlog).
- No change to existing documents or re-running a stage on an existing document (Phase 7).
- No new team machinery: the Phase 5 loop (`run_design_test_team`) is reused unchanged. Only the agents, gates, checklists and the pipeline are new.
- No rendering of exclusions in Excel (spec 05 open point 1 still applies).

## 1. V-model mapping and trace rules

| Document | Id | Realises / tests | Created from |
|---|---|---|---|
| Detail Design | `DOC-DETAIL_DESIGN-0001` | each item `refines` one or more **Basic Design items** | stored Basic Design |
| UT specification | `DOC-TEST_UT-0001` | each case checks one or more **Detail Design items** | the detail draft |

Trace links written when the team is `done` (upstream to downstream):

- `design item -> detail item`, type `realizes`, one per entry of `refines` (the stored field keeps the name `refines`; the link type for "is worked out into" stays `realizes` as in Phase 5);
- `detail item -> TC-UT-####`, type `tests`, one per entry of a UT case's `verifies`.

So `rtm(REQ-####)` now reaches IT, ST and UT cases.

**Coverage rule (code):** every active Basic Design item is refined by at least one detail item; every active detail item has at least one UT case or an exclusion with a reason; an item may not be both tested and excluded.

## 2. Roles, artifacts and drafts

Same roles and single-writer rule as Phase 5: `designer` (`detail-design-agent`, owns `design-draft`), `tester` (`unit-test-design-agent`, owns `test-draft`), `qa` (the stage-neutral reviewer, owns `qa-report`). Models per role: `--model`, `--test-model`, `--qa-model` as in spec 05.

Draft models (not stored; the model never writes ids; items are numbered by position, `DOC-DETAIL_DESIGN-0001#item.n`, and UT cases get `TC-UT-####` in draft order):

```python
class DraftDetailItem(FrozenModel):
    kind: DetailDesignKind  # module | processing_step | db_table | api
    name: str
    spec: str
    refines: list[ItemRef]  # at least one Basic Design item ref (DOC-BASIC_DESIGN-0001#item.n)


class DetailDesignDraft(FrozenModel):
    items: list[DraftDetailItem]  # at least one
    answers: list[DesignAnswer] = []  # reused from spec 05


class UnitTestDraft(FrozenModel):
    ut_cases: list[
        DraftTestCase
    ] = []  # reused: precondition, input, steps, expected, verifies (detail item refs)
    exclusions: list[DraftExclusion] = []  # reused: item_ref is a detail item
    questions: list[DesignQuestion] = []  # reused: ref is a detail item
```

`DesignAnswer`, `DraftTestCase`, `DraftExclusion` and `DesignQuestion` keep their definitions from spec 05 (the question and answer refs now name detail items). `DetailDesignItem.spec` is free text; the guidance below fixes what it must contain per kind.

### 2.1 Content guidance per kind (prompt rules, checked by QA, not by code)

| Kind | `spec` must state |
|---|---|
| `module` | responsibility, public operations with inputs, outputs and errors, collaborators, the invariants it keeps |
| `processing_step` | the processing of one function as numbered steps in order: input, validation, duplicate check, registration or update, notification, output, error handling (concept-design section 8); every branch and error exit named |
| `db_table` | table purpose, columns with type, length, nullability, keys, indexes and constraints, retention |
| `api` | operation or endpoint, request and response fields with types and limits, status or error codes, idempotency, authentication |

A figure the Basic Design does not give is marked open, never invented; this follows spec 05.

## 3. The team loop

Exactly spec 05 section 3 (`run_design_test_team`): cycle = round, designer and tester work on what is pending, the two deterministic gates run, then QA reviews the detail design and the unit tests; at most 2 designer-tester exchanges per cycle; tester questions about an item the designer already answered stop blocking and are reported as customer questions (mailbox message to `customer`, `StageResult.open_questions`); limits, escalation and the run record are unchanged. The loop is generic over its draft types, so no loop code changes.

## 4. Gates (deterministic)

Detail gate (`validate_detail_draft`):

1. Every `refines` ref is an active Basic Design item of the stored Basic Design.
2. **Coverage:** every active Basic Design item is refined by at least one detail item.
3. No two items of the same kind have the same normalised name.
4. Specs and answers in the project's language (the loose script check); `answers[].ref` are items of the draft.

Unit-test gate (`validate_unit_test_draft`):

1. Every `verifies` ref is a detail item of the current draft; every case has non-empty steps (none blank) and a non-empty `expected`.
2. **Coverage:** every detail item has at least one UT case or an exclusion; an item is not both tested and excluded; exclusion refs are detail items with non-empty reasons.
3. Question refs are detail items; language check on case text and reasons.

## 5. QA for this stage

The reviewer code is unchanged. Two checklists are added:

- `skills/qa-review/checklists/detail_design.toml` (upstream: the Basic Design): every Basic Design item is refined and nothing is invented; each item satisfies the content guidance of its kind; no contradiction between modules, steps, tables and interfaces; names and terminology consistent; no code (language syntax, library calls) at this level; vague wording is advisory.
- `skills/qa-review/checklists/unit_tests.toml` (upstream: the Basic Design and the detail draft): each case has a concrete precondition, input, steps and an observable expected result; boundary cases at every stated limit and error cases for every named error exit; each case checks only the detail items it names; nothing assumed that the detail design does not state; exclusions are justified; duplication is advisory.

Following the Phase 5 live finding, the subjective level-distinction check is advisory from the start; blocking checks are limited to ones a reader can verify against the text.

## 6. Pipeline and CLI

`masterba.pipeline.detail.run_detail_design(store, templates_root, designer_llm, *, tester_llm=None, qa_llm=None)`:

```
precondition: Basic Design exists; no Detail Design / UT document exists (else error, nothing written)
team loop (spec 05 section 3) with the detail agents, gates and checklists above
on done: assign ids in memory, then write
   DOC-DETAIL_DESIGN-0001 v1 and DOC-TEST_UT-0001 v1
   links (design -> detail realizes, detail -> TC-UT tests)
   render both documents
   commit the run record
```

Commit order: two `doc` commits, the `trace` commits (all `realizes`, then `tests`), two `render` commits, then `run(...) done`. On escalation only the run record is committed.

```
masterba run detail --project PRJ-001 [--model M] [--test-model M] [--qa-model M]
```

Shared code: the helpers that Phase 5 kept private in `pipeline/basic.py` (document construction, existence check, link de-duplication) move to `pipeline/stage.py` and are used by both pipelines; behaviour of the Basic Design stage does not change.

## 7. Layout

```
agents/detail-design.md  agents/unit-test-design.md
skills/detail-design-from-basic/SKILL.md  skills/unit-test-design/SKILL.md
skills/qa-review/checklists/{detail_design,unit_tests}.toml
src/masterba/
  agents/   detail_writer.py  unit_test_writer.py
  pipeline/ detail.py   (stage.py gains the shared helpers)
schemas/DetailDesignDraft.schema.json  schemas/UnitTestDraft.schema.json
tests/ ...
```

## 8. Acceptance Criteria

- [x] `brd -> srs -> basic -> detail` runs end `done` on the demo project (fake models): the two new documents, links, two workbooks that open with `openpyxl`, one committed run record, commit order as in section 6.
- [x] `rtm(REQ-####)` returns paths that end at an IT case, an ST case and a UT case; `query_impact(upstream)` from a `TC-UT-####` reaches the requirement through the detail item, the design item and the SRS item.
- [x] Every Basic Design item is refined and every detail item has a UT case or an exclusion (gate failures otherwise); an item both tested and excluded is rejected; exclusions are stored in `DOC-TEST_UT-0001`.
- [x] A tester question reaches the designer (mailbox `question`), the answer appears in the revised spec and as an `answer` message, the tests are revised in the same cycle; a repeated question about an answered item stops blocking and is reported in `open_questions`.
- [x] QA issues are routed by document: detail refs to the designer, UT refs to the tester.
- [x] Exceeding `team_max_rounds` or the token budget ends `escalated` (exit code 3) with no business artifact written.
- [x] The stage refuses to start without a Basic Design and refuses a second run.
- [x] The Basic Design pipeline tests still pass unchanged after the helpers move to `stage.py`.
- [ ] A live attempt (`pytest -m live` or the CLI with a key) is made and recorded in section 9; it needs a stored Basic Design, so it is blocked if the Basic Design stage cannot reach `done` on the available models.
- [x] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass; the new draft schemas are generated and drift-tested.

## 9. Manual review record

Not run: the live attempt needs a stored Basic Design, and the Basic Design stage did not reach `done` on the available free gateway models (spec 05 section 9), so the demo project has none. To run it, finish the Basic Design stage with stronger models, then `masterba run detail --project PRJ-001 --qa-model <strong model>`; record the result here.

## 10. Open points (do not block implementation)

1. **Resuming.** Phase 5's live runs show that a run can end `escalated` with a nearly complete draft. Resuming from the last draft (kept only in `transcripts/`) would save most of the cost; it needs the draft to be persisted in a committed form and is better designed together with the Decision Record flow (Phase 7).
2. **Reliability of QA signals** (spec 05 open point 5) applies here unchanged.
3. **Whole-chain run.** A `masterba run all` that chains the four stages and stops at the first escalation is a convenience for later; the stages stay separate commands so each can be reviewed.
4. **Code-level detail** (class and method signatures in a language) is deliberately excluded; it belongs to the dev extension (Phase 10).

## 11. Decisions taken while implementing

1. **No loop changes.** `run_design_test_team` served the detail stage as is; the question rule from spec 05 section 11 (a repeated question about an answered item is reported, not blocking) applies unchanged.
2. **Shared helpers** `make_document`, `unique_links`, `document_exists` and `TEMPLATE_ID` now live in `pipeline/stage.py`; the Basic Design pipeline uses them with no behaviour change.
3. **Naming.** `UnitTestDraft` holds `ut_cases`, `exclusions` and `questions`; its question type is spec 05's `DesignQuestion`, whose ref now names a detail item. Gate and view functions are `validate_detail_draft`, `validate_unit_test_draft`, `detail_view` and `unit_cases_view`.
4. **Link counts in the demo.** One detail item may refine several Basic Design items, so a detail item can have several `realizes` links; links are de-duplicated.
