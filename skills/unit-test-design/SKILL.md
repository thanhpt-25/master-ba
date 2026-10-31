---
name: unit-test-design
description: Rules for writing UT cases that map back to detail design items (the V-model), with exclusions and questions. Used by the unit-test-design agent.
---

# unit-test-design

Used by `agents/unit-test-design.md`.

## The mapping

| Level | Checks | Written from | Stored as |
|---|---|---|---|
| UT (単体テスト) | Detail Design items | the detail draft | `DOC-TEST_UT-0001`, ids `TC-UT-####` |

Trace link (upstream to downstream): `detail item -> TC-UT`, type `tests`. Together with
`design item -> detail item` (`realizes`), a requirement reaches its unit tests through the whole
chain.

## Rules and where they are enforced

| Rule | Enforcement |
|---|---|
| UT cases cite detail items of the current draft | `validate_unit_test_draft` |
| Every detail item has a UT case or an exclusion; never both | `validate_unit_test_draft` |
| Steps are real | `DraftTestCase` rejects blank steps; `expected` must be non-empty |
| Nothing is guessed | The tester raises a `question` about a detail item instead; QA does not run while a fresh question is open; a repeated question about an answered item is reported as a customer question |
| The model never chooses ids | `pipeline.detail.assign_detail_ids` assigns `TC-UT-####` and item refs in draft order |
| Boundary and error cases | QA checklist `skills/qa-review/checklists/unit_tests.toml` |

Exclusions are stored in `TestSpecContent.exclusions` of the UT document.
