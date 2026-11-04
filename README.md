# MasterBA

MasterBA is a multi-agent system that turns customer requirements into the deliverables of a Japanese SIer V-Waterfall project (the IPA model): BRD, SRS, basic design and detail design, plus the test specifications that go with them. The output is Excel in the layout a company already uses. Every document is versioned, every item is traceable to the requirement it came from, and a change to a requirement can be pushed through the documents that depend on it.

```
Customer requirements
        │
        ▼
BRD (業務要件定義書) ──────────────────────────── UAT (not generated yet)
        │
        ▼
SRS (システム要件定義書) ───────────────────────── ST specification
        │
        ▼
Basic design (基本設計書) ──────────────────────── IT specification (結合テスト)
        │
        ▼
Detail design (詳細設計書) ─────────────────────── UT specification (単体テスト)
```

A person reviews each phase before the next one starts: the stages do not run end to end on their own.

```
intake ─▶ BRD ─▶ [review] ─▶ SRS ─▶ [review] ─▶ Basic design + IT/ST ─▶ [review] ─▶ Detail design + UT ─▶ [review]
              ▲                  ▲
              │ reject with comments: a writer and QA team writes the next version
              │
   side loops: customer questions · Decision Records · knowledge base
```

## Concept

### Why the work is split into content and layout

A language model is good at drafting text and poor at reproducing a spreadsheet cell by cell. So the agents never touch Excel. They return structured JSON, a deterministic renderer fills the workbook, and the two layers share only a schema. This has three consequences:

- A company's template can change, or be replaced with one calibrated from its own sample, without regenerating any content.
- Rendering the same JSON twice gives byte-identical files, so a re-render of unchanged content is not a git change.
- What a model said and how it was laid out can be reviewed separately.

### Identifiers and stability

Models do not invent identifiers. Code assigns them after a stage has passed its gates.

| Kind | Form | Example |
|---|---|---|
| Project | `PRJ-###` | `PRJ-001` |
| Requirement | `REQ-####` | `REQ-0002` |
| Document | `DOC-<TYPE>-####` | `DOC-BRD-0001` |
| Item inside a document | `<document>#item.<n>` | `DOC-SRS-0001#item.4` |
| Test case | `TC-<LEVEL>-####` | `TC-IT-0003` |
| Decision record | `DR-####` | `DR-0001` |
| Team run | `RUN-####` | `RUN-0007` |
| Customer question | `Q-####` | `Q-0004` |
| Knowledge source and chunk | `KB-####`, and `KB-####` + `#chunk.<n>` | `KB-0001#chunk.3` |
| Phase review | `REV-####` | `REV-0002` |

Documents are versioned with integers and a version is never overwritten. The ID stability rule says that a new version may not drop an item id or bring a dropped one back. Impact analysis relies on it: a link from `REQ-0002` to `DOC-SRS-0001#item.4` must still mean the same thing after the fourth revision.

### Traceability

Trace links point from upstream to downstream and have a type: `realizes` (requirement to design item), `tests` (item to test case), and `derives_from`, `verifies` and `implements`. A change request is answered by walking these edges, so the system can list the documents and items a requirement touches and the requirements an item or test case verifies, without asking a model.

### Teams, gates and escalation

Each stage is run by a small team rather than a single call. The shape is the same for every stage:

1. The writer returns a draft through a forced tool call, so the output is structured and validated against a schema.
2. A deterministic gate checks what code can check: citations point into the intake text and the quoted text is a substring of the cited lines, titles are unique, every upstream item is covered. Errors go straight back to the writer and cost no QA call.
3. A QA reviewer works from a checklist in `skills/qa-review/checklists/<stage>.toml`. The model only reports issues; code computes the verdict, and the checklist caps how severe an issue can be.
4. The loop repeats until the draft passes or a limit is reached (`team_max_rounds`, `team_token_budget` in the project config).

When a limit is reached the run is escalated: the command exits with code 3 and nothing business-related is written. A model request that fails (timeout, connection or gateway error) escalates the run the same way, so it can be resumed. The design stages add a tester. A tester can put questions to the designer through a mailbox, at most two exchanges per cycle, and a question about an item that was already answered is reported as an open question for the customer instead of blocking the loop.

### Review gates between phases

