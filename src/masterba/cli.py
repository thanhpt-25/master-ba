"""Command line: ``masterba init-project`` and ``masterba run brd`` (spec 03 section 6)."""

import argparse
import getpass
import json
import os
import re
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from masterba import calibration
from masterba.agents import QaOutputInvalidError
from masterba.api import create_app, settings_from_env
from masterba.api.auth import ROLES, AuthError, UserStore
from masterba.calibration import CalibrationError
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
from masterba.cli_kb import KB_ERRORS, add_kb_parsers, dispatch_kb
from masterba.cli_review import REVIEW_ERRORS, add_review_parsers, dispatch_review
from masterba.doctor import init_root, run_checks
from masterba.llm import DEFAULT_MODEL, LLM, AnthropicLLM, LLMError
from masterba.models import ProjectConfig
from masterba.models.enums import (
    DocLanguage,
    DocType,
    DrTrigger,
    QuestionStatus,
    TeamRunStatus,
)
from masterba.models.ids import PROJECT_ID_PATTERN
from masterba.pipeline import (
    Resume,
    run_basic_design,
    run_brd,
    run_detail_design,
    run_srs,
    stage_summary,
)
from masterba.questions.answer import answer_question, withdraw_question
from masterba.rendering import RenderError
from masterba.team import ResumeError
from masterba.trace_store import (
    ProjectStore,
    TraceStoreError,
    create_project,
    get_decision_record,
    get_dr_extra,
    get_question,
    list_decision_records,
    list_questions,
    open_project,
)
from masterba.trace_store.git import ensure_ready

LLMFactory = Callable[[str], LLM]


