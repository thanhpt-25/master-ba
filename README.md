# MasterBA

A multi-agent system that turns customer requirements into Japanese-SIer-style V-Waterfall (IPA) deliverables, as Excel workbooks, with full traceability and change management.

```
Customer requirements ─▶ BRD (業務要件定義書) ─▶ SRS (システム要件定義書)
                                                   │
                  Basic Design (基本設計書) + IT/ST test specs ◀┘
                                  │
            Detail Design (詳細設計書) + UT test specs
```

- **Agents write JSON, code writes Excel.** Content agents return structured data; a deterministic renderer (openpyxl, no LLM) fills the company's Excel template. Re-rendering unchanged content produces byte-identical files.
- **Writer + QA teams.** Each stage runs a small team (writer, optional tester, QA reviewer) with a token budget and a round limit; if it cannot converge it escalates instead of writing anything.
- **Git is the audit trail.** Every business action is exactly one commit in a file-based project store.
- **Change management.** A Decision Record (DR) is proposed, approved, then propagated: impact analysis walks the trace graph and a reviser agent produces new versions of the affected documents, in V-model order.
- **Company templates.** Defaults follow standard SIer layouts; a company can supply its own Excel sample, which is calibrated into a template and used only after an admin confirms it.
- **Dashboard.** A local web app (FastAPI + plain ES modules, no build step) to run stages, browse documents, traceability and DRs.

## Status

Phases 0 to 9 are implemented; Phase 10 (code generation and executable unit tests) is a backlog spec only (`specs/10-dev-extension.md`).

- Template calibration has only been verified on synthetic samples; no real customer workbook has been tried yet.
- The Basic Design stage has not reached `done` on the free gateway models used so far (QA is strict; see `specs/05-basic-design-and-tests.md` section 9).
- After an escalation a run cannot resume from its last draft yet.

## Requirements

- Python 3.11 and [uv](https://docs.astral.sh/uv/)
- git (the store must live inside a git work tree)
- An Anthropic-compatible API key for real runs. Tests use a fake model and need no key.

## Setup

```bash
uv sync
uv run pytest        # offline; coverage must stay at or above 80%
```

The key is read only from the environment, never from files:

```bash
export ANTHROPIC_API_KEY=...            # required for real runs
export ANTHROPIC_BASE_URL=...           # optional: an Anthropic-compatible gateway
export MASTERBA_MODEL=...               # optional: default writer model
export MASTERBA_QA_MODEL=...            # optional: separate (ideally stronger) QA model
```

## Quick start

`--root` is the git work tree that holds `projects/` and `templates/` (default: the current directory).

```bash
git init && git commit --allow-empty -m init     # once, in your work tree
masterba init-project --project PRJ-001 --language ja
masterba run brd    --project PRJ-001 --input intake.txt
masterba run srs    --project PRJ-001
masterba run basic  --project PRJ-001            # Basic Design + IT/ST test specs
masterba run detail --project PRJ-001            # Detail Design + UT test specs
```

Each stage writes JSON under `projects/PRJ-001/`, renders `.xlsx`, links the items in the trace graph and commits. Exit code `3` means the team escalated; nothing business-related is written in that case. Use `--model`, `--qa-model` and (for design stages) `--test-model` to choose models per role.

### Changing requirements

```bash
masterba dr new --project PRJ-001 --trigger requirement_change \
  --description "Password reset by SMS too." --item REQ-0002
masterba dr approve   --project PRJ-001 DR-0001 --approver alice --decision "ok"
masterba dr propagate --project PRJ-001 DR-0001   # revises the affected documents
masterba dr diff      --project PRJ-001 DR-0001
```

Also: `dr from-run`, `reject`, `close`, `list`, `show`.

### Company templates

```bash
masterba template calibrate sample.xlsx --company ACME --type BRD
masterba template show      --company ACME --type BRD
masterba template set       --company ACME --type BRD --sheet 要件一覧 --col F --field source_ref
masterba template preview   --company ACME --type BRD
masterba template check     --company ACME --type BRD
masterba template confirm   --company ACME --type BRD --by alice
```

A calibrated template is ignored by the renderer until `confirm`; editing a column removes the confirmation.

### Dashboard

```bash
masterba user add alice --role admin          # roles: viewer < approver < admin
masterba serve --port 8000                    # then open http://127.0.0.1:8000
```

Users live in `.masterba/` (git-ignored). Models and keys come from the server environment; the browser never sees a key.

## Repository layout

| Path | Contents |
|---|---|
| `src/masterba/models/` | Frozen Pydantic models, the single source of truth for `schemas/` |
| `src/masterba/trace_store/` | File-based project store, trace graph, ID Stability Rule |
| `src/masterba/rendering/` | Deterministic JSON to `.xlsx` renderer and template loader |
| `src/masterba/agents/`, `agents/*.md`, `skills/` | Agent code, prompts and QA checklists |
| `src/masterba/team/` | Phase Team runtime (tasks, mailbox, budget, escalation) |
| `src/masterba/pipeline/` | BRD, SRS, Basic Design and Detail Design stages |
| `src/masterba/change/` | Decision Records, impact analysis, propagation |
| `src/masterba/calibration/` | Excel sample to company template |
| `src/masterba/api/`, `frontend/` | Dashboard backend and web app |
| `templates/default/` | The eight baseline Excel templates (generated from `rendering/catalog.py`) |
| `specs/` | One spec per phase; `00-constitution.md` holds the binding conventions |
| `docs/` | Concept design and roadmap |

## Development

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests                      # strict
uv run python -m masterba.schema_export    # after changing a model (a test fails on drift)
uv run pytest -m live                      # optional: live model test, needs a key
```

Development is spec-driven: a phase's `specs/NN-*.md` is written and approved before its code. Read `specs/00-constitution.md` before adding code (ID scheme, versioning, commit format). New documents are written in English; the earlier Vietnamese docs (`docs/concept-design.md`, `docs/roadmap-phases.md`, specs 00 and 01) stay as they are.

## License

See [LICENSE](LICENSE).