A finished stage stores its documents `in_review`, and the next stage refuses to start until a person approves the phase. The reviewer either approves (the documents become `approved`, a review record `reviews/REV-####.json` is committed) or rejects with comments. A rejection becomes a `review_feedback` Decision Record: the reviser writes version n+1 for another review and the rejected version is marked `superseded`. Basic design is reviewed together with its IT and ST specifications, detail design with its UT specification. The gate is a project setting, on for new projects (`init-project --no-review-gates` turns it off for scripted runs).

### Customer questions

What only the customer can settle is not guessed. The writers, the tester and QA raise questions, which go into a ledger (`questions/Q-####.json`). An answer is recorded as an approved clarification Decision Record, and every later model call gets the answered points as `<confirmed>` facts and the unanswered ones as `<open_questions>`. No stage may state an answer to an open question, even when the intake or a knowledge passage contains one.

### Knowledge base

A project can hold reference files (glossaries, standards, earlier specifications in `.md`, `.txt`, `.xlsx`, `.docx` or `.pdf`). They are split into chunks and indexed locally: always a keyword index, and with the optional `rag` extra also vectors from a local embedding model. Each writer gets the passages that match its input in an escaped `<knowledge>` block, may cite them by chunk, and code checks every citation before QA sees the draft. QA gets the same block and may block a draft that contradicts it. Citations become trace links, so replacing or removing a cited source proposes a Decision Record.

### Change management

A decision record (DR) is how a change enters the system. It moves through proposed, approved, propagated and closed, and a rejected record is closed immediately. The default is a manual gate: nothing is revised until a person approves the record.

On approval the system computes the impact from the trace graph and orders the affected documents along the V (BRD, SRS, basic design, IT, ST, detail design, UT). Propagation then runs one writer and QA team per document. The reviser agent does not rewrite a document. It returns a patch of `update`, `add` and `remove` operations, and a pure function applies it, so items the patch does not mention stay byte-identical and keep their ids. Each result is stored as version n+1 with a before and after diff. A rerun resumes from the documents that are not yet done.

The diff has two levels: a structural comparison by item id, and a classification of each changed item as reworded or structural. The classification uses text similarity only, and any change to a number counts as structural.

### Company templates

The defaults follow common SIer layouts and live in `templates/default/`. A company can override them. Given a sample workbook, calibration reads the sheets, finds the header row, matches the column labels against a table of Japanese and English synonyms, optionally asks a model to refine the mapping, and writes a draft template. A validation gate checks every sheet, cell and field in the draft. The renderer ignores the draft until an administrator confirms it, and any later edit removes the confirmation.

## Architecture

```
                          ┌────────────────────────────┐
                          │ CLI (masterba)  Dashboard  │   cli.py, api/, frontend/
                          └─────────────┬──────────────┘
                                        │ same library calls, same git history
                          ┌─────────────▼──────────────┐
                          │ pipeline/   change/        │   stages, decision records
                          │ review/     questions/     │   phase gates, customer questions
                          │ knowledge/                 │   retrieval for the writers
                          └───────┬─────────────┬──────┘
                                  │             │
                  ┌───────────────▼───┐   ┌─────▼────────────────┐
                  │ team/  agents/    │   │ rendering/           │
                  │ gates, QA, loops  │   │ JSON + template → xlsx│
                  └───────┬───────────┘   └─────┬────────────────┘
                          │                     │
                  ┌───────▼───────┐             │
                  │ llm/          │             │
                  │ LLM protocol  │             │
                  └───────────────┘             │
                          ┌─────────────────────▼────────────────┐
                          │ trace_store/   models/   diff/       │
                          │ files in a git work tree, one commit │
                          │ per business action                  │
                          └──────────────────────────────────────┘
```

### Packages

