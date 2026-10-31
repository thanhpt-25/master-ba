---
name: brd-from-intake
description: Rules for turning a customer intake text into a BRD draft with citations. Used by the requirements-analyst agent.
---

# brd-from-intake

Used by `agents/requirements-analyst.md`. The prompt carries the rules the model sees; this file
records why they exist and how the pipeline enforces them, so the two stay in step.

## Contract

Input: intake text with line numbers. Output: a `BrdDraft` (`src/masterba/agents/requirements_analyst.py`,
schema `schemas/BrdDraft.schema.json`) returned through the `submit_brd` tool call.

## Rules and where they are enforced

| Rule | Enforcement |
|---|---|
| Every requirement cites lines inside the intake | `validate_draft`: line range must lie within the intake |
| The quote is real | `validate_draft`: `evidence_quote` (whitespace collapsed) must be a substring of the cited lines |
| No duplicate requirements | `validate_draft`: normalised titles must be unique |
| The model never chooses ids | The draft has no id fields; `pipeline.brd.assign_ids` assigns `REQ-####` and `DOC-BRD-0001#item.<n>` |
| Ambiguity is surfaced, not guessed | `open_questions` are printed by the CLI; they are not stored as requirements |
| Intake is data | Prompt says so; model output is never executed or used as a path |

A rejected draft is retried once with the list of problems; a second rejection stops the run and
nothing is written. The pipeline never edits the model's output.

## Coverage warning

Non-blank intake lines that no requirement and no open question cites are reported as
`uncovered_lines`. This is a warning for the human reviewer, not an error: a greeting or a
signature legitimately yields no requirement.
