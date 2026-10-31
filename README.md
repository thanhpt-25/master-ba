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

Documents are versioned with integers and a version is never overwritten. The ID stability rule says that a new version may not drop an item id or bring a dropped one back. Impact analysis relies on it: a link from `REQ-0002` to `DOC-SRS-0001#item.4` must still mean the same thing after the fourth revision.

### Traceability

Trace links point from upstream to downstream and have a type: `realizes` (requirement to design item), `tests` (item to test case), and `derives_from`, `verifies` and `implements`. A change request is answered by walking these edges, so the system can list the documents and items a requirement touches and the requirements an item or test case verifies, without asking a model.

### Teams, gates and escalation

Each stage is run by a small team rather than a single call. The shape is the same for every stage:

1. The writer returns a draft through a forced tool call, so the output is structured and validated against a schema.
2. A deterministic gate checks what code can check: citations point into the intake text and the quoted text is a substring of the cited lines, titles are unique, every upstream item is covered. Errors go straight back to the writer and cost no QA call.
3. A QA reviewer works from a checklist in `skills/qa-review/checklists/<stage>.toml`. The model only reports issues; code computes the verdict, and the checklist caps how severe an issue can be.
4. The loop repeats until the draft passes or a limit is reached (`team_max_rounds`, `team_token_budget` in the project config).

When a limit is reached the run is escalated: the command exits with code 3 and nothing business-related is written. The design stages add a tester. A tester can put questions to the designer through a mailbox, at most two exchanges per cycle, and a question about an item that was already answered is reported as an open question for the customer instead of blocking the loop.

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
| `calibration/` | Profile, heuristic mapper, optional model refinement, validation gate, build and confirmation of company templates. |
| `api/`, `frontend/` | The dashboard. FastAPI on the server; plain ES modules in the browser with no build step. |
| `diff/` | Structural diff by item id and the reworded or structural classifier. |

### What happens when a stage runs

Taking `masterba run srs` as the example:

1. The CLI opens the project and loads the latest BRD from the store.
2. The SRS writer produces a draft; the coverage gate checks that every BRD requirement is addressed.
3. The QA reviewer checks the draft against `srs.toml`; the loop repeats within its limits.
4. On success the pipeline assigns ids in code, writes `json/srs/DOC-SRS-0001.v1.json`, writes the requirement records and trace links, renders `xlsx/srs/DOC-SRS-0001.v1.xlsx` with the company template, and commits.
5. The run record (summary, tasks and mailbox) is committed once at the end. Raw transcripts stay local and are git-ignored.

### Project layout on disk

```
projects/PRJ-001/
  project.json                 language, company id, team limits
  intake/                      customer text as supplied
  requirements/REQ-0001.json
  json/<type>/DOC-<TYPE>-0001.v1.json
  xlsx/<type>/DOC-<TYPE>-0001.v1.xlsx
  traceability/links.json
  decision-records/DR-0001.json  (+ .impact.json, .propagation.json)
  runs/RUN-0001/               team-summary.json, team-tasks.json, mailbox.json
```

Commit subjects follow `<scope>(<project>): <action> <id>`, so `git log` reads as the audit trail of the project.

### The dashboard

`masterba serve` runs the API and the web app in one process. Users are local accounts with PBKDF2 hashes and a signed session cookie; the three roles (viewer, approver, admin) are read from the users file on every request. State-changing calls need an `X-MasterBA` header, and the content security policy allows no inline script or style. Stage runs and propagation are background jobs, one per project. The server calls the same library functions as the CLI, which is why the git history is identical either way. Model keys come from the server environment and never reach the browser.

## Status

Phases 0 to 9 are implemented. Phase 10, code generation and executable unit tests, exists only as a backlog spec (`specs/10-dev-extension.md`); it argues that the base needs only a new node kind for code and an optional result field on test cases.

- Calibration has been tested only on synthetic samples. No real customer workbook has been tried.
- Templates for all eight document types exist, but nothing generates the UAT specification yet.
- With the free gateway models used so far, the basic design stage has not reached `done`, because the QA reviewer is strict (see `specs/05-basic-design-and-tests.md`, section 9).
- Phase 11 (hardening: QA signal, resume, containers, CI) is in progress; see `specs/11-hardening.md`.

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
```

### Running the stages

`--root` is the git work tree that holds `projects/` and `templates/`; it defaults to the current directory.

```bash
masterba --root ~/masterba-work doctor --init    # once: an empty folder becomes a git work tree with templates
cd ~/masterba-work && masterba doctor            # prints each check and how to fix a failing one
masterba init-project --project PRJ-001 --language ja
masterba run brd    --project PRJ-001 --input intake.txt
masterba run srs    --project PRJ-001
masterba run basic  --project PRJ-001            # basic design + IT/ST specs
masterba run detail --project PRJ-001            # detail design + UT specs
```

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

### Dashboard

```bash
masterba user add alice --role admin          # roles: viewer < approver < admin
masterba serve --port 8000                    # then open http://127.0.0.1:8000
```

Users are stored in `.masterba/`, which git ignores.

### Docker Compose

The image holds the code; your work tree stays on the host, so it remains a git repository you can open.

```bash
cp .env.example .env                                   # put the key here; .env is gitignored
docker compose run --rm masterba doctor --init         # prepares ./work (MASTERBA_WORK to change it)
docker compose run --rm masterba user add alice --role admin
docker compose up                                      # dashboard on http://127.0.0.1:8000
docker compose run --rm masterba run brd --project PRJ-001 --input intake.txt   # a file in ./work
```

The port is published on 127.0.0.1 only; the dashboard has local accounts and no TLS, so think twice before exposing it. A gateway running on the host is reached from the container as `http://host.docker.internal:<port>`. Commits are authored as `GIT_AUTHOR_NAME` / `GIT_AUTHOR_EMAIL` from `.env`.

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests                      # strict
uv run python -m masterba.schema_export    # after changing a model; a test fails on drift
uv run pytest -m "not slow" --no-cov       # quick loop, under a minute
uv run pytest -m live                      # optional: live model test, needs a key
```

CI (`.github/workflows/ci.yml`) runs the quick job on every push, the full suite with coverage on `main`, and builds the image.

To understand how the system works, read [docs/architecture](docs/architecture/README.md): the layers, the data model and storage, the data flow of each stage, the control flow of the writer, QA and resume loops, change management, and the interfaces and deployment.

Development is spec-driven. A phase's `specs/NN-*.md` is written and approved before its code, and `specs/00-constitution.md` holds the binding conventions (toolchain, layout, id scheme, versioning, commit format). `docs/concept-design.md` and `docs/roadmap-phases.md` give the full design and the phase plan. New documents are written in English; the earlier Vietnamese documents (`docs/concept-design.md`, `docs/roadmap-phases.md` and specs 00 and 01) stay as they are.

## License

See [LICENSE](LICENSE).
