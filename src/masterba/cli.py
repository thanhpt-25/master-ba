"""Command line: ``masterba init-project`` and ``masterba run brd`` (spec 03 section 6)."""

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from masterba.agents import QaOutputInvalidError
from masterba.llm import DEFAULT_MODEL, LLM, AnthropicLLM, LLMError
from masterba.models import ProjectConfig
from masterba.models.enums import DocLanguage, TeamRunStatus
from masterba.models.ids import PROJECT_ID_PATTERN
from masterba.pipeline import (
    StageResult,
    run_basic_design,
    run_brd,
    run_detail_design,
    run_srs,
)
from masterba.rendering import RenderError
from masterba.trace_store import TraceStoreError, create_project, open_project
from masterba.trace_store.git import ensure_ready

LLMFactory = Callable[[str], LLM]


def _project_id(value: str) -> str:
    if not re.match(PROJECT_ID_PATTERN, value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a project id like PRJ-001")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="masterba", description="Generate V-model deliverables from customer requirements"
    )
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="git work tree to use")
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init-project", help="create an empty project")
    init.add_argument("--project", type=_project_id, required=True)
    init.add_argument("--company", default="default")
    init.add_argument(
        "--language", type=DocLanguage, choices=list(DocLanguage), default=DocLanguage.JA
    )
    init.add_argument("--team-max-rounds", type=int, default=3)
    init.add_argument("--team-token-budget", type=int, default=None)

    run = commands.add_parser("run", help="run one stage")
    stages = run.add_subparsers(dest="stage", required=True)
    brd = stages.add_parser("brd", help="intake text -> BRD json + xlsx")
    brd.add_argument("--project", type=_project_id, required=True)
    brd.add_argument("--input", type=Path, required=True, help="intake .txt or .md file")
    brd.add_argument("--model", default=None)
    brd.add_argument(
        "--qa-model", default=None, help="model for the QA reviewer (default: --model)"
    )
    brd.add_argument("--reuse-intake", action="store_true")
    srs = stages.add_parser("srs", help="stored BRD -> SRS json + xlsx")
    srs.add_argument("--project", type=_project_id, required=True)
    srs.add_argument("--model", default=None)
    srs.add_argument(
        "--qa-model", default=None, help="model for the QA reviewer (default: --model)"
    )
    basic = stages.add_parser("basic", help="stored SRS -> Basic Design + IT/ST tests")
    basic.add_argument("--project", type=_project_id, required=True)
    basic.add_argument("--model", default=None, help="model for the designer")
    basic.add_argument("--test-model", default=None, help="model for the tester (default: --model)")
    basic.add_argument(
        "--qa-model", default=None, help="model for the QA reviewer (default: --model)"
    )
    detail = stages.add_parser("detail", help="stored Basic Design -> Detail Design + UT tests")
    detail.add_argument("--project", type=_project_id, required=True)
    detail.add_argument("--model", default=None, help="model for the designer")
    detail.add_argument(
        "--test-model", default=None, help="model for the tester (default: --model)"
    )
    detail.add_argument(
        "--qa-model", default=None, help="model for the QA reviewer (default: --model)"
    )
    return parser


def _default_llm(model: str) -> LLM:
    return AnthropicLLM(model)


def _emit(data: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _dispatch(args: argparse.Namespace, llm_factory: LLMFactory) -> int:
    root: Path = args.root
    ensure_ready(root)
    projects = root / "projects"
    if args.command == "init-project":
        store = create_project(
            projects,
            ProjectConfig(
                project_id=args.project,
                company_id=args.company,
                document_language=args.language,
                team_max_rounds=args.team_max_rounds,
                team_token_budget=args.team_token_budget,
            ),
        )
        _emit({"project_id": store.project_id, "path": str(store.path)})
        return 0
    store = open_project(projects, args.project)
    model = args.model or os.environ.get("MASTERBA_MODEL") or DEFAULT_MODEL
    writer = llm_factory(model)
    reviewer = llm_factory(args.qa_model) if args.qa_model else None
    if args.stage == "brd":
        result = run_brd(
            store,
            root / "templates",
            writer,
            args.input,
            qa_llm=reviewer,
            reuse_intake=args.reuse_intake,
        )
    elif args.stage == "srs":
        result = run_srs(store, root / "templates", writer, qa_llm=reviewer)
    else:
        tester = llm_factory(args.test_model) if args.test_model else None
        stage = run_basic_design if args.stage == "basic" else run_detail_design
        result = stage(store, root / "templates", writer, tester_llm=tester, qa_llm=reviewer)
    _emit(_summary(result))
    return 3 if result.status is TeamRunStatus.ESCALATED else 0


def _summary(result: StageResult) -> dict[str, object]:
    return {
        "stage": result.stage.value,
        "status": result.status.value,
        "run_id": result.run_id,
        "rounds": result.rounds,
        "issues_raised": result.issues_raised,
        "issues_resolved": result.issues_resolved,
        "advisory_issues": list(result.advisory),
        "escalations": list(result.escalations),
        "tokens_used": result.tokens_used,
        "document_id": result.document_id,
        "document_ids": list(result.document_ids),
        "exchanges": result.exchanges,
        "requirement_ids": list(result.requirement_ids),
        "xlsx": str(result.xlsx_path) if result.xlsx_path else None,
        "open_questions": list(result.open_questions),
        "uncovered_lines": list(result.uncovered_lines),
    }


def main(argv: Sequence[str] | None = None, *, llm_factory: LLMFactory | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args, llm_factory or _default_llm)
    except (
        TraceStoreError,
        RenderError,
        LLMError,
        QaOutputInvalidError,
        OSError,
        ValueError,
    ) as exc:
        sys.stderr.write(f"masterba: error: {exc}\n")
        return 1
