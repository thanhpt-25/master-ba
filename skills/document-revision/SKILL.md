---
name: document-revision
description: How an approved Decision Record is turned into new document versions by patches, with stable ids, QA review and trace-link updates. Used by the document-reviser agent and the dr propagate command.
---

# document-revision

Used by `agents/document-reviser.md` and `masterba.change.propagate`. Spec: `specs/07-change-management.md`.

## Flow

1. `dr approve` runs impact analysis (graph query, no LLM) and stores it.
2. `dr propagate` visits the affected documents in V order (BRD, SRS, Basic Design, IT, ST, Detail
   Design, UT). For each one a writer + QA team runs; the writer returns a `RevisionPatch`.
3. Deterministic gate: `apply_patch` must succeed. QA then reviews the patch with the checklist of
   the document type (`brd`, `srs`, `basic_design`, `tests`, `detail_design`, `unit_tests`).
4. On done, a non-empty patch becomes version `n + 1` (never an overwrite); an empty patch changes
   nothing. Missing trace links are added, none are deleted.

## Rules and where they are enforced

| Rule | Enforcement |
|---|---|
| Untouched items stay identical | `apply_patch` copies them as they are |
| Ids are stable and never reused | `update` cannot change identity fields; `remove` sets `status: removed`; new numbers are `max + 1`; `add_document` enforces the ID Stability Rule |
| References point at active nodes | `apply_patch` checks every reference of a changed or added item |
| Requirement mirror | BRD `update` of a description updates `RequirementItem.text`; `remove` marks the requirement removed; BRD `add` creates `REQ-####` |
| No silent cascade | Propagation is a separate human action after approval (`manual_gate`) |
| Resumable | `DR-####.propagation.json` records finished documents; a rerun skips them |