def _project_id(value: str) -> str:
    if not re.match(PROJECT_ID_PATTERN, value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a project id like PRJ-001")
    return value


_STAGE_ALIASES = {"basic": DocType.BASIC_DESIGN, "detail": DocType.DETAIL_DESIGN}


def _stage_rounds(value: str) -> tuple[DocType, int]:
    """Parse ``STAGE=N`` for ``init-project --rounds`` (spec 11 section 2.1)."""
    name, sep, count = value.partition("=")
    stage = _STAGE_ALIASES.get(name.lower()) or next(
        (t for t in DocType if t.value == name.upper()), None
    )
    if not sep or stage is None or not count.isdigit() or int(count) < 1:
        raise argparse.ArgumentTypeError(f"{value!r} is not STAGE=N, for example basic=5")
    return stage, int(count)


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
    init.add_argument(
        "--rounds",
        type=_stage_rounds,
        action="append",
        default=[],
        metavar="STAGE=N",
        help="round limit of one stage (brd, srs, basic, detail); repeatable",
    )
    init.add_argument("--team-token-budget", type=int, default=None)
    init.add_argument(
        "--no-review-gates",
        action="store_true",
        help="run stages back to back without a review between them (spec 15)",
    )

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
    for stage_parser in (brd, srs, basic, detail):
        stage_parser.add_argument(
            "--resume", default=None, metavar="RUN-####", help="continue an escalated run"
        )
        stage_parser.add_argument(
            "--rounds", type=int, default=None, help="with --resume: rounds to add"
        )
    _add_dr_parsers(commands)
    _add_question_parsers(commands)
    _add_template_parsers(commands)
    add_kb_parsers(commands, _project_id)
    add_review_parsers(commands, _project_id)
    doctor = commands.add_parser("doctor", help="check this root and print what to fix")
    doctor.add_argument("--init", action="store_true", help="prepare an empty folder first")
    serve = commands.add_parser("serve", help="run the dashboard (API and web app)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    user = commands.add_parser("user", help="dashboard users")
    users = user.add_subparsers(dest="user_command", required=True)
    add = users.add_parser("add")
    add.add_argument("name")
    add.add_argument("--role", choices=ROLES, required=True)
    add.add_argument("--password-stdin", action="store_true")
    users.add_parser("list")
    users.add_parser("remove").add_argument("name")
    return parser


def _add_template_parsers(commands: Any) -> None:
    template = commands.add_parser("template", help="company templates from Excel samples")
    subs = template.add_subparsers(dest="template_command", required=True)

    def with_target(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--company", required=True)
        parser.add_argument(
            "--type", dest="doc_type", type=DocType, choices=list(DocType), required=True
        )
        return parser

    calibrate = with_target(subs.add_parser("calibrate", help="read a sample, write a draft"))
    calibrate.add_argument("sample", type=Path)
    calibrate.add_argument("--replace", action="store_true")
    calibrate.add_argument("--model", default=None, help="let a model refine the mapping")
    for name in ("show", "check", "unconfirm"):
        with_target(subs.add_parser(name))
    preview = with_target(subs.add_parser("preview", help="render the draft and compare"))
    preview.add_argument("--project", type=_project_id, default=None)
    confirm = with_target(subs.add_parser("confirm"))
    confirm.add_argument("--by", required=True)
    setter = with_target(subs.add_parser("set", help="assign a field to a column"))
    setter.add_argument("--sheet", required=True)
    setter.add_argument("--col", required=True)
    setter.add_argument("--field", default=None, help="omit to leave the column unmapped")
    subs.add_parser("list").add_argument("--company", default=None)


def _dispatch_template(args: argparse.Namespace, root: Path, llm_factory: LLMFactory) -> int:
    command: str = args.template_command
    if command == "list":
        _emit({"templates": calibration.list_templates(root, args.company)})
        return 0
    company, doc_type = args.company, args.doc_type
    if command == "calibrate":
        model = args.model
        outcome = calibration.calibrate(
            root,
            company,
            doc_type,
            args.sample,
            llm=llm_factory(model) if model else None,
            replace=args.replace,
        )
        _emit(
            {
                "state": "draft",
                "warnings": outcome.draft.warnings,
                "unmapped": outcome.draft.unmapped,
                "messages": list(outcome.messages),
            }
        )
    elif command == "show":
        _emit(
            {
                "state": calibration.state_of(root, company, doc_type),
                "mapping": calibration.load_draft(root, company, doc_type).model_dump(mode="json"),
            }
        )
    elif command == "check":
        problems = calibration.check(root, company, doc_type)
        _emit({"ok": not problems, "problems": problems})
        return 1 if problems else 0
    elif command == "preview":
        project = open_project(root / "projects", args.project) if args.project else None
        shown = calibration.preview(root, company, doc_type, project)
        _emit({"path": str(shown.path), "differences": list(shown.differences)})
    elif command == "confirm":
        _emit(dict(calibration.confirm(root, company, doc_type, args.by)))
    elif command == "unconfirm":
        calibration.unconfirm(root, company, doc_type)
        _emit({"state": "draft"})
    else:
        changed = calibration.set_column(root, company, doc_type, args.sheet, args.col, args.field)
        _emit({"state": "draft", "warnings": changed.warnings})
    return 0


def _add_question_parsers(commands: Any) -> None:
    question = commands.add_parser("question", help="customer questions and their answers")
    subs = question.add_subparsers(dest="question_command", required=True)

    def with_project(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--project", type=_project_id, required=True)
        return parser

    listing = with_project(subs.add_parser("list", help="the ledger, optionally by status"))
    listing.add_argument("--status", type=QuestionStatus, choices=list(QuestionStatus))
    with_project(subs.add_parser("show")).add_argument("question_id")
    answer = with_project(subs.add_parser("answer", help="record an answer as a Decision Record"))
    answer.add_argument("question_id")
    answer.add_argument("--by", required=True, help="who records the answer")
    answer.add_argument("--text", required=True, help="the answer")
    answer.add_argument("--source", default=None, help="who gave it and where, outside the system")
    with_project(subs.add_parser("withdraw")).add_argument("question_id")


def _dispatch_question(args: argparse.Namespace, store: ProjectStore) -> int:
    command: str = args.question_command
    if command == "list":
        found = [q for q in list_questions(store) if args.status in (None, q.status)]
        _emit({"questions": [q.model_dump(mode="json") for q in found]})
        return 0
    if command == "show":
        question = get_question(store, args.question_id)
    elif command == "answer":
        question = answer_question(store, args.question_id, args.text, args.by, source=args.source)
    else:
        question = withdraw_question(store, args.question_id)
    data: dict[str, object] = {"question": question.model_dump(mode="json")}
    if question.dr_id:
        data["dr"] = get_decision_record(store, question.dr_id).model_dump(mode="json")
    _emit(data)
    return 0


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
        _emit(result.to_json())
        return 3 if result.escalated else 0
    return 0


def _default_llm(model: str) -> LLM:
    return AnthropicLLM(model)


def _emit(data: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _dispatch_user(args: argparse.Namespace, root: Path) -> int:
    settings = settings_from_env(root)
    store = UserStore(settings.state_dir / "users.json", settings.hash_iterations)
    if args.user_command == "add":
        if args.password_stdin:
            password = sys.stdin.readline().rstrip("\n")
        else:
            password = getpass.getpass("Password: ")
            if getpass.getpass("Repeat password: ") != password:
                raise AuthError("the passwords differ")
        user = store.add(args.name, args.role, password)
        _emit({"name": user.name, "role": user.role})
    elif args.user_command == "list":
        _emit({"users": [{"name": u.name, "role": u.role} for u in store.list()]})
    else:
        store.remove(args.name)
        _emit({"removed": args.name})
    return 0


def _dispatch(args: argparse.Namespace, llm_factory: LLMFactory) -> int:
    root: Path = args.root
    if args.command == "user":
        return _dispatch_user(args, root)
    if args.command == "doctor":
        if args.init:
            init_root(root)
        checks = run_checks(root)
        sys.stdout.write("".join(f"{c.line()}\n" for c in checks))
        return 0 if all(c.ok or not c.required for c in checks) else 1
    ensure_ready(root)
    if args.command == "serve":
        import uvicorn

        uvicorn.run(create_app(settings_from_env(root)), host=args.host, port=args.port)
        return 0
    if args.command == "template":
        return _dispatch_template(args, root, llm_factory)
    if args.command == "kb":
        return dispatch_kb(args, root)
    projects = root / "projects"
    if args.command == "init-project":
        store = create_project(
            projects,
            ProjectConfig(
                project_id=args.project,
                company_id=args.company,
                document_language=args.language,
                team_max_rounds=args.team_max_rounds,
                team_max_rounds_by_stage=dict(args.rounds),
                team_token_budget=args.team_token_budget,
                review_gates=not args.no_review_gates,
            ),
        )
        _emit({"project_id": store.project_id, "path": str(store.path)})
        return 0
    store = open_project(projects, args.project)
    if args.command == "question":
        return _dispatch_question(args, store)
    if args.command == "review":
        return dispatch_review(args, root, llm_factory)
    if args.command == "dr":
        return _dispatch_dr(args, store, root, llm_factory)
    model = args.model or os.environ.get("MASTERBA_MODEL") or DEFAULT_MODEL
    writer = llm_factory(model)
    reviewer = llm_factory(args.qa_model) if args.qa_model else None
    if args.rounds is not None and (args.resume is None or args.rounds < 1):
        raise ValueError("--rounds needs --resume and a positive number")
    resume = Resume(args.resume, args.rounds) if args.resume else None
    if args.stage == "brd":
        result = run_brd(
            store,
            root / "templates",
            writer,
            args.input,
            qa_llm=reviewer,
            reuse_intake=args.reuse_intake,
            resume=resume,
        )
    elif args.stage == "srs":
        result = run_srs(store, root / "templates", writer, qa_llm=reviewer, resume=resume)
    else:
        tester = llm_factory(args.test_model) if args.test_model else None
        stage = run_basic_design if args.stage == "basic" else run_detail_design
        result = stage(
            store, root / "templates", writer, tester_llm=tester, qa_llm=reviewer, resume=resume
        )
    _emit(stage_summary(result))
    return 3 if result.status is TeamRunStatus.ESCALATED else 0


def main(argv: Sequence[str] | None = None, *, llm_factory: LLMFactory | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return _dispatch(args, llm_factory or _default_llm)
    except (
        TraceStoreError,
        ResumeError,
        AuthError,
        CalibrationError,
        LifecycleError,
        RenderError,
        LLMError,
        QaOutputInvalidError,
        *KB_ERRORS,
        *REVIEW_ERRORS,
        OSError,
        ValueError,
    ) as exc:
        sys.stderr.write(f"masterba: error: {exc}\n")
        return 1
