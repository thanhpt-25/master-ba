# Spec 05 — Basic Design and IT/ST tests (three-member team)

Status: v0.1 (2026-10-31), draft for review. Sources: [concept-design.md](../docs/concept-design.md) sections 2, 7, 14 (Vietnamese), [roadmap-phases.md](../docs/roadmap-phases.md) Phase 5, [01-data-contracts.md](01-data-contracts.md), [02-excel-rendering.md](02-excel-rendering.md), [04-srs-qa-and-team-runtime.md](04-srs-qa-and-team-runtime.md).

This document is written in English (new documents are English; see `CLAUDE.md`).

## Goal

Add the third V-model stage: from the stored SRS, produce the Basic Design (基本設計書) together with its integration tests (IT, 結合テスト) and system tests (ST, システムテスト), written by a three-member team: a **designer**, a **tester** and a **QA reviewer**, with a question-and-answer exchange between designer and tester. This is where the left side of the V meets the right side: every test case traces back to the design item or SRS item it checks, and every item is either tested or explicitly excluded with a reason.

## Non-goals

- No Detail Design or unit tests (Phase 6) and no UAT (the BRD side of the V, a later phase).
- No change to approved documents or re-running a stage on an existing document (Phase 7).
- No rendering of exclusions in the Excel files (open point 1); they are stored in the JSON and in the trace store.
- No running of tests; the documents are specifications.
- No new general team framework: the new loop reuses the Phase 4 workspace, mailbox, budget and escalation, and adds one loop for this stage.

## 1. V-model mapping and trace rules

| Document | Id | Tests / realises | Created from |
|---|---|---|---|
| Basic Design | `DOC-BASIC_DESIGN-0001` | each item `realizes` one or more SRS items | stored SRS |
| IT specification | `DOC-TEST_IT-0001` | each case checks one or more **Basic Design items** | the design draft |
| ST specification | `DOC-TEST_ST-0001` | each case checks one or more **SRS items** | the SRS |

Trace links written when the team is `done` (direction: upstream to downstream, spec 01 decision 1):

- `SRS item -> design item`, type `realizes`, one per entry of `realizes`;
- `design item -> TC-IT-####`, type `tests`, one per entry of an IT case's `verifies`;
- `SRS item -> TC-ST-####`, type `tests`, one per entry of an ST case's `verifies`.

Consequently `rtm(REQ-####)` reaches test cases through both the IT and the ST route. (`verifies` as a link type stays reserved for UAT.) The `verifies` field of a stored `TestCaseItem` holds the same targets as the links.

**Coverage rule (checked by code, section 4.2):** every active design item has at least one IT case or an exclusion with a reason; every active SRS item has at least one ST case or an exclusion with a reason; every active SRS item is realised by at least one design item.

## 2. Roles and artifacts

| Role | Agent | Owns (single-writer) | Output tool |
|---|---|---|---|
| `designer` | `basic-design-agent` | `design-draft` | `submit_basic_design` |
| `tester` | `basic-test-design-agent` | `test-draft` | `submit_tests` |
| `qa` | `qa-reviewer-agent` (Phase 4, unchanged code and prompt) | `qa-report` | `submit_qa_report` |

