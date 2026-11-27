"""`masterba user|access|audit ...`: accounts, limits, sharing and the audit log (spec 23, 24).

Every change made here is written to the audit log with actor `cli` (spec 24 section 2).
"""

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Any

from masterba.accounts import AuditFilter, AuditLog, Limits, LimitStore, ProjectAccess, UsageLedger
from masterba.accounts.access import PROJECT_ROLES
from masterba.api.auth import ROLES, AuthError, UserStore
from masterba.api.settings import settings_from_env


def _emit(data: dict[str, object]) -> None:
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _limit(raw: str) -> int | None:
    """A token count, or `none` for no limit."""
    if raw.lower() in {"none", "null", "unlimited"}:
        return None
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("a limit is 0 or more tokens")
    return value


def add_account_parsers(commands: Any) -> None:
    user = commands.add_parser("user", help="dashboard users, their usage and limits")
    users = user.add_subparsers(dest="user_command", required=True)
    add = users.add_parser("add")
    add.add_argument("name")
    add.add_argument("--role", choices=ROLES, required=True)
    add.add_argument("--password-stdin", action="store_true")
    users.add_parser("list")
    users.add_parser("remove").add_argument("name")
    role = users.add_parser("role", help="change the global role of a user")
    role.add_argument("name")
    role.add_argument("role", choices=ROLES)
    password = users.add_parser("password", help="set a new password")
    password.add_argument("name")
    password.add_argument("--password-stdin", action="store_true")
    limit = users.add_parser("limit", help="token limits of one user, or --default for all")
    limit.add_argument("name", nargs="?")
    limit.add_argument("--default", action="store_true", help="set the default limits")
    keep = argparse.SUPPRESS  # an option left out keeps the current value
    limit.add_argument("--session", type=_limit, default=keep, help="tokens per 5 hours, or none")
    limit.add_argument("--weekly", type=_limit, default=keep, help="tokens per 7 days, or none")
    limit.add_argument("--clear", action="store_true", help="return the user to the defaults")
    for action, text in (
        ("disable", "stop a user from signing in and end their sessions"),
        ("enable", "let a disabled user sign in again"),
        ("signout", "end every session of a user"),
    ):
        users.add_parser(action, help=text).add_argument("name")
    usage = users.add_parser("usage", help="usage windows of one user")
    usage.add_argument("name")
    usage.add_argument("--reset", action="store_true", help="start new windows now")

    access = commands.add_parser("access", help="who may open a project")
    actions = access.add_subparsers(dest="access_command", required=True)
    actions.add_parser("show").add_argument("project")
    owner = actions.add_parser("owner", help="hand a project to another user")
    owner.add_argument("project")
    owner.add_argument("name")
    share = actions.add_parser("share", help="add or change a member")
    share.add_argument("project")
    share.add_argument("name")
    share.add_argument("--role", choices=PROJECT_ROLES, default="viewer")
    unshare = actions.add_parser("unshare", help="remove a member")
    unshare.add_argument("project")
    unshare.add_argument("name")

    log = commands.add_parser("audit", help="administrative and sign-in events, newest first")
    log.add_argument("--actor")
    log.add_argument("--action", help="an action such as user.role, or a group such as user")
    log.add_argument("--target")
    log.add_argument("--limit", type=int, default=50)


def _password(from_stdin: bool) -> str:
    if from_stdin:
        return sys.stdin.readline().rstrip("\n")
    password = getpass.getpass("Password: ")
    if getpass.getpass("Repeat password: ") != password:
        raise AuthError("the passwords differ")
    return password


class _Accounts:
    def __init__(self, root: Path) -> None:
        settings = settings_from_env(root)
        self.users = UserStore(settings.state_dir / "users.json", settings.hash_iterations)
        self.limits = LimitStore(settings.state_dir / "limits.json")
        self.usage = UsageLedger(settings.state_dir / "usage.sqlite3", self.limits)
        self.access = ProjectAccess(
            settings.state_dir / "access.json", settings.projects, self.users.list
        )
        self.audit = AuditLog(settings.state_dir / "audit.sqlite3")

    def log(self, action: str, target: str | None = None, **detail: object) -> None:
        project = detail.pop("project", None)
        self.audit.record(
            "cli",
            action,
            target=target,
            project=str(project) if project else None,
            detail=detail,
            source="cli",
        )

    def known(self, name: str) -> None:
        if self.users.get(name) is None:
            raise AuthError(f"user {name} does not exist")


