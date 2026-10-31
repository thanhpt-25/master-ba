---
name: basic-design-from-srs
description: Rules for turning SRS items into a Basic Design draft with full coverage and answers to tester questions. Used by the basic-design agent.
---

# basic-design-from-srs

Used by `agents/basic-design.md`. The prompt carries the rules the model sees; this file records
how the pipeline enforces them.

## Contract

Input: the active items of the stored SRS with their references. Output: a `BasicDesignDraft`
(`src/masterba/agents/design_writer.py`, schema `schemas/BasicDesignDraft.schema.json`) returned
through the `submit_basic_design` tool call.

## Rules and where they are enforced

| Rule | Enforcement |
|---|---|
| Only active SRS items are cited | `validate_design_draft`: every `realizes` ref must be an active SRS item |
| Every SRS item is realised | `validate_design_draft`: coverage check; failure goes back to the designer, no review is paid for |
| No duplicate names within a kind | `validate_design_draft` |
| The model never chooses ids | Items are numbered by position; `pipeline.basic.assign_basic_ids` assigns `DOC-BASIC_DESIGN-0001#item.n` |
| Tester questions are answered | The designer puts the answer into the item description and lists it in `answers`; answers become `answer` messages in the mailbox |
| Testable, no implementation detail | QA checklist `skills/qa-review/checklists/basic_design.toml` |
| Output language | Prompt gets an `Output language` section; the gate loosely checks the script |
