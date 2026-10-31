"""Command line: ``masterba init-project`` and ``masterba run brd`` (spec 03 section 6)."""

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

from masterba.agents import DraftRejectedError
from masterba.llm import DEFAULT_MODEL, LLM, AnthropicLLM, LLMError
from masterba.models import ProjectConfig
from masterba.models.enums import DocLanguage
from masterba.models.ids import PROJECT_ID_PATTERN
from masterba.pipeline import run_brd
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

    run = commands.add_parser("run", help="run one stage")
    stages = run.add_subparsers(dest="stage", required=True)
    brd = stages.add_parser("brd", help="intake text -> BRD json + xlsx")
    brd.add_argument("--project", type=_project_id, required=True)
    brd.add_argument("--input", type=Path, required=True, help="intake .txt or .md file")
    brd.add_argument("--model", default=None)
    brd.add_argument("--reuse-intake", action="store_true")
    return parser


def _default_llm(model: str) -> LLM:
    return AnthropicLLM(model)


def _emit(data: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _dispatch(args: argparse.Namespace, llm_factory: LLMFactory) -> None:
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
            ),
        )
        _emit({"project_id": store.project_id, "path": str(store.path)})
        return
    store = open_project(projects, args.project)
    model = args.model or os.environ.get("MASTERBA_MODEL") or DEFAULT_MODEL
    result = run_brd(
        store,
        root / "templates",
        llm_factory(model),
        args.input,
        reuse_intake=args.reuse_intake,
    )
    _emit(
        {
            "document_id": result.document_id,
            "requirement_ids": list(result.requirement_ids),
            "xlsx": str(result.xlsx_path),
            "open_questions": list(result.open_questions),
            "uncovered_lines": list(result.uncovered_lines),
            "attempts": result.attempts,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }
    )


def main(argv: Sequence[str] | None = None, *, llm_factory: LLMFactory | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        _dispatch(args, llm_factory or _default_llm)
    except (TraceStoreError, RenderError, LLMError, DraftRejectedError, OSError, ValueError) as exc:
        sys.stderr.write(f"masterba: error: {exc}\n")
        return 1
    return 0
