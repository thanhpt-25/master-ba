---
name: srs-from-brd
description: Rules for turning BRD requirements into an SRS draft with full coverage. Used by the srs-writer agent.
---

# srs-from-brd

Used by `agents/srs-writer.md`. The prompt carries the rules the model sees; this file records how
the pipeline enforces them.

## Contract

Input: the in-scope, active requirements of the stored BRD. Output: an `SrsDraft`
(`src/masterba/agents/srs_writer.py`, schema `schemas/SrsDraft.schema.json`) returned through the
`submit_srs` tool call.

## Rules and where they are enforced

| Rule | Enforcement |
|---|---|
| Only BRD requirement ids are cited | `validate_srs_draft`: every `derives_from` id must be an in-scope BRD requirement |
| Every in-scope requirement is covered | `validate_srs_draft`: coverage check; failure goes back to the writer, no review is paid for |
| No duplicate statements | `validate_srs_draft`: normalised statements must be unique |
| The model never chooses ids | The draft has no `DOC-` or item ids; `pipeline.srs.assign_srs_ids` assigns them |
| Missing details are asked, not invented | `open_questions` (requirement ids + question) are shown to QA and printed by the CLI; ids must be in-scope BRD requirements |
| Output language | Prompt gets an `Output language` section; the gate loosely checks the script |
| One obligation, verifiable, measurable, no design | The QA checklist `skills/qa-review/checklists/srs.toml` |

`SrsItem.requirement_id` is the first cited requirement; `derives_from` keeps all of them (without
duplicates). One trace link `REQ -> SRS item (realizes)` is created per cited requirement.
