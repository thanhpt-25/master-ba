---
name: knowledge-citation-gate
description: Rules for citing the project knowledge base (Chunk_Ref, quote) that every writer and QA call shares across all stages. Used by pipeline/stage.py's kb_block/kb_text/kb_gate helpers and knowledge/session.py.
---

# knowledge-citation-gate

Cross-cutting: every stage (`pipeline/brd.py`, `srs.py`, `basic.py`, `detail.py`, `change/propagate.py`)
wires the same helpers (`pipeline/stage.py`: `kb_block`, `kb_text`, `kb_refs`, `kb_gate`) around its
own writer/QA loop. Spec: `specs/12-local-rag.md` (Requirements 9 and 10).

## Contract

A writer gets a fresh `Reference_Block` built from its own input (`KnowledgeSession.references_for`).
QA reuses that exact block, with no new search (Requirement 9.6, `KnowledgeSession.block_for_review`).
An item that cites a passage adds a `KbCitation` (`chunk_ref`, optional `quote`) to its payload; a
missing or disabled knowledge base makes every `kb_*` helper a no-op (`""` / `frozenset()` / `[]`).

## Rules and where they are enforced

| Rule | Enforcement |
|---|---|
| `Chunk_Ref` is well-formed and names a source in the project manifest | `citations.py:_problem`: `parse_chunk_ref`, then membership in `manifest_ids` |
| The chunk exists in the index | `_problem`: `chunk_text(ref)` must resolve |
| The quote is real and short | `_problem`: collapsed quote must be a substring of the passage, at most `MAX_QUOTE_CHARS` (500) |
| The cited ref was actually shown to the model this call | `_problem`: `ref not in seen_refs` fails — a role cannot cite a passage from someone else's block |
| The knowledge base must be queryable, not silently skipped | `_problem`: `index_covers_manifest` false fails every citation instead of passing them |
| The stage's own rule (e.g. intake-line citation) is not replaced | Each stage's `gate` lambda concatenates its own validator's errors with `kb_gate`'s (`brd.py`: "Chunk_Refs only add to it, Req. 10.8") |
| A QA check that needs the knowledge block does not exist without one | `qa_reviewer.active_checks` drops `requires_reference` checks when `references` is empty (Req. 11.3) |
| A blocking contradiction must cite the block it contradicts | `qa_reviewer.normalise_contradictions`: a `requires_reference` check with no `chunk_refs` inside the QA's own reference set is downgraded to advisory |
| Passages are data, never instructions | `reference.py`'s `DATA_STATEMENT`, prepended to every block |

Failures from `kb_gate` land in the same `gate=` list as the stage's deterministic validator, so a
citation problem goes back to the writer exactly like any other validation error — no separate
retry budget.

## Known limits

Without an index (`index_covers_manifest` false, e.g. mid-rebuild or the `rag` extra not installed)
every citation is rejected rather than silently accepted; a writer in that state should not cite at
all. Keyword-only mode (no embeddings) still enforces the same gate — it only changes what
`references_for` finds, not what `citations.py` accepts.
