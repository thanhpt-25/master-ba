# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Phases 0 (scaffold), 1 (data contracts: models, `trace_store`, diff), 2 (Excel rendering) 3 (BRD walking skeleton), 4 (SRS, QA reviewer, team runtime) 5 (Basic Design + IT/ST tests, three-member team) and 6 (Detail Design + UT tests, same loop) are done (live reviews in spec 03/04/05 section 9; the Phase 5 live run has not reached `done` on the free gateway models). Change management (Decision Records), the dashboard and template calibration do not exist yet (Phase 7+). Conventions (toolchain, repo layout, ID scheme, ID Stability Rule, document versioning, commit format) are binding and defined in `specs/00-constitution.md` — read it before adding code.

## Commands

Python env is managed with `uv` (Python 3.11, `.venv/`):

```bash
uv sync                          # install deps + dev tools
uv run pytest                    # all tests; coverage report is on by default, fails under 80%
uv run pytest tests/trace_store/test_store.py::test_add_requirement_commits_and_rejects_reuse   # single test
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests            # strict mode
uv run python -m masterba.schema_export   # regenerate schemas/*.schema.json after changing a model
uv run python -m masterba.rendering.shells # regenerate templates/default/* after editing rendering/catalog.py
```

## Architecture (Phase 3 state)

Code lives in `src/masterba/`:
- `models/`: frozen Pydantic v2 models are the single source of truth; `schemas/*.schema.json` are generated from them and a test fails if they drift.
- `trace_store/`: file-based project store under `projects/<project_id>/`. Each business action is exactly one git commit (`commit_paths` commits only the files it wrote), and the store must run inside a git repo. `add_document` enforces the ID Stability Rule (a new version may not drop or revive item ids) and raises `IdStabilityError`.
- `trace_store/graph.py`: trace links point upstream to downstream; test case ids (`TC-...`) are aliases of their test item ref. `query_impact` and `rtm` walk only trace edges, not document containment edges.
- `rendering/`: JSON to `.xlsx`, no LLM. `catalog.py` is the single source for the 8 baseline templates; `shells.py` generates `templates/default/<TYPE>.xlsx` and `<TYPE>.template.json` from it (a test fails if the committed files drift). Bindings in `TemplateDefinition.cell_bindings` are parsed into typed models in `bindings.py` at load time. Output is byte-deterministic (`xlsxio.workbook_bytes` fixes zip timestamps), so re-rendering unchanged content makes no git commit. Every string is written as text, never as a formula.
- `llm/`: `LLM` protocol (`generate(system, user, output, tool_name)`), `AnthropicLLM` (forced tool call, key only from `ANTHROPIC_API_KEY`) and `FakeLLM`; every automated test uses the fake.
- `agents/requirements_analyst.py` + `agents/requirements-analyst.md` (prompt) + `skills/brd-from-intake/`: the model returns a `BrdDraft` without ids; `validate_draft` is the deterministic gate (citations in range, quote is a substring of the cited lines, unique titles), one retry, never repairs output.
- `team/`: Phase Team runtime. `Team` owns a `runs/RUN-####/` workspace (tasks, mailbox, token budget, escalations, single-writer check) and `run_writer_review` is the loop used by BRD and SRS: writer draft, deterministic gate (errors go back to the writer, no QA call), QA review, repeat up to `team_max_rounds` / `team_token_budget`, otherwise `escalated`. Summary, tasks and mailbox are committed once at the end; `transcripts/` is gitignored per run.
- `team/design_test_loop.py` + `agents/design_writer.py` + `agents/test_writer.py` + `pipeline/basic.py`: the Basic Design stage. Designer, tester and QA; a round is one cycle (designer, tester, gates, then QA reviews design and tests). The tester may question the designer (max 2 exchanges per cycle, mailbox `question`/`answer`); a question about an already answered item stops blocking and is reported as a customer question. On done it writes `DOC-BASIC_DESIGN-0001`, `DOC-TEST_IT-0001`, `DOC-TEST_ST-0001`, links (`realizes`, and `tests` for design item to TC-IT and SRS item to TC-ST) and renders all three; every design item has an IT case or an exclusion, every SRS item an ST case or an exclusion (`TestSpecContent.exclusions`).
- `agents/detail_writer.py`, `agents/unit_test_writer.py`, `pipeline/detail.py`: the Detail Design stage reuses `run_design_test_team` unchanged (Basic Design item to detail item `realizes`, detail item to `TC-UT` `tests`); `pipeline/stage.py` holds helpers shared by the pipelines.
- `agents/qa_reviewer.py`: one stage-neutral reviewer; only `skills/qa-review/checklists/<stage>.toml` differs. The model returns issues only, the verdict is computed (`QaReport.passed`), severity is capped by the checklist. `agents/srs_writer.py`: BRD to `SrsDraft` with coverage gate and open questions.
- `pipeline/brd.py` and `pipeline/srs.py`: `run_brd` / `run_srs` run the team, then (only if done) assign ids in code, write requirements/document/trace links, render, commit the run record. Nothing business-related is written on escalation. Both refuse when the document already exists.
- `cli.py`: `masterba init-project [--language ja|en]` (default `ja`; sets `ProjectConfig.document_language`, the language of generated content), `masterba run brd --project PRJ-001 --input file.txt` and `masterba run srs --project PRJ-001` and `masterba run basic --project PRJ-001` and `masterba run detail --project PRJ-001` (extra `--test-model`), all with `--model` / `--qa-model` (a stronger separate QA model is recommended); exit code 3 means escalated (installed console script; `--root` is the git work tree, default cwd). Live-model test: `uv run pytest -m live` with `ANTHROPIC_API_KEY` (an Anthropic-compatible gateway works via `ANTHROPIC_BASE_URL` and `MASTERBA_MODEL`).
- `diff/`: structural diff by stable item id plus `classify_change` (pure similarity, no LLM; numeric edits always count as structural).

## Intended purpose

Based on direction from the repository owner, this project will house a multi-agent system that generates and maintains Japanese-SIer-style V-Waterfall (IPA-defined) deliverables:

- Customer requirements → BRD (業務要件定義書) / SRS (システム要件定義書)
- BRD/SRS → Basic Design (基本設計書) + Basic Test Design (結合テスト仕様書 etc.)
- Basic Design → Detail Design (詳細設計書) + Detail Test Design (単体テスト仕様書)

Deliverables are Excel workbooks following per-company templates, defaulting to standard Japanese SIer templates when no company-specific template is specified. Changes to requirements or design must be tracked via a decision-record mechanism that propagates updates to dependent documents (traceability across the V-model).

A full concept design for this agent system is tracked in `docs/concept-design.md`, and the phased implementation plan (spec-driven development: spec → plan → tasks → implement → validate per phase) is tracked in `docs/roadmap-phases.md`. Per-phase specs will live under `specs/`, starting with `specs/00-constitution.md`.

## Working in this repo

Documentation language: all new or updated docs and specs (`docs/`, `specs/`, this file) are written in English. The existing Vietnamese docs (`docs/concept-design.md`, `docs/roadmap-phases.md`, `specs/00-constitution.md`, `specs/01-data-contracts.md`) are intentionally kept in Vietnamese and are not to be translated; only new documents are written in English. When editing a Vietnamese doc, keep its language consistent. Japanese terms for document types (e.g. 基本設計書) stay as-is.

Development is spec-driven: no code for a phase lands before its `specs/NN-*.md` exists. If code and spec disagree, fix the spec first (separate commit). Update this file with real architecture notes once the agent/skill/MCP code exists.

Until then, treat any architecture description elsewhere (plans, artifacts, design docs) as proposed/draft, not implemented.