| Package | Role |
|---|---|
| `models/` | Frozen Pydantic v2 models. They are the single source of truth; `schemas/*.schema.json` is generated from them and a test fails if the two drift. |
| `trace_store/` | A file-based project store under `projects/<project_id>/`. Each business action is one git commit, and `commit_paths` commits only the files it wrote. `graph.py` answers impact and requirements-traceability-matrix queries by walking trace edges only. |
| `rendering/` | The renderer. A `TemplateDefinition` holds a sheet map, typed cell bindings (tables, header cells, numbering) and validation rules. Strings are always written as text, never as formulas. |
| `llm/` | The `LLM` protocol (`generate(system, user, output, tool_name)`), an Anthropic implementation that forces a tool call, and a `FakeLLM` that every automated test uses. |
| `agents/` | One module per agent, with its prompt in `agents/*.md` at the repository root. The requirements analyst, SRS writer, design and test writers, detail and unit-test writers, and the stage-neutral QA reviewer. |
| `team/` | The Phase Team runtime: a run workspace with tasks, a mailbox, a token budget, escalations and a single-writer check. |
| `pipeline/` | `run_brd`, `run_srs`, `run_basic_design` and `run_detail_design`. Each runs its team and, only if the team is done, assigns ids, writes the document, links it and renders it. |
| `change/` | Decision record lifecycle, impact analysis, patches, the reviser and propagation. |
| `review/` | Phase review gates: the gate the pipelines check before a stage starts (`gates.py`), and approve and reject (`actions.py`). |
| `questions/` | The ledger of customer questions, answers as clarification DRs, and the `<confirmed>` and `<open_questions>` blocks. |
| `knowledge/` | The project knowledge base: upload checks, extraction, keyword and optional vector indexes, the hybrid retriever, the `<knowledge>` block and the citation gate. |
| `calibration/` | Profile, heuristic mapper, optional model refinement, validation gate, build and confirmation of company templates. |
| `api/`, `frontend/` | The dashboard. FastAPI on the server; plain ES modules in the browser with no build step. The project overview opens with a workflow strip: phases in order, the review gate between them, the next action. |
| `diff/` | Structural diff by item id and the reworded or structural classifier. |

### What happens when a stage runs

Taking `masterba run srs` as the example:

1. The CLI opens the project and loads the latest BRD from the store. With review gates on, it refuses to start while the BRD phase is still in review.
2. The SRS writer produces a draft from the BRD, the confirmed facts, the open questions and the matching knowledge passages; the coverage gate checks that every BRD requirement is addressed, and the citation gate checks every knowledge citation.
3. The QA reviewer checks the draft against `srs.toml`; the loop repeats within its limits.
4. On success the pipeline assigns ids in code, writes `json/srs/DOC-SRS-0001.v1.json` (status `in_review` with gates), writes the trace links, renders `xlsx/srs/DOC-SRS-0001.v1.xlsx` with the company template, and commits. New customer questions go into the ledger.
5. The run record (summary, tasks and mailbox) is committed once at the end. Raw transcripts stay local and are git-ignored.

### Project layout on disk

```
projects/PRJ-001/
  project.json                 language, company id, team limits, review_gates
  intake/                      customer text as supplied
  requirements/REQ-0001.json
  json/<type>/DOC-<TYPE>-0001.v1.json
  xlsx/<type>/DOC-<TYPE>-0001.v1.xlsx
  traceability/links.json
  decision-records/DR-0001.json  (+ .impact.json, .propagation.json)
  questions/Q-0001.json        the customer questions ledger
  reviews/REV-0001.json        phase approvals and rejections
  knowledge/manifest.json      knowledge sources (sources/ and index/ are gitignored)
  runs/RUN-0001/               team-summary.json, team-tasks.json, mailbox.json
```

Commit subjects follow `<scope>(<project>): <action> <id>`, so `git log` reads as the audit trail of the project.

### The dashboard

`masterba serve` runs the API and the web app in one process. Users are local accounts with PBKDF2 hashes and a signed session cookie; the three roles (viewer, approver, admin) are read from the users file on every request. State-changing calls need an `X-MasterBA` header, and the content security policy allows no inline script or style. Stage runs and propagation are background jobs, one per project. The server calls the same library functions as the CLI, which is why the git history is identical either way. Model keys come from the server environment and never reach the browser.

## Status

Implemented: phases 0 to 9, hardening (spec 11), the local knowledge base (spec 12), the customer questions ledger (spec 13) and the phase review gates (spec 15). Phase 10, code generation and executable unit tests, exists only as a backlog spec (`specs/10-dev-extension.md`).

- A full live run of `tests/fixtures/intake/timesheet_ja.md` reached `done` in every stage with `kr/claude-opus-5.5` through a gateway (60 requirements, 67 SRS items, 55 design items, 148 UT cases; spec 11 section 10.3). That run predates the review gates; no live run with the gates has been recorded yet.
- Calibration has been tested only on synthetic samples. No real customer workbook has been tried.
- Templates for all eight document types exist, but nothing generates the UAT specification yet.
- The knowledge-base evaluation set is too easy to rank embedding models (keyword search alone scores 1.0; spec 12 section 18).

## Getting started

