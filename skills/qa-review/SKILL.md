---
name: qa-review
description: Checklist-driven review of a draft stage artifact. Used by the stage-neutral qa-reviewer agent for BRD, SRS and later stages.
---

# qa-review

Used by `agents/qa-reviewer.md`. The same agent code and prompt serve every stage; the only thing
that changes is the checklist file in `skills/qa-review/checklists/<stage>.toml`.

## Checklist format

```toml
stage = "SRS"

[[checks]]
id = "SRS-01"
severity = "blocking"   # or "advisory"
text = "What the draft must satisfy."
```

- `id` is unique inside the file and is what the model cites in `checklist_id`.
- `severity` is a ceiling: the model may report an issue as `advisory` when the check is
  `blocking`, never the other way. The code caps anything higher (`cap_severity`).

## How the result is used

The model returns only issues. `QaReport.passed` is true when no issue is `blocking`; the model
does not state a verdict. An issue with an unknown `checklist_id` or a `ref` that is not an item of
the draft makes the report unusable: it is retried once, then the run escalates.

## What is not here

Whether the SRS covers every in-scope BRD requirement is decided by the deterministic gate in
`masterba.agents.srs_writer.validate_srs_draft`, before any review is paid for.

## Adding a stage

Add `skills/qa-review/checklists/<stage>.toml` (lower-case document type) and call
`masterba.agents.qa_reviewer.review` with the stage's upstream text and numbered draft view.
No change to the reviewer is needed.
