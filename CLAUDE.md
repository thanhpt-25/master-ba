# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project status

Phase 0 (scaffold) is done: folder layout and toolchain exist, but there is no application code or tests yet. Conventions (toolchain, repo layout, ID scheme, ID Stability Rule, document versioning, commit format) are binding and defined in `specs/00-constitution.md` — read it before adding code.

## Commands

Python env is managed with `uv` (Python 3.11, `.venv/`):

```bash
uv sync                          # install deps + dev tools
uv run pytest                    # run tests (coverage via pytest-cov; fail_under=80 when using --cov)
uv run pytest tests/path/test_x.py::test_name   # single test
uv run ruff check . && uv run ruff format --check .
uv run mypy src                  # strict mode
```

## Intended purpose

Based on direction from the repository owner, this project will house a multi-agent system that generates and maintains Japanese-SIer-style V-Waterfall (IPA-defined) deliverables:

- Customer requirements → BRD (業務要件定義書) / SRS (システム要件定義書)
- BRD/SRS → Basic Design (基本設計書) + Basic Test Design (結合テスト仕様書 etc.)
- Basic Design → Detail Design (詳細設計書) + Detail Test Design (単体テスト仕様書)

Deliverables are Excel workbooks following per-company templates, defaulting to standard Japanese SIer templates when no company-specific template is specified. Changes to requirements or design must be tracked via a decision-record mechanism that propagates updates to dependent documents (traceability across the V-model).

A full concept design for this agent system is tracked in `docs/concept-design.md`, and the phased implementation plan (spec-driven development: spec → plan → tasks → implement → validate per phase) is tracked in `docs/roadmap-phases.md`. Per-phase specs will live under `specs/`, starting with `specs/00-constitution.md`.

## Working in this repo

Development is spec-driven: no code for a phase lands before its `specs/NN-*.md` exists. If code and spec disagree, fix the spec first (separate commit). Update this file with real architecture notes once the agent/skill/MCP code exists.

Until then, treat any architecture description elsewhere (plans, artifacts, design docs) as proposed/draft, not implemented.
