"""Command line: ``masterba init-project`` and ``masterba run brd`` (spec 03 section 6)."""

import argparse
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from masterba.agents import QaOutputInvalidError
from masterba.change import (
    LifecycleError,
    approve_dr,
    close_dr,
    dr_diff,
    dr_from_run,
    new_dr,
    propagate_dr,
    reject_dr,
    rows,
)
from masterba.llm import DEFAULT_MODEL, LLM, AnthropicLLM, LLMError
from masterba.models import ProjectConfig
from masterba.models.enums import DocLanguage, DrTrigger, TeamRunStatus
from masterba.models.ids import PROJECT_ID_PATTERN
from masterba.pipeline import (
    StageResult,
    run_basic_design,
    run_brd,
    run_detail_design,
    run_srs,
)
from masterba.rendering import RenderError
from masterba.trace_store import (
    ProjectStore,
    TraceStoreError,
    create_project,
    get_decision_record,
    get_dr_extra,
    list_decision_records,
    open_project,
)
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
    _add_dr_parsers(commands)
    return parser


def _add_dr_parsers(commands: Any) -> None:
    dr = commands.add_parser("dr", help="Decision Records: change management")
    drs = dr.add_subparsers(dest="dr_command", required=True)

    def with_project(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--project", type=_project_id, required=True)
        return parser

    new = with_project(drs.add_parser("new", help="propose a change"))
    new.add_argument("--trigger", type=DrTrigger, choices=list(DrTrigger), required=True)
    new.add_argument("--description", required=True)
    new.add_argument("--item", action="append", default=[], help="REQ-#### or item ref")
    from_run = with_project(drs.add_parser("from-run", help="DR from an escalated run"))
    from_run.add_argument("--run", required=True)
    for name in ("approve", "reject"):
        signed = with_project(drs.add_parser(name))
        signed.add_argument("dr_id")
        signed.add_argument("--approver", required=True)
        signed.add_argument("--decision", required=True)
        signed.add_argument("--rationale", default=None)
    propagate = with_project(drs.add_parser("propagate", help="revise the affected documents"))
    propagate.add_argument("dr_id")
    propagate.add_argument("--model", default=None)
    propagate.add_argument("--qa-model", default=None)
    with_project(drs.add_parser("close")).add_argument("dr_id")
    with_project(drs.add_parser("list"))
    with_project(drs.add_parser("show")).add_argument("dr_id")
    diff = with_project(drs.add_parser("diff"))
    diff.add_argument("dr_id")
    diff.add_argument("--structural-only", action="store_true")


def _dispatch_dr(
    args: argparse.Namespace, store: ProjectStore, root: Path, llm_factory: LLMFactory
) -> int:
    command: str = args.dr_command
    if command == "new":
        _emit(new_dr(store, args.trigger, args.description, args.item).model_dump(mode="json"))
    elif command == "from-run":
        _emit(dr_from_run(store, args.run).model_dump(mode="json"))
    elif command == "approve":
        dr, impact = approve_dr(store, args.dr_id, args.approver, args.decision, args.rationale)
        _emit({"dr": dr.model_dump(mode="json"), "impact": impact.to_json()})
    elif command == "reject":
        dr = reject_dr(store, args.dr_id, args.approver, args.decision, args.rationale)
        _emit(dr.model_dump(mode="json"))
    elif command == "close":
        _emit(close_dr(store, args.dr_id).model_dump(mode="json"))
    elif command == "list":
        _emit(
            {"decision_records": [r.model_dump(mode="json") for r in list_decision_records(store)]}
        )
    elif command == "show":
        dr = get_decision_record(store, args.dr_id)
        _emit(
            {
                "dr": dr.model_dump(mode="json"),
                "impact": get_dr_extra(store, dr.id, "impact"),
                "propagation": get_dr_extra(store, dr.id, "propagation"),
            }
        )
    elif command == "diff":
        diffs = dr_diff(store, args.dr_id, args.structural_only)
        _emit(
            {
                "documents": [
                    {
                        "doc_id": d.doc_id,
                        "old_version": d.old_version,
                        "new_version": d.new_version,
                        "rows": rows(d),
                    }
                    for d in diffs
                ]
            }
        )
    else:
        model = args.model or os.environ.get("MASTERBA_MODEL") or DEFAULT_MODEL
        reviser = llm_factory(model)
        reviewer = llm_factory(args.qa_model) if args.qa_model else None
        result = propagate_dr(store, root / "templates", args.dr_id, reviser, qa_llm=reviewer)
        _emit(
            {
                "dr_id": result.dr_id,
                "status": result.status.value,
                "documents": [
                    {
                        "doc_id": d.doc_id,
                        "outcome": d.outcome,
                        "version": d.version,
                        "run_id": d.run_id,
                        "escalations": list(d.escalations),
                    }
                    for d in result.documents
                ],
            }
        )
        return 3 if result.escalated else 0
    return 0


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
    if args.command == "dr":
        return _dispatch_dr(args, store, root, llm_factory)
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
        LifecycleError,
        RenderError,
        LLMError,
        QaOutputInvalidError,
        OSError,
        ValueError,
    ) as exc:
        sys.stderr.write(f"masterba: error: {exc}\n")
        return 1
