---
name: detail-design-from-basic
description: Rules for turning Basic Design items into a Detail Design draft with full coverage and answers to tester questions. Used by the detail-design agent.
---

# detail-design-from-basic

Used by `agents/detail-design.md`. The prompt carries the rules the model sees; this file records
how the pipeline enforces them.

## Contract

Input: the active items of the stored Basic Design. Output: a `DetailDesignDraft`
(`src/masterba/agents/detail_writer.py`, schema `schemas/DetailDesignDraft.schema.json`) returned
through the `submit_detail_design` tool call.

## Rules and where they are enforced

| Rule | Enforcement |
|---|---|
| Only active Basic Design items are cited | `validate_detail_draft`: every `refines` ref must be an active Basic Design item |
| Every Basic Design item is refined | `validate_detail_draft`: coverage check; failure goes back to the designer, no review is paid for |
| No duplicate names within a kind | `validate_detail_draft` |
| The model never chooses ids | Items are numbered by position; `pipeline.detail.assign_detail_ids` assigns `DOC-DETAIL_DESIGN-0001#item.n` |
| Tester questions are answered | The answer goes into the item's spec and into `answers`; answers become `answer` messages in the mailbox |
| Content per kind, no invented limits | QA checklist `skills/qa-review/checklists/detail_design.toml` |
| Output language | Prompt gets an `Output language` section; the gate loosely checks the script |
