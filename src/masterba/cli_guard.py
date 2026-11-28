"""`masterba guard ...`: scan for sensitive data, prune transcripts, masking settings (spec 30)."""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from masterba.accounts.audit import AuditLog
from masterba.api.settings import settings_from_env
from masterba.guard import clean_terms, prune_transcripts, transcript_days
from masterba.guard.scan import scan_project
from masterba.models import ProjectConfig
from masterba.trace_store import get_config, open_project, set_config


def add_guard_parsers(commands: Any, project_id: Any) -> None:
    guard = commands.add_parser("guard", help="sensitive-data guardrails (spec 30)")
    subs = guard.add_subparsers(dest="guard_command", required=True)
    scan = subs.add_parser("scan", help="find secrets and personal data in a project")
    scan.add_argument("--project", type=project_id, required=True)
    scan.add_argument("--history", action="store_true", help="also every version in git")
    scan.add_argument("--json", action="store_true", help="print JSON")
    prune = subs.add_parser("prune", help="delete transcripts past the retention period")
    prune.add_argument("--days", type=int, default=None, help="default MASTERBA_TRANSCRIPT_DAYS")
    settings = subs.add_parser("settings", help="show or change a project's masking settings")
    settings.add_argument("--project", type=project_id, required=True)
    settings.add_argument("--pii", choices=["on", "off"], default=None)
    settings.add_argument("--term", action="append", default=[], help="a word to mask")
    settings.add_argument("--clear-terms", action="store_true")


def _audit(root: Path) -> AuditLog:
    return AuditLog(settings_from_env(root).state_dir / "audit.sqlite3")


def _emit(data: object) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def dispatch_guard(args: argparse.Namespace, root: Path) -> int:
    command: str = args.guard_command
    if command == "prune":
        days = args.days if args.days is not None else transcript_days()
        _emit({"removed": prune_transcripts(root, days), "days": days})
        return 0
    store = open_project(root / "projects", args.project)
    if command == "scan":
        config = get_config(store)
        report = scan_project(
            root, store.path, history=args.history, terms=tuple(config.masking_terms)
        )
        if args.json:
            _emit(report.to_json())
        else:
            for hit in report.hits:
                sys.stdout.write(hit.line() + "\n")
            counts = ", ".join(f"{n} {k}" for k, n in sorted(report.counts().items()))
            sys.stdout.write(f"{store.project_id}: {counts or 'nothing found'}\n")
        _audit(root).record(
            "cli",
            "guard.scan",
            project=store.project_id,
            target=store.project_id,
            detail={"history": args.history, **report.counts()},
            source="cli",
        )
        return 1 if report.secrets else 0
    current = get_config(store)
    changed = args.pii is not None or args.term or args.clear_terms
    if changed:
        terms = [] if args.clear_terms else list(current.masking_terms)
        updated = current.model_copy(
            update={
                "pii_masking": current.pii_masking if args.pii is None else args.pii == "on",
                "masking_terms": clean_terms([*terms, *args.term]),
            }
        )
        set_config(store, ProjectConfig.model_validate(updated.model_dump()))
        current = get_config(store)
        _audit(root).record(
            "cli",
            "project.guard",
            project=store.project_id,
            target=store.project_id,
            detail={"pii_masking": current.pii_masking, "terms": len(current.masking_terms)},
            source="cli",
        )
    _emit({"pii_masking": current.pii_masking, "masking_terms": current.masking_terms})
    return 0
