---
name: test-design-v-mapping
description: Rules for writing IT and ST test cases that map back to design items and SRS items (the V-model), with exclusions and questions. Used by the basic-test-design agent.
---

# test-design-v-mapping

Used by `agents/basic-test-design.md`. It records the V-model mapping and how the pipeline checks it.

## The mapping

| Level | Checks | Written from | Stored as |
|---|---|---|---|
| IT (結合テスト) | Basic Design items | the design draft | `DOC-TEST_IT-0001`, ids `TC-IT-####` |
| ST (システムテスト) | SRS items | the SRS | `DOC-TEST_ST-0001`, ids `TC-ST-####` |

Trace links (upstream to downstream): `design item -> TC-IT` and `SRS item -> TC-ST`, both of type
`tests`. Requirement to test case paths therefore exist on both routes.

## Rules and where they are enforced

| Rule | Enforcement |
|---|---|
| IT cases cite design items, ST cases cite active SRS items | `validate_test_draft` |
| Every design item has an IT case or an exclusion; every SRS item an ST case or an exclusion | `validate_test_draft`; an item cannot be both tested and excluded |
| Steps are real | `DraftTestCase` rejects blank steps; `expected` must be non-empty |
| Nothing is guessed | The tester raises a `question` about a design item instead; questions are posted to the designer (mailbox `question`) and QA does not run while they are open |
| The model never chooses ids | `pipeline.basic.assign_basic_ids` assigns `TC-` ids and item refs in draft order |
| Good cases (boundary, error, observable result) | QA checklist `skills/qa-review/checklists/tests.toml` |

Exclusions are stored in `TestSpecContent.exclusions` (IT document: design items; ST document: SRS
items).
