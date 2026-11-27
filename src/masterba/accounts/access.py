"""Project ownership and sharing in `.masterba/access.json` (spec 23 sections 1 to 4)."""

import json
import os
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any, Protocol

PROJECT_ROLES = ("viewer", "approver")
GLOB = "PRJ-???"


class AccessError(ValueError):
    """A sharing change that cannot be made (unknown user, bad role, the owner as member)."""


class Account(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def role(self) -> str: ...


Accounts = Callable[[], Sequence[Account]]


class ProjectAccess:
    """Owner and members per project; a missing file migrates the projects already there."""

    def __init__(self, path: Path, projects: Path, accounts: Accounts) -> None:
        self._path = path
        self._projects = projects
        self._accounts = accounts
        self._lock = threading.RLock()

    # -- storage -----------------------------------------------------------------

    def _existing(self) -> list[str]:
        if not self._projects.exists():
            return []
        return sorted(p.name for p in self._projects.glob(GLOB) if (p / "project.json").exists())

    def _first_admin(self) -> str | None:
        admins = sorted(a.name for a in self._accounts() if a.role == "admin")
        return admins[0] if admins else None

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True) + "\n")
        tmp.replace(self._path)

    def _load(self) -> dict[str, Any]:
        """The access data, with every project on disk given an entry (and saved if new)."""
        with self._lock:
            first_time = not self._path.exists()
            if first_time:
                data: dict[str, Any] = {"version": 1, "projects": {}}
            else:
                data = json.loads(self._path.read_text("utf-8"))
            projects: dict[str, Any] = data.setdefault("projects", {})
            missing = [pid for pid in self._existing() if pid not in projects]
            if not missing:
                return data
            owner = self._first_admin()
            if owner is None:
                # Nobody to give the projects to yet; try again once an admin exists.
                return data
            members = (
                {a.name: a.role for a in self._accounts() if a.name != owner and a.role != "admin"}
                if first_time
                else {}
            )
            for pid in missing:
                projects[pid] = {"owner": owner, "members": dict(members)}
            self._save(data)
            return data

    def migrate(self) -> None:
        """Give every project without an entry an owner now (server start, `user add`)."""
        self._load()

    def _update(self, change: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            data = self._load()
            change(data["projects"])
            self._save(data)

    # -- reading -----------------------------------------------------------------

    def entry(self, project_id: str) -> dict[str, Any] | None:
        found: dict[str, Any] | None = self._load()["projects"].get(project_id)
        return found

    def role_of(self, project_id: str, account: Account) -> str | None:
        """The project role: admin for the owner and global admins, the member role, or None."""
        if account.role == "admin":
            return "admin" if (self._projects / project_id / "project.json").exists() else None
        entry = self.entry(project_id)
        if entry is None:
            return None
        if entry.get("owner") == account.name:
            return "admin"
        role = entry.get("members", {}).get(account.name)
        return str(role) if role in PROJECT_ROLES else None

    def visible(self, account: Account) -> list[str]:
        data = self._load()["projects"]
        return [pid for pid in self._existing() if self._sees(data.get(pid), account)]

    @staticmethod
    def _sees(entry: dict[str, Any] | None, account: Account) -> bool:
        if account.role == "admin":
            return True
        if entry is None:
            return False
        return entry.get("owner") == account.name or account.name in entry.get("members", {})

    # -- changing ----------------------------------------------------------------

    def _known(self, name: str) -> None:
        if name not in {a.name for a in self._accounts()}:
            raise AccessError(f"user {name} does not exist")

    def create(self, project_id: str, owner: str) -> None:
        def change(projects: dict[str, Any]) -> None:
            projects[project_id] = {"owner": owner, "members": {}}

        self._update(change)

    def set_member(self, project_id: str, name: str, role: str) -> None:
        if role not in PROJECT_ROLES:
            raise AccessError(f"a member role is one of {', '.join(PROJECT_ROLES)}")
        self._known(name)

        def change(projects: dict[str, Any]) -> None:
            entry = projects[project_id]
            if entry.get("owner") == name:
                raise AccessError(f"{name} owns {project_id}")
            entry.setdefault("members", {})[name] = role

        self._update(change)

    def remove_member(self, project_id: str, name: str) -> None:
        def change(projects: dict[str, Any]) -> None:
            members = projects[project_id].setdefault("members", {})
            if name not in members:
                raise AccessError(f"{name} is not a member of {project_id}")
            del members[name]

        self._update(change)

    def set_owner(self, project_id: str, name: str) -> None:
        """Hand a project over; the previous owner stays as an approver member."""
        self._known(name)

        def change(projects: dict[str, Any]) -> None:
            entry = projects[project_id]
            previous = entry.get("owner")
            members = entry.setdefault("members", {})
            members.pop(name, None)
            if previous and previous != name:
                members[previous] = "approver"
            entry["owner"] = name

        self._update(change)

    def forget_user(self, name: str, heir: str) -> None:
        """A removed user's projects go to `heir`; their memberships are dropped."""

        def change(projects: dict[str, Any]) -> None:
            for entry in projects.values():
                entry.setdefault("members", {}).pop(name, None)
                if entry.get("owner") == name:
                    entry["owner"] = heir
                    entry["members"].pop(heir, None)

        self._update(change)
