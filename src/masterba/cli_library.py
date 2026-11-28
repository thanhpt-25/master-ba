"""`masterba project ...` and the template-set commands of `masterba template` (spec 29 6.2).

The CLI has no signed-in user: it acts as the operator of the work tree, so it may switch any
project to any set and change the sharing of any set.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from masterba import library
from masterba.accounts import AuditLog
from masterba.api.auth import UserStore
from masterba.api.settings import settings_from_env
from masterba.library import TemplateAccess
from masterba.models.ids import PROJECT_ID_PATTERN
from masterba.trace_store import get_config, open_project

LIBRARY_ERRORS = (library.TemplateAccessError, library.UnknownSetError)


def _emit(data: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _project_id(value: str) -> str:
    if not re.fullmatch(PROJECT_ID_PATTERN, value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a project id like PRJ-001")
    return value


def add_project_parsers(commands: Any) -> None:
    project = commands.add_parser("project", help="a project's template set")
    subs = project.add_subparsers(dest="project_command", required=True)

    def with_project(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
        parser.add_argument("--project", type=_project_id, required=True)
        return parser

    switch = with_project(subs.add_parser("set-template", help="use another template set"))
    switch.add_argument("--template", required=True, help="a set id, or default")
    switch.add_argument("--accept-gaps", action="store_true", help="switch although data drops")
    report = with_project(subs.add_parser("coverage", help="what a set prints of the project"))
    report.add_argument("--template", required=True)
    again = with_project(subs.add_parser("reissue", help="render an approved version again"))
    again.add_argument("--doc", required=True)
    again.add_argument("--version", type=int, default=None)


def add_set_parsers(subs: Any) -> None:
    """Subcommands of `masterba template` that work on whole sets."""
    subs.add_parser("sets", help="every template set with owner and visibility")
    share = subs.add_parser("share", help="private, shared with users, or public")
    share.add_argument("--company", required=True)
    share.add_argument("--visibility", choices=library.VISIBILITIES, required=True)
    share.add_argument("--users", default="", help="comma separated names for shared")
    cloned = subs.add_parser("clone", help="copy a set to a new private set")
    cloned.add_argument("--company", required=True)
    cloned.add_argument("--to", required=True)
    cloned.add_argument("--owner", required=True)


def users_of(root: Path) -> UserStore:
    settings = settings_from_env(root)
    return UserStore(settings.state_dir / "users.json", settings.hash_iterations)


def _access(root: Path) -> tuple[TemplateAccess, AuditLog]:
    settings = settings_from_env(root)
    users = users_of(root)
    access = TemplateAccess(
        settings.state_dir / "template_access.json", settings.templates, users.list
    )
    return access, AuditLog(settings.state_dir / "audit.sqlite3")


def dispatch_sets(args: argparse.Namespace, root: Path) -> int:
    access, audit = _access(root)
    command: str = args.template_command
    if command == "sets":
        rows = []
        for set_id in ["default", *access.existing()]:
            entry = access.entry(set_id) or {}
            rows.append(
                {
                    "id": set_id,
                    "owner": entry.get("owner"),
                    "visibility": entry.get(
                        "visibility", "public" if set_id == "default" else None
                    ),
                    "shared_with": entry.get("shared_with", []),
                    "title": entry.get("title"),
                    "types": library.set_types(root, set_id),
                }
            )
        _emit({"sets": rows})
        return 0
    if command == "share":
        if args.company not in access.existing():
            raise library.UnknownSetError(f"no template set {args.company}")
        names = [n for n in args.users.split(",") if n.strip()]
        entry = access.set_visibility(args.company, args.visibility, names)
        audit.record("cli", "template.visibility", target=args.company, detail=entry, source="cli")
        _emit({"id": args.company, **entry})
        return 0
    if args.owner not in {u.name for u in users_of(root).list()}:
        raise library.TemplateAccessError(f"no such user: {args.owner}")
    library.clone(root, args.company, args.to)
    access.create(args.to, args.owner)
    audit.record(
        "cli", "template.clone", target=args.to, detail={"source": args.company}, source="cli"
    )
    _emit({"id": args.to, **(access.entry(args.to) or {})})
    return 0


def dispatch_project(args: argparse.Namespace, root: Path) -> int:
    store = open_project(root / "projects", args.project)
    templates = root / "templates"
    command: str = args.project_command
    if command == "coverage":
        _emit(library.project_coverage(store, templates, args.template).to_json())
        return 0
    if command == "reissue":
        path = library.reissue(store, templates, args.doc, args.version)
        _emit({"file": path.name, "set": get_config(store).company_id})
        return 0
    try:
        result = library.switch_template(
            store, templates, args.template, accept_gaps=args.accept_gaps
        )
    except library.CoverageGapError as exc:
        _emit({"error": str(exc), "coverage": exc.report.to_json()})
        return 1
    _emit(result.to_json())
    return 0
