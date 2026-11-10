# Next steps: hardening and local RAG

Status: proposal v0.2 (2026-10-31). v0.2 records the owner's answers on embeddings, vector store, source storage, file types, reviser scope and containers (12.5). Nothing here is implemented. Each phase below still follows the repo's spec-driven process: a `specs/NN-*.md` is written and approved before any code.

Phases 0 to 9 are done and Phase 10 is a backlog spec. This plan adds two phases:

- Phase 11 fixes what the live runs and the Phase 9 review exposed, and makes the project easier to install, run and keep green.
- Phase 12 lets the agents read a local, per-project knowledge base (retrieval-augmented generation that runs entirely on the user's machine), so drafts can rely on customer documents, glossaries and company standards beyond the intake text.

Phase 11 comes first because Phase 12 changes prompts and gates. Without the QA and resume fixes, a regression caused by retrieval would be hard to tell apart from the existing flakiness.

## Phase 11: hardening (`specs/11-hardening.md`)

### 11.1 Findings this phase answers

| Finding | Where it was recorded | Effect today |
|---|---|---|
| The basic design stage never reached `done` on the free gateway models | spec 05 section 9 | Phases 5 and 6 have no successful live run |
| A QA issue marked blocking can say the draft is acceptable | Phase 4 and 5 live runs | The loop spends rounds on issues that are not issues |
| An escalated run cannot resume from its last draft | specs 04 and 05 | A long run that stops at round N must start again from round 1 |
| No continuous integration | repo has no `.github/` | Nothing checks a push; the full suite takes about 5.5 minutes locally |
| `masterba` is not on `PATH` after `uv sync` | user report | The first command a new user types fails |
| Empty `backend/` and `mcp-configs/` folders from the Phase 0 scaffold; the constitution still names React/Next.js although spec 08 chose plain ES modules | repo, spec 00 | Readers are misled about the layout |
| Dashboard jobs live in memory | spec 08 | A server restart loses the job list and its logs |
| UAT has a template but no generating agent | spec 02, README | The top left of the V has no test document |

### 11.2 Work items

1. QA signal consistency. Add a deterministic check after each QA call: an issue whose severity is blocking must name an item id and a checklist rule, and its message must not contain the checklist's "acceptable" phrases. A contradictory issue is downgraded to advisory and recorded in the run's mailbox, so the record shows what was changed. Add a regression test built from the transcript of the live run that showed the problem.
2. Convergence on weaker models. Three changes, each measured separately on the recorded basic design run: tighten the designer and tester prompts with the questions QA asked most often, let the project config set a per-stage round limit, and allow QA to accept a draft whose only remaining issues are open customer questions. Success is a recorded live `done` for `run basic` and `run detail` with a named model.
3. Resume after escalation. Store the last validated draft and the open QA issues in the run workspace. `masterba run <stage> --resume RUN-####` starts the next round from that draft instead of from nothing. The run keeps its id and the summary records the resume. No business data is written until the run is done, as now.
4. CI. A GitHub Actions workflow running `ruff`, `mypy --strict` and `pytest` on push and pull request. Split the suite with a `slow` marker (the session-built demo chain and the API flows) so a quick job runs in under a minute and the full job runs on `main`.
5. Install and onboarding. Document `uv run masterba ...` and `uv tool install --editable .` in the README, and add `masterba doctor`, which checks git, the root layout, the template files and whether a model key is set, and prints what to fix.
6. Clean-up. Remove the empty scaffold folders or give them a README saying what will live there, and amend spec 00 (in Vietnamese, as that file is) to record the plain ES module frontend decision from spec 08.
7. Persistent jobs. Write each dashboard job's state and log lines to `.masterba/jobs/<project>/<job>.json`, so a restart shows past jobs and marks interrupted ones as `interrupted`. Still one job per project, with no queue.
8. UAT generation (optional here; it may move to its own phase). A `run uat` stage from the BRD, reusing `run_design_test_team` with the BRD as the design side, and a `uat.toml` checklist. Only if the owner wants the full V before Phase 12.
9. Containers (owner decision: Docker Compose for every component). One image built from `pyproject.toml` and `uv.lock` (multi-stage: `uv sync --frozen` in a builder, a slim Python 3.11 runtime with git, running as a non-root user). One Compose service `masterba` runs `masterba serve --host 0.0.0.0` and the CLI runs as `docker compose run --rm masterba <command>`, so both use the same code and the same data. The work tree (`projects/`, `templates/`, `.masterba/`) is a bind mount or named volume, because the store must stay a git repository the user can inspect; git author name and email come from environment variables. Model keys come from an env file that is gitignored, never from the image. A health check calls a new unauthenticated `GET /api/health`. The CI job builds the image and runs the quick test job inside it.

### 11.3 Acceptance criteria

- The QA consistency check has unit tests and one transcript-based regression test.
- Live `run basic` and `run detail` reach `done` with a named model, recorded in the spec with token counts.
- `--resume` continues a recorded escalated run and finishes it with the fake model in tests.
- CI is green on `main`, and the quick job takes under a minute.
- On a fresh clone, `uv sync` followed by `uv run masterba doctor` reports a clean setup.
- `docker compose up` serves the dashboard; `docker compose run --rm masterba init-project ...` and a stage run with the fake model write commits that are visible in the mounted work tree; the container runs as a non-root user and no key is present in the image (`docker history` and the image filesystem are checked in CI).

## Phase 12: local RAG (`specs/12-local-rag.md`)

### 12.1 Goal

Agents today see only the intake text and the upstream document. Real projects come with more: earlier specifications, interface lists, business glossaries, the customer's naming standards, meeting notes and the SIer's own design standards. Phase 12 indexes such files per project and gives the writers and the QA reviewer the passages relevant to each item, with citations a gate can check.

Local means the documents, the index and the embedding model stay on the user's machine. Only the passages chosen for a prompt go to the language model, the same way the intake text does today. A fully offline setup, with a local model behind an Anthropic-compatible gateway, already works through `ANTHROPIC_BASE_URL` and needs no change here.

### 12.2 Design

```
projects/PRJ-001/knowledge/
  sources/               files added by the user (md, txt, docx, xlsx, pdf); gitignored
  manifest.json          source id, file name, sha256, added by, added at; committed
  index/                 chunks, LanceDB vectors, FTS5 keyword index; gitignored, rebuildable
```

- Sources and manifest. `masterba kb add --project PRJ-001 FILE...` copies files into `sources/` and records them in `manifest.json`, one commit of the manifest per action like every other store change. Each source gets an id `KB-####` and each chunk a ref `KB-#####chunk.<n>`, following the existing item-ref style.
- Extraction. Plain text and Markdown as they are; `.xlsx` with openpyxl (one chunk per block of rows, sheet name kept); `.docx` and `.pdf` through small extractors chosen in the spec. Chunks follow headings and paragraphs, a few hundred characters each, with the heading path kept as context.
- Retrieval. Hybrid search: a keyword index (SQLite FTS5 with character bigrams, so Japanese text without spaces still matches) plus vector search over local embeddings, merged by reciprocal rank fusion. Keyword search catches exact terms such as screen names and ids, which embeddings often miss.
- Embeddings. A multilingual model that handles Japanese well, run locally through `sentence-transformers` (decision 12.5.1). The spec picks between `bge-m3` and `multilingual-e5` on the evaluation set. Vectors are stored in LanceDB (decision 12.5.2), which keeps the index in files and needs no server.
- A `Retriever` protocol (`search(query, k, filters) -> list[Passage]`), mirroring the `LLM` protocol, with a `FakeRetriever` for tests. Every automated test keeps running offline and without the embedding model.
- Prompt use. Passages go into the prompt between `<reference>` tags with their refs, marked as data and never as instructions, like the intake text. The writer may cite `KB-#####chunk.<n>` in `source_ref`.
- Citation gate. The deterministic gate that already checks intake citations also checks KB citations: the ref exists in this project's manifest, and a quoted span is a substring of that chunk. A wrong citation goes back to the writer, as today.
- QA. The reviewer receives the same passages and a checklist rule: a statement that contradicts a cited passage is a blocking issue.
- Traceability. KB sources become trace nodes (kind `knowledge`) linked to the items that cite them, so impact analysis can answer "which requirements depend on this glossary entry". Replacing a source creates a DR proposal listing the citing items, through the existing `dr new` path.
- Dashboard. A Knowledge tab with upload, a list with status (indexed, failed, stale) and a search box showing ranked passages with their refs. Admins and approvers may add sources; viewers may search.

### 12.3 Security and privacy

- Sources may be confidential, so `sources/` and the index are gitignored (decision 12.5.3); only the manifest of hashes is committed.
- Uploads follow the intake and calibration rules: an allow-list of file types, a size limit per file, no macros, no external links followed, archives refused.
- Retrieved text is untrusted. It is wrapped and labeled as data, and the prompts already tell agents to ignore instructions inside data. A test feeds a passage containing an injected instruction and checks that the draft ignores it.
- Indexing needs no network access beyond downloading the embedding model once, which `masterba kb setup` does explicitly.

### 12.4 Acceptance criteria

- `kb add`, `kb list`, `kb remove`, `kb search` and `kb reindex` work from the CLI with one commit per stored change, and the index rebuilds from the sources alone.
- Retrieval quality is measured on a small Japanese and English test set committed with the spec (questions with their expected chunk). Recall at 5 is reported for keyword only, vector only and hybrid, and hybrid is not worse than either.
- A stage run with the fake model and a fake retriever cites a KB chunk, and the gate rejects a fabricated ref and a quote that is not in the chunk.
- One live BRD and SRS run on a demo project with a glossary source cites at least one glossary entry correctly, recorded in the spec.
- Replacing a cited source proposes a DR listing the citing items.
- All existing tests pass without the embedding model installed; it is an optional extra (`uv sync --extra rag`).

### 12.5 Decisions (taken 2026-10-31 by the owner)

1. Embeddings run with `sentence-transformers` inside the Python process. No separate embedding service.
2. Vectors are stored in LanceDB, under `knowledge/index/`. The keyword index stays in SQLite FTS5 next to it.
3. Knowledge sources stay local and are never committed. `sources/` is gitignored; `manifest.json` is committed and holds only the source id, file name, sha256, who added it and when. A clone without the sources shows them as missing, and `kb reindex` refuses until they are put back.
4. The first round supports md, txt, xlsx, docx and pdf. PDF means the text layer only; scanned PDFs (OCR) are out of scope and reported as "no text found".
5. Retrieval feeds only the generating stages (BRD, SRS, basic design, detail design) at first. The DR reviser gets it later, once the evaluation set shows retrieval helps.
6. All components run in containers with Docker Compose (see 11.2 item 9 and 12.6).

### 12.6 Containers for RAG

The Phase 11 image gains the `rag` extra as a build argument (`--build-arg EXTRAS=rag`), so the default image stays small. The embedding model is downloaded once by `masterba kb setup` into a named volume (`model-cache`, mounted as the Hugging Face cache), never baked into the image and never fetched at request time. The LanceDB and FTS index live in the project volume with the sources, so they persist across container restarts and rebuild from the sources if deleted.

## Order and size

| Step | Size | Depends on |
|---|---|---|
| 11.2 items 1 to 3: QA check, convergence, resume | M | live model access |
| 11.2 items 4 to 7: CI, onboarding, clean-up, persistent jobs | S each | nothing |
| 11.2 item 8: UAT stage | M | the owner's choice |
| 11.2 item 9: Docker image and Compose | S | item 4 (CI builds the image) |
| Spec 12, with the decisions in 12.5 | S | Phase 11 QA and resume items |
| Phase 12 store, extraction, keyword index | M | spec 12 |
| Phase 12 embeddings, hybrid retrieval, evaluation set | M | spec 12 |
| Phase 12 RAG image variant and model cache volume | S | item 9 and the embeddings row |
| Phase 12 prompt, gate, QA and trace integration | M | the two rows above |
| Phase 12 dashboard Knowledge tab | S | the store |

CI, onboarding and clean-up depend on nothing else. They can start at once, alongside the spec for Phase 12.
