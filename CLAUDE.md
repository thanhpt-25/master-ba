# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Phases 0 (scaffold) and 1 (data contracts: models, `trace_store`, diff) are done; there is no Excel rendering, agent or orchestrator code yet (Phase 2+). Conventions (toolchain, repo layout, ID scheme, ID Stability Rule, document versioning, commit format) are binding and defined in `specs/00-constitution.md` — read it before adding code.

## Commands

Python env is managed with `uv` (Python 3.11, `.venv/`):

```bash
uv sync                          # install deps + dev tools
uv run pytest                    # all tests; coverage report is on by default, fails under 80%
uv run pytest tests/trace_store/test_store.py::test_add_requirement_commits_and_rejects_reuse   # single test
uv run ruff check . && uv run ruff format --check .
uv run mypy src tests            # strict mode
PYTHONPATH=src uv run python -m masterba.schema_export   # regenerate schemas/*.schema.json after changing a model
```

## Architecture (Phase 1 state)

Code lives in `src/masterba/`:
- `models/`: frozen Pydantic v2 models are the single source of truth; `schemas/*.schema.json` are generated from them and a test fails if they drift.
- `trace_store/`: file-based project store under `projects/<project_id>/`. Each business action is exactly one git commit (`commit_paths` commits only the files it wrote), and the store must run inside a git repo. `add_document` enforces the ID Stability Rule (a new version may not drop or revive item ids) and raises `IdStabilityError`.
- `trace_store/graph.py`: trace links point upstream to downstream; test case ids (`TC-...`) are aliases of their test item ref. `query_impact` and `rtm` walk only trace edges, not document containment edges.
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
