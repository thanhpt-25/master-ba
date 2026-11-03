# 8. Knowledge base

A project can hold reference files (glossaries, standards, earlier specifications) that the
generating stages may quote from. Writers receive retrieved passages in their prompt, cite them by
ref, and the citation gate checks every citation in code. QA receives the same passages and may
block a draft that contradicts one. The spec is [specs/12-local-rag.md](../../specs/12-local-rag.md).

## 8.1 Layout

```
projects/PRJ-001/knowledge/
  manifest.json      committed; the only knowledge file in git
  .lock              gitignored; flock held by every add, replace, remove and reindex
  sources/           gitignored; files stored as KB-####<ext>, never under the uploaded name
  index/             gitignored, rebuildable
    CURRENT          name of the active generation, switched with os.replace
    gen-0007/
      keyword.sqlite chunks table + FTS5 table of character-bigram hex tokens
      vectors.lance/ LanceDB table (only with the rag extra and a set-up model)
      record.json    ReindexRecord: format version, embedder name, sha256 and status per source
```

- `KB-####` ids are never reused; removed sources stay in the Manifest with `removed: true`.
- A chunk is `KB-####` followed by `#chunk.<n>`, numbered from 1 in document order.
- Status is computed on read: `missing` (file absent) wins over `stale` (hash, format version or
  embedder differ from `record.json`), which wins over the recorded `indexed` or `failed`.
- Every action writes in the order sources, new generation, Manifest, commit, activate. A failure
  before the commit restores the earlier state; a failed build leaves the previous generation active.
- Each action is one commit, `kb(<project>): add|replace|remove KB-####`, holding only
  `manifest.json`. The store checks the ignore rules first and adds missing patterns to
  `.git/info/exclude` for work trees created before this phase.

## 8.2 Indexing and search

| Part | Module | Notes |
|---|---|---|
| Upload checks | `knowledge/safety.py` | name, empty, 20 MB, archives, type, content signature, Office macros, 200 MB uncompressed |
| Extraction | `knowledge/extract/` | `.md`/`.txt` paragraphs under headings, `.xlsx` runs of non-empty rows, `.docx` body in order, `.pdf` one page per chunk; pieces of at most 1,000 code points |
| Keyword index | `knowledge/keyword.py` | bigrams computed in Python, stored as ASCII hex tokens so FTS5 `bm25()` ranks them |
| Vectors (optional) | `knowledge/embedder.py`, `vectors.py` | `sentence-transformers` + LanceDB from the `rag` extra, flat cosine search, loaded offline after `masterba kb setup` |
| Retriever | `knowledge/retriever.py` | 50 keyword + 50 vector candidates merged by RRF (k = 60); keyword-only when vectors are unavailable; only active sources are returned |

Without the extra, or before the model is set up, everything works keyword-only and the CLI prints
a notice.

## 8.3 In a stage

```mermaid
sequenceDiagram
  participant P as pipeline (brd, srs, basic, detail)
  participant K as KnowledgeSession
  participant W as writer
  participant G as gate
  participant Q as QA
  P->>K: open_session (before Team.open)
  Note over K: None without indexed sources; a broken index stops the stage, nothing written
  K->>K: one search per query segment of the writer's input, k = 12, indexed sources only
  K->>W: Reference_Block after the main input, before the previous draft
  W->>G: draft with kb_citations
  G->>G: stage gate + validate_kb_citations
  G-->>W: errors back to the writer, no QA call, round counted
  K->>Q: the same block text (no new search) and the contradiction check
  Q->>K: blocking contradictions without a block ref become advisory
```

- The block is `<knowledge>` with one `<reference ref="...">` per passage, at most 12 passages and
  12,000 escaped characters. Passage text has `<` and `>` replaced, and the block states that its
  content is data, not instructions.
- Each writer role (writer, designer, tester) has its own block; the design review gets the
  designer's block and the test review the tester's.
- With no knowledge base the prompts are identical to the ones before this phase
  (`tests/agents/test_prompt_identity_property.py` checks this against a frozen copy).
- The citation gate checks, per citation: the index covers the Manifest, the ref is well formed,
  source and chunk exist, the optional quote is copied exactly (whitespace-insensitive, at most 500
  characters), and the ref was in a block of this run. Seen refs are kept in the run checkpoint, so
  `--resume` keeps them; the first writer call after a resume searches again.
- The BRD rule that every requirement cites intake lines is unchanged; a Chunk_Ref adds to it.
- DR propagation (`change/reviser.py`) makes no search and gets no block.

## 8.4 Traceability and change

- On `done`, stored items keep their citations. The document's commit also writes
  `traceability/knowledge-nodes.json` (the cited Source_Ids) and one `derives_from` link per
  (source, citing item) into `links.json`. An escalated run writes neither.
- `query_impact("KB-0003")` walks those links downstream; a Source_Id that was never cited raises
  "no Knowledge_Node exists".
- Replacing or removing a cited source first creates a `proposed` DR with trigger
  `knowledge_change` listing the citing items, then commits the Manifest
  (`knowledge/proposal.py`). If the DR cannot be created nothing changes; if the Manifest commit
  fails afterwards, the error names the DR to reject. Removal keeps the node and its links.

## 8.5 Surfaces

| Surface | Commands or routes |
|---|---|
| CLI (`cli_kb.py`) | `masterba kb setup [--model]`, `add --project P [--by NAME] FILE...`, `list`, `replace KB-#### FILE`, `remove KB-####`, `reindex`, `search "QUERY" [-k N]` |
| API (`api/routes_knowledge.py`) | `GET /api/projects/{pid}/knowledge` (viewer), `POST /api/projects/{pid}/knowledge` multipart `file` (approver), `PUT /api/projects/{pid}/knowledge/{source_id}` (approver), `DELETE /api/projects/{pid}/knowledge/{source_id}` (approver), `GET /api/projects/{pid}/knowledge/search?q=&k=` (viewer) |
| Dashboard | Knowledge tab (`frontend/views/knowledge.js`): sources with status, upload, replace and remove for approvers, search |
| Containers | `HF_HOME=/models` on the `model-cache` volume; build with `EXTRAS=rag` and run `docker compose run --rm masterba kb setup` once |

API errors: 400 (refusal, bad search argument), 404 (unknown project or source), 409 (index
unavailable), 500 (Manifest commit failed). `added_by` is always the signed-in user.

## 8.6 Evaluation

`tests/knowledge/eval/` holds two sample sources and 40 questions (20 Japanese, 20 English).
`uv run python -m masterba.knowledge.evaluation [--model NAME]` prints Recall@5 per language for
keyword, vector and hybrid; `uv run pytest -m rag_eval` asserts hybrid is at least as good as each.
Both need the `rag` extra and a model set up by `masterba kb setup`.
