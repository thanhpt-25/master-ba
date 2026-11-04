"""`masterba review ...`: approve or reject a phase between stages (spec 15 section 7)."""

import argparse
import json
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from masterba.llm import DEFAULT_MODEL, LLM
from masterba.models.enums import ReviewStage
from masterba.review import STAGE_DOCS, ReviewError, phase_state
from masterba.review.actions import approve_phase, parse_comment, reject_phase
from masterba.review.gates import latest
from masterba.trace_store import ProjectStore, get_question, list_reviews, open_project

REVIEW_ERRORS = (ReviewError,)
LLMFactory = Callable[[str], LLM]


def add_review_parsers(commands: Any, project_id: Any) -> None:
    review = commands.add_parser("review", help="approve or reject a phase between stages")
    subs = review.add_subparsers(dest="review_command", required=True)

    def with_project(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--project", type=project_id, required=True)
        return parser

    def with_stage(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--stage", type=ReviewStage, choices=list(ReviewStage), required=True)
        parser.add_argument("--by", required=True, help="who reviews")
        return parser

    with_project(subs.add_parser("status", help="the review state of every phase"))
    with_project(subs.add_parser("list", help="the review records"))
    with_stage(with_project(subs.add_parser("approve", help="let the next stage start")))
    reject = with_stage(with_project(subs.add_parser("reject", help="send the phase back")))
    reject.add_argument(
        "--comment",
        action="append",
        required=True,
        help="what to change; start with an item ref to name one (DOC-SRS-0001#item.3: ...)",
    )
    reject.add_argument("--model", default=None)
    reject.add_argument("--qa-model", default=None)


def _emit(data: object) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _status(store: ProjectStore) -> dict[str, object]:
    phases = []
    for stage in ReviewStage:
        docs = [(doc_id, latest(store, doc_id)) for doc_id in STAGE_DOCS[stage]]
        phases.append(
            {
                "stage": stage.value,
                "state": phase_state(store, stage),
                "documents": [
                    {"id": doc_id, "version": d.version, "status": d.status.value}
                    for doc_id, d in docs
                    if d is not None
                ],
            }
        )
    return {"project": store.project_id, "phases": phases}


def _warn_open(store: ProjectStore, ids: list[str]) -> None:
    # Spec 15 section 6: approving with open questions is allowed, but said out loud.
    if ids:
        sys.stderr.write(f"warning: {len(ids)} customer question(s) are still open:\n")
        for qid in ids:
            sys.stderr.write(f"  {qid}: {get_question(store, qid).text}\n")


def dispatch_review(args: argparse.Namespace, root: Path, llm_factory: LLMFactory) -> int:
    store = open_project(root / "projects", args.project)
    templates = root / "templates"
    command: str = args.review_command
    if command == "status":
        _emit(_status(store))
        return 0
    if command == "list":
        _emit({"reviews": [r.model_dump(mode="json") for r in list_reviews(store)]})
        return 0
    if command == "approve":
        review = approve_phase(store, templates, args.stage, args.by)
        _warn_open(store, review.open_questions)
        _emit(review.model_dump(mode="json"))
        return 0
    comments = [parse_comment(c) for c in args.comment]
    model = args.model or os.environ.get("MASTERBA_MODEL") or DEFAULT_MODEL
    reviser = llm_factory(model)
    qa = llm_factory(args.qa_model) if args.qa_model else None
    review, result = reject_phase(
        store, templates, args.stage, args.by, comments, reviser, qa_llm=qa
    )
    _emit({"review": review.model_dump(mode="json"), "revision": result.to_json()})
    return 3 if result.escalated else 0