You need Python 3.11, [uv](https://docs.astral.sh/uv/), git, and for real runs an Anthropic-compatible API key. Tests use the fake model and need no key.

```bash
uv sync
uv run pytest        # offline; coverage must stay at or above 80%
```

`uv sync` installs the `masterba` command inside `.venv/`, not on your `PATH`. Either prefix every command below with `uv run` (`uv run masterba ...`) or install it once as a tool with `uv tool install --editable .`.

The key is read from the environment only:

```bash
export ANTHROPIC_API_KEY=...            # required for real runs
export ANTHROPIC_BASE_URL=...           # optional: an Anthropic-compatible gateway
export MASTERBA_MODEL=...               # optional: default writer model
export MASTERBA_QA_MODEL=...            # optional: separate, ideally stronger, QA model
export MASTERBA_REQUEST_TIMEOUT=900     # optional: seconds per request (default 180)
export MASTERBA_MAX_TOKENS=32000        # optional: output tokens per call (default 16000)
export MASTERBA_EMBED_MODEL=BAAI/bge-m3 # optional: embedding model for the rag extra
```

A failed model request escalates the run instead of crashing it, so `--resume` continues it. Raise the two limits above for a large intake.

### Running the stages

`--root` is the git work tree that holds `projects/` and `templates/`; it defaults to the current directory.

```bash
masterba --root ~/masterba-work doctor --init    # once: an empty folder becomes a git work tree with templates
cd ~/masterba-work && masterba doctor            # prints each check and how to fix a failing one
masterba init-project --project PRJ-001 --language ja
masterba run brd    --project PRJ-001 --input intake.txt
masterba review approve --project PRJ-001 --stage brd --by alice     # review gate (spec 15)
masterba run srs    --project PRJ-001
masterba review approve --project PRJ-001 --stage srs --by alice
masterba run basic  --project PRJ-001            # basic design + IT/ST specs
masterba review approve --project PRJ-001 --stage basic --by alice
masterba run detail --project PRJ-001            # detail design + UT specs
masterba review approve --project PRJ-001 --stage detail --by alice
```

A new project has review gates: each stage stores its documents `in_review`, and the next stage
refuses to start until a person approves the phase. `masterba review status --project PRJ-001` shows
where each phase stands. To send a phase back instead, reject it with comments; a writer and QA team
writes the next version for another review:

```bash
masterba review reject --project PRJ-001 --stage srs --by alice \
  --comment "DOC-SRS-0001#item.12: Split this into two obligations." \
  --comment "Use the glossary term 受注 throughout."
```

`init-project --no-review-gates` runs the stages back to back, as scripted runs need. On the dashboard,
a phase in review shows Approve and Reject on its card.

Use `--model`, `--qa-model` and, for the design stages, `--test-model` to pick a model for each role. `init-project --rounds basic=6` gives one stage more rounds than the default.

A run that escalates keeps its last validated drafts in `runs/RUN-####/checkpoint.json` (not committed). Continue it instead of starting over:

```bash
masterba run basic --project PRJ-001 --resume RUN-0004 --rounds 2
```

It refuses when the upstream document changed since the run, or when the target document already exists.

### Changing a requirement

```bash
masterba dr new --project PRJ-001 --trigger requirement_change \
  --description "Password reset by SMS too." --item REQ-0002
masterba dr approve   --project PRJ-001 DR-0001 --approver alice --decision "ok"
masterba dr propagate --project PRJ-001 DR-0001   # revises the affected documents
masterba dr diff      --project PRJ-001 DR-0001
```

The other subcommands are `from-run`, `reject`, `close`, `list` and `show`.

### Calibrating a company template

```bash
masterba template calibrate sample.xlsx --company ACME --type BRD
masterba template show      --company ACME --type BRD
masterba template set       --company ACME --type BRD --sheet 要件一覧 --col F --field source_ref
masterba template preview   --company ACME --type BRD
masterba template check     --company ACME --type BRD
masterba template confirm   --company ACME --type BRD --by alice
```

The repository ships a sample company, `sample-sier`, with seven confirmed templates in the usual Japanese SIer layout (cover sheet, revision history, document-info block, list sheet). `scripts/make_sier_samples.py OUTDIR` regenerates the sample workbooks they were calibrated from. A ready-made Japanese intake, `tests/fixtures/intake/hrm_employee_ja.txt` (a small HR management system), runs against it:

```bash
masterba --root work init-project --project PRJ-001 --company sample-sier --language ja
masterba --root work run brd --project PRJ-001 --input tests/fixtures/intake/hrm_employee_ja.txt
```

A larger example for a full run, `tests/fixtures/intake/timesheet_ja.md` (a timesheet system for a 200-person offshore developer: entry, PM approval, PMO reports), goes from BRD to Detail Design:

```bash
masterba --root work init-project --project PRJ-002 --language ja --no-review-gates
masterba --root work run brd    --project PRJ-002 --input tests/fixtures/intake/timesheet_ja.md
masterba --root work run srs    --project PRJ-002
masterba --root work run basic  --project PRJ-002
masterba --root work run detail --project PRJ-002
masterba --root work question list --project PRJ-002   # what the stages asked the customer
```

An intake of this size (60 requirements, 67 SRS items) needs higher request limits for the design tester calls; the recorded run (spec 11 section 10.3) used `MASTERBA_REQUEST_TIMEOUT=1800` and `MASTERBA_MAX_TOKENS=32000`.

### Customer questions and the knowledge base

```bash
masterba question list   --project PRJ-001 --status open
masterba question answer --project PRJ-001 Q-0004 --by alice --text "Partial deliveries: at most three."
masterba kb add    --project PRJ-001 --by alice glossary.md standards.xlsx
masterba kb search --project PRJ-001 "受注"
masterba kb list   --project PRJ-001
```

An answer becomes an approved clarification Decision Record and reaches every later model call. For vector search as well as keyword search, install the extra and download the model once: `uv sync --extra rag`, then `masterba kb setup`.

### Dashboard

```bash
masterba user add alice --role admin          # roles: viewer < approver < admin
masterba serve --port 8000                    # then open http://127.0.0.1:8000
```

Users are stored in `.masterba/`, which git ignores. The project overview opens with the workflow strip; a phase in review shows Approve and Reject with comments, and the next stage's Run button waits until the phase before it is approved. The Questions and Knowledge tabs cover the side loops.

### Docker Compose

The image holds the code; your work tree stays on the host, so it remains a git repository you can open.

```bash
cp .env.example .env                                   # put the key here; .env is gitignored
docker compose build
docker compose run --rm masterba doctor --init         # prepares ./work (MASTERBA_WORK to change it)
docker compose run --rm masterba user add alice --role admin
docker compose up -d                                   # dashboard on http://127.0.0.1:8000
```

A first example from the CLI, with a file placed in `./work/examples/`:

```bash
docker compose run --rm masterba init-project --project PRJ-001 --language ja
docker compose run --rm masterba run brd --project PRJ-001 --input /work/examples/order_portal.txt
docker compose run --rm masterba review approve --project PRJ-001 --stage brd --by alice
docker compose run --rm masterba run srs --project PRJ-001
docker compose run --rm masterba review status --project PRJ-001
```

The workbooks appear in `./work/projects/PRJ-001/xlsx/` on the host. `docker compose down` stops the service and keeps `./work`.

The port is published on 127.0.0.1 only; the dashboard has local accounts and no TLS, so think twice before exposing it. A gateway running on the host is reached from the container as `http://host.docker.internal:<port>`. Commits are authored as `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` from `.env`; on macOS also set `UID` and `GID` there so files in `./work` belong to you. Build with `EXTRAS=rag` for vector search; the embedding model is downloaded once into the `model-cache` volume with `docker compose run --rm masterba kb setup`.

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests                      # strict
uv run python -m masterba.schema_export    # after changing a model; a test fails on drift
uv run pytest -m "not slow" --no-cov       # quick loop, under a minute
uv run pytest -m live                      # optional: live model test, needs a key
```

CI (`.github/workflows/ci.yml`) runs the quick job on every push, the full suite with coverage on `main`, and builds the image.

To understand how the system works, read [docs/architecture](docs/architecture/README.md): the layers, the data model and storage, the data flow of each stage, the control flow of the writer, QA and resume loops, change management, the interfaces and deployment, customer questions, the knowledge base and the phase review gates.

Development is spec-driven. A phase's `specs/NN-*.md` is written and approved before its code, and `specs/00-constitution.md` holds the binding conventions (toolchain, layout, id scheme, versioning, commit format). `docs/concept-design.md` and `docs/roadmap-phases.md` give the full design and the phase plan. New documents are written in English; the earlier Vietnamese documents (`docs/concept-design.md`, `docs/roadmap-phases.md` and specs 00 and 01) stay as they are.

## License

See [LICENSE](LICENSE).