def dispatch_user(args: argparse.Namespace, root: Path) -> int:
    accounts = _Accounts(root)
    store = accounts.users
    command = args.user_command
    if command == "add":
        accounts.access.migrate()  # projects already there are not shared with the new user
        user = store.add(args.name, args.role, _password(args.password_stdin))
        accounts.log("user.create", user.name, role=user.role)
        _emit({"name": user.name, "role": user.role})
    elif command == "list":
        _emit(
            {
                "users": [
                    {"name": u.name, "role": u.role, "disabled": u.disabled} for u in store.list()
                ]
            }
        )
    elif command == "remove":
        store.remove(args.name)
        accounts.log("user.remove", args.name)
        _emit({"removed": args.name})
    elif command == "role":
        previous = store.get(args.name)
        user = store.set_role(args.name, args.role)
        accounts.log("user.role", user.name, old=previous.role if previous else None, new=user.role)
        _emit({"name": user.name, "role": user.role})
    elif command == "password":
        store.set_password(args.name, _password(args.password_stdin))
        store.end_sessions(args.name)
        accounts.log("user.password", args.name)
        _emit({"name": args.name, "password": "changed"})
    elif command in {"disable", "enable", "signout"}:
        accounts.known(args.name)
        if command == "signout":
            user = store.end_sessions(args.name)
        else:
            user = store.set_disabled(args.name, command == "disable")
        accounts.log(f"user.{command}", args.name)
        _emit({"name": user.name, "role": user.role, "disabled": user.disabled})
    elif command == "limit":
        return _limit_command(args, accounts)
    else:
        accounts.known(args.name)
        if args.reset:
            accounts.usage.reset(args.name)
            accounts.log("user.usage_reset", args.name)
        _emit(
            {
                "name": args.name,
                "limits": accounts.limits.effective(args.name).to_json(),
                "windows": [w.to_json() for w in accounts.usage.status(args.name)],
            }
        )
    return 0


def _limit_command(args: argparse.Namespace, accounts: _Accounts) -> int:
    if args.default == bool(args.name):
        raise ValueError("name one user or pass --default")
    if args.default:
        current = accounts.limits.default()
        accounts.limits.set_default(_merged(current, args))
        accounts.log("limits.default", limits=accounts.limits.default().to_json())
        _emit({"default": accounts.limits.default().to_json()})
        return 0
    accounts.known(args.name)
    if args.clear:
        accounts.limits.set_override(args.name, None)
    else:
        current = accounts.limits.effective(args.name)
        accounts.limits.set_override(args.name, _merged(current, args))
    override = accounts.limits.override(args.name)
    accounts.log("user.limits", args.name, limits=override.to_json() if override else "default")
    _emit({"name": args.name, "limits": accounts.limits.effective(args.name).to_json()})
    return 0


def _merged(current: Limits, args: argparse.Namespace) -> Limits:
    given = vars(args)
    return Limits(
        session=given.get("session", current.session),
        weekly=given.get("weekly", current.weekly),
    )


def dispatch_access(args: argparse.Namespace, root: Path) -> int:
    accounts = _Accounts(root)
    access = accounts.access
    pid: str = args.project
    if access.entry(pid) is None:
        raise ValueError(f"no project {pid} with an owner; add an admin user first")
    command = args.access_command
    if command == "owner":
        previous = (access.entry(pid) or {}).get("owner")
        access.set_owner(pid, args.name)
        accounts.log("project.owner", args.name, project=pid, previous=previous)
    elif command == "share":
        access.set_member(pid, args.name, args.role)
        accounts.log("project.member_set", args.name, project=pid, role=args.role)
    elif command == "unshare":
        access.remove_member(pid, args.name)
        accounts.log("project.member_remove", args.name, project=pid)
    _emit({"project_id": pid, **(access.entry(pid) or {})})
    return 0


def dispatch_audit(args: argparse.Namespace, root: Path) -> int:
    log = _Accounts(root).audit
    found = AuditFilter(actor=args.actor, action=args.action, target=args.target)
    events, _ = log.query(found, limit=max(1, min(args.limit, 1000)))
    _emit({"events": events})
    return 0