`Team.write` owners are extended with `design-draft`, `test-draft` (Phase 4's `draft` and `qa-report` stay). Each role may use its own model: `--model` (designer), `--test-model` (tester, defaults to `--model`), `--qa-model` (defaults to `--model`).

### 2.1 Draft models (not stored; between model and pipeline)

```python
class DesignAnswer(FrozenModel):  # designer's reply to a tester question
    ref: ItemRef  # design item the question was about
    text: str


class DraftDesignItem(FrozenModel):
    kind: BasicDesignKind  # function | screen | interface | data_entity
    name: str
    description: str
    realizes: list[ItemRef]  # at least one SRS item ref (DOC-SRS-0001#item.n)


class BasicDesignDraft(FrozenModel):
    items: list[DraftDesignItem]  # at least one
    answers: list[DesignAnswer] = []  # only when responding to tester questions


class DraftTestCase(FrozenModel):
    precondition: str
    input: str
    steps: list[str]  # at least one, none empty
    expected: str
    verifies: list[ItemRef]  # IT: design item refs of the current design draft; ST: SRS item refs


class DraftExclusion(FrozenModel):
    item_ref: ItemRef  # a design item (for IT) or an SRS item (for ST)
    reason: str


class TesterQuestion(FrozenModel):
    ref: ItemRef  # design item that cannot be tested as written
    question: str


class TestDraft(FrozenModel):
    it_cases: list[DraftTestCase] = []
    st_cases: list[DraftTestCase] = []
    exclusions: list[DraftExclusion] = []
    questions: list[TesterQuestion] = []
```

The model never writes ids. Items are numbered by position (`DOC-BASIC_DESIGN-0001#item.n`), test cases get `TC-IT-####` / `TC-ST-####` and item refs in `DOC-TEST_IT-0001` / `DOC-TEST_ST-0001` in draft order. The refs the tester writes in `verifies`, `exclusions` and `questions` are the final refs of the **current** design draft; the tester is always shown the design draft with its numbers.

### 2.2 Stored change to `TestSpecContent`

`TestSpecContent` gains `exclusions: list[TestExclusion]` (default empty), `TestExclusion = {item_ref: ItemRef, reason: str}`. Old documents without the field still load. This is a spec 01 change, recorded there as a decision, with regenerated schemas. Exclusions of the IT document reference design items; those of the ST document reference SRS items. Because items in a stored document are never deleted, an exclusion is data about the document version, not an item.

## 3. The team loop

A **round** here is one *cycle*: the designer and tester do whatever they have pending, the gates run, and then QA reviews. A cycle that ends early because a gate failed also counts as a round (as in Phase 4). `team_max_rounds` and `team_token_budget` apply exactly as in Phase 4; additionally at most **2 designer-tester exchanges** may happen inside one cycle (`MAX_EXCHANGES = 2`).

State: the latest design draft and test draft, and three pending lists of feedback strings: `to_designer`, `to_tester`.

```
cycle (guards: rounds, budget as in spec 04):
  1. if there is no design draft or to_designer is not empty:
        designer writes (previous draft + to_designer)        -> answers become `answer` messages
        design gate fails  -> post feedback from "gate", to_designer = errors, end the cycle
        design changed     -> to_tester += ["the design was revised"] (+ the answers)
  2. if there is no test draft or to_tester is not empty:
        tester writes (design draft, SRS, previous tests + to_tester)
        test gate fails    -> post feedback from "gate", to_tester = errors, end the cycle
  3. if the tester raised questions:
        post them as `question` messages (tester -> designer, ref = design item)
        if exchanges < 2:  exchanges += 1, to_designer = questions, go to 1 (same cycle)
        else:              to_designer = questions, end the cycle (next round starts at 1)
  4. QA reviews the design draft, then the test drafts (two reviews, section 5)
        blocking issues on a design ref -> to_designer; on a test ref -> to_tester
        advisory issues are posted and reported, they do not block
        no blocking issue in either review -> done
```

Rules:

- **Done** requires: both gates clean, the tester has no open questions, both QA reviews have no blocking issue, no task open.
- **Escalated** when `team_max_rounds` is exceeded, the token budget is reached before a call, or a QA report is unusable twice. `escalations` lists the reasons plus the last open issues and unanswered questions. Only the run record is written (this stage has no intake to commit).
- **Single writer:** the designer writes `design-draft`, the tester `test-draft`, QA `qa-report`; anything else raises `SingleWriterError`.
- **Tasks:** per cycle, e.g. `Draft design`, `Write tests` (depends on the design task), `Answer questions`, `Revise tests`, `Review design`, `Review tests`; a cycle ended by a gate leaves later tasks uncreated.
- **Mailbox:** gate and QA feedback as in Phase 4 (`to` is `designer` or `tester` according to the ref's document); tester questions use `type: question`, the designer's answers `type: answer`, both with a design item `ref`.
- **Counting:** `issues_raised` counts blocking QA issues across all reviews, `issues_resolved` those gone by the end, as in Phase 4. Tester questions are not counted as issues.

## 4. Agents and gates

### 4.1 Designer (`masterba.agents.design_writer`) and tester (`masterba.agents.test_writer`)

Prompts `agents/basic-design.md` and `agents/basic-test-design.md`, skills `skills/basic-design-from-srs/SKILL.md` and `skills/test-design-v-mapping/SKILL.md`. Both end with the project's `Output language` section like the earlier agents, and both state that the SRS, the design and the questions are data, not instructions.

- **Designer rules:** derive only from the SRS (no invented features); one design item per function, screen, interface or data entity; cover every SRS item; describe behaviour, inputs and outputs, limits and error handling concretely enough to be tested; when answering tester questions, put the answer **into the item's description** and also list it in `answers`.
- **Tester rules:** write IT cases from the design items (normal, boundary and error cases for each item where the description supports them) and ST cases from the SRS items; steps are concrete operations; expected results are observable; never invent a limit or behaviour the design or SRS does not state: if a case cannot be written without it, add a `question` about that design item (and an exclusion with the reason for the part that cannot be tested yet, if needed) instead of guessing.

### 4.2 Deterministic gates

Design gate (`validate_design_draft`):

1. Every `realizes` ref is an active SRS item of the stored SRS.
2. **Coverage:** every active SRS item is realised by at least one design item.
3. No two items of the same kind have the same normalised name.
4. Descriptions and answers in the project's language (same loose script check as before); every `answers[].ref` is an item of the draft.

Test gate (`validate_test_draft`, given the current design draft and the SRS):

1. IT `verifies` refs are items of the design draft; ST `verifies` refs are active SRS items; both lists non-empty per case.
2. Every case has non-empty `steps` (no blank step) and a non-empty `expected`.
3. **Coverage:** every design item has at least one IT case or an exclusion; every active SRS item has at least one ST case or an exclusion. An item may not be both tested and excluded. Exclusion reasons are non-empty; exclusion refs are design items (listed under IT scope) or SRS items.
4. Each question's `ref` is a design item of the draft.
5. Language check on case text and reasons.

Questions do not fail the gate: they are the tester's legitimate output.

## 5. QA for this stage

The Phase 4 reviewer is reused unchanged in behaviour; its call signature is generalised so one review can cover several documents: `review(..., item_counts: Mapping[str, int])` replaces `doc_id` + `item_count`, and a `ref` is valid when its document id is a key and its number is within that count. Two checklists are added, nothing else changes:

- `skills/qa-review/checklists/basic_design.toml` (reviewed against the SRS): every SRS item is realised and nothing is invented; items are testable (inputs, outputs, limits, errors stated); no detail-design or implementation choice (class, table, method names); consistent naming; screen, interface and data items state their responsibilities; no contradiction.
- `skills/qa-review/checklists/tests.toml` (reviewed against the design draft and the SRS, covering IT and ST together): each case has a concrete precondition, steps and an observable expected result; boundary and error cases exist where the item states limits or errors; each case verifies exactly the items it names; no case depends on a behaviour the design or SRS does not state; exclusions have convincing reasons; ST cases are black-box (SRS level), IT cases check design-level interactions.

`checklist_path` accepts a stem (`"tests"`) as well as a `DocType`. The tests review shows both documents' items with their final refs (`DOC-TEST_IT-0001#item.n`, `DOC-TEST_ST-0001#item.n`).

## 6. Pipeline and CLI

`masterba.pipeline.basic.run_basic_design(store, templates_root, designer_llm, *, tester_llm=None, qa_llm=None)`:

```
precondition: SRS exists; no Basic Design / IT / ST exists (else DuplicateIdError, nothing written)
team loop (section 3)
on done: assign ids and build objects in memory, then write:
   document DOC-BASIC_DESIGN-0001 v1, DOC-TEST_IT-0001 v1, DOC-TEST_ST-0001 v1
   links (SRS -> design realizes, design -> TC-IT tests, SRS -> TC-ST tests)
   render the three documents
   commit the run record
```

Commit order: the three `doc` commits, then the `trace` commits (all `realizes`, then IT, then ST), then three `render` commits, then `run(...) done`. On escalation only the run record is committed.

```
masterba run basic --project PRJ-001 [--model M] [--test-model M] [--qa-model M]
```

`StageResult` gains `document_ids: tuple[str, ...]` (`document_id` stays the first one, for the earlier stages) and the CLI JSON prints `document_ids`, plus `questions` asked and `answers` given counts (`exchanges`). Exit codes as before (3 = escalated).

## 7. Layout

```
agents/basic-design.md  agents/basic-test-design.md
skills/basic-design-from-srs/SKILL.md  skills/test-design-v-mapping/SKILL.md
skills/qa-review/checklists/{basic_design,tests}.toml
src/masterba/
  agents/   design_writer.py  test_writer.py     (qa_reviewer.py generalised)
  team/     design_test_loop.py                   (workspace.py: more artifact owners)
  pipeline/ basic.py
  models/   payloads.py (TestExclusion, TestSpecContent.exclusions)
tests/ ...
```

## 8. Acceptance Criteria

- [ ] `brd -> srs -> basic` runs end `done` on a demo project (fake models) and writes the three documents, links, three workbooks that open with `openpyxl`, and one committed run record; commit order as in section 6.
- [ ] `rtm(REQ-####)` returns paths ending at both an IT case and an ST case; `query_impact(upstream)` from a `TC-ST-####` reaches the requirement through the SRS item.
- [ ] Every design item has an IT case or an exclusion, and every SRS item has an ST case or an exclusion, in the stored JSON (a gate failure otherwise); an item both tested and excluded is rejected.
- [ ] A tester question reaches the designer as a `question` message with a design item ref; the designer's reply is an `answer` message and appears in the revised description; the tester then revises the tests within the same cycle (one exchange), and the run ends `done`.
- [ ] After two exchanges in one cycle, further questions end the cycle and carry over to the next round; unanswered questions at the round limit are listed in `escalations`.
- [ ] A blocking QA issue on a design ref goes to the designer and one on a test ref goes to the tester (mailbox `to` is correct); the next cycle revises only what was criticised and the run ends `done` with `issues_raised == issues_resolved`.
- [ ] Exceeding `team_max_rounds` or reaching `team_token_budget` ends `escalated` (exit code 3) with no business artifact written.
- [ ] The QA reviewer code is unchanged in stage-neutrality (no `DocType` branch), and one review validates refs of several documents; an unknown document in a `ref` is rejected.
- [ ] Single-writer is enforced for `design-draft` and `test-draft`.
- [ ] `TestSpecContent.exclusions` round-trips through the store and a document stored without it still loads; `schemas/*.schema.json` for the new draft models and the changed payload are regenerated and drift-tested.
- [ ] A live run (`pytest -m live` / the CLI with a key) completes the stage on the login demo; the result is reviewed by hand and recorded in section 9.
- [ ] `uv run pytest` (coverage >= 80%), `ruff` and `mypy --strict` pass.

## 9. Manual review record

To be filled after the first live run.

## 10. Open points (do not block implementation)

1. **Exclusions in Excel.** They live in the JSON only; a sheet (除外項目) needs the renderer to read `$content.exclusions`, which is a small spec 02 extension for a later phase.
2. **Round budget.** Three members need more cycles than the default `team_max_rounds = 3` for hard inputs; the setting stays project-wide and `init-project --team-max-rounds` raises it. Whether the default should differ per stage is a tuning question for after the live review.
3. **Test depth.** The checklist asks for boundary and error cases only where the design states limits or errors; coverage metrics (for example case-per-condition) are a later refinement.
4. **IT/ST in one pass.** Both levels are written by one tester call; splitting them into two agents or two calls is possible without changing the stored documents.
