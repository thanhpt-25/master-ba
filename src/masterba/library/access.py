"""Owner and sharing of template sets in `.masterba/template_access.json` (spec 29 section 1.2)."""

import json
import os
import threading
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from masterba.accounts.access import Account, Accounts
from masterba.guard.templates import set_findings
from masterba.rendering.template import DEFAULT_COMPANY

VISIBILITIES = ("private", "shared", "public")
PUBLIC_SAMPLE = "sample-sier"
PUBLIC_SAMPLE_TITLE = "Mẫu SIer (dữ liệu giả)"
MAX_TITLE = 80


class TemplateAccessError(ValueError):
    """A sharing change that cannot be made (unknown user or set, bad visibility)."""


class TemplateAccess:
    """Who owns, sees and manages each company template set; `default` is seen by everyone."""

    def __init__(self, path: Path, templates: Path, accounts: Accounts) -> None:
        self._path = path
        self._companies = templates / "companies"
        self._accounts = accounts
        self._lock = threading.RLock()

    # -- storage -----------------------------------------------------------------

    def existing(self) -> list[str]:
        """Every company set folder on disk."""
        if not self._companies.exists():
            return []
        return sorted(p.name for p in self._companies.iterdir() if p.is_dir())

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        tmp.replace(self._path)

    def _load(self) -> dict[str, Any]:
        """The access data, with every set on disk given an entry (and saved if new)."""
        with self._lock:
            if self._path.exists():
                data: dict[str, Any] = json.loads(self._path.read_text("utf-8"))
            else:
                data = {"version": 1, "sets": {}}
            sets: dict[str, Any] = data.setdefault("sets", {})
            missing = [s for s in self.existing() if s not in sets]
            if not missing:
                return data
            admins = sorted(a.name for a in self._accounts() if a.role == "admin")
            if not admins:
                return data
            for set_id in missing:
                public = set_id == PUBLIC_SAMPLE
                sets[set_id] = {
                    "owner": admins[0],
                    "visibility": "public" if public else "private",
                    "shared_with": [],
                    "title": PUBLIC_SAMPLE_TITLE if public else None,
                }
            self._save(data)
            return data

    def migrate(self) -> None:
        self._load()

    def _update(self, change: Callable[[dict[str, Any]], None]) -> None:
        with self._lock:
            data = self._load()
            change(data["sets"])
            self._save(data)

    # -- reading -----------------------------------------------------------------

    def entry(self, set_id: str) -> dict[str, Any] | None:
        if set_id == DEFAULT_COMPANY:
            return None
        found: dict[str, Any] | None = self._load()["sets"].get(set_id)
        return found

    def sees(self, set_id: str, account: Account) -> bool:
        if set_id == DEFAULT_COMPANY:
            return True
        if set_id not in self.existing():
            return False
        if account.role == "admin":
            return True
        entry = self.entry(set_id)
        if entry is None:
            return False
        if entry.get("owner") == account.name or entry.get("visibility") == "public":
            return True
        return entry.get("visibility") == "shared" and account.name in entry.get("shared_with", [])

    def manages(self, set_id: str, account: Account) -> bool:
        if set_id == DEFAULT_COMPANY or set_id not in self.existing():
            return False
        if account.role == "admin":
            return True
        entry = self.entry(set_id)
        return entry is not None and entry.get("owner") == account.name

    def visible(self, account: Account) -> list[str]:
        """The sets `account` may pick, the built-in set first."""
        return [DEFAULT_COMPANY, *(s for s in self.existing() if self.sees(s, account))]

    # -- changing ----------------------------------------------------------------

    def _known(self, names: Iterable[str]) -> list[str]:
        accounts = {a.name for a in self._accounts()}
        wanted = sorted(dict.fromkeys(n.strip() for n in names if n.strip()))
        unknown = [n for n in wanted if n not in accounts]
        if unknown:
            raise TemplateAccessError(f"no such user: {', '.join(unknown)}")
        return wanted

    def _entry_of(self, sets: dict[str, Any], set_id: str) -> dict[str, Any]:
        if set_id not in sets:
            raise TemplateAccessError(f"no template set {set_id}")
        entry: dict[str, Any] = sets[set_id]
        return entry

    def create(self, set_id: str, owner: str, title: str | None = None) -> None:
        """A new private set owned by `owner` (a calibration or a clone)."""

        def change(sets: dict[str, Any]) -> None:
            sets[set_id] = {
                "owner": owner,
                "visibility": "private",
                "shared_with": [],
                "title": title,
            }

        self._update(change)

    def set_visibility(
        self, set_id: str, visibility: str, shared_with: Iterable[str] | None = None
    ) -> dict[str, Any]:
        if visibility not in VISIBILITIES:
            raise TemplateAccessError(f"visibility is one of {', '.join(VISIBILITIES)}")
        names = self._known(shared_with or []) if visibility == "shared" else None
        if visibility != "private" and set_id != DEFAULT_COMPANY:
            # Spec 30 section 5: a set that shows personal data or a secret stays private.
            found = set_findings(self._companies / set_id)
            if found:
                shown = "; ".join(f.text() for f in found[:3])
                more = f" and {len(found) - 3} more" if len(found) > 3 else ""
                raise TemplateAccessError(
                    f"the set holds personal data or a secret ({shown}{more}); "
                    "remove it from the template before sharing"
                )

        def change(sets: dict[str, Any]) -> None:
            entry = self._entry_of(sets, set_id)
            entry["visibility"] = visibility
            if names is not None:
                entry["shared_with"] = [n for n in names if n != entry.get("owner")]

        self._update(change)
        return self.entry(set_id) or {}

    def downgrade_unsafe(self) -> list[str]:
        """Make every shared or public set with findings private (spec 30 section 5)."""
        with self._lock:
            sets = self._load().get("sets", {})
            unsafe = [
                set_id
                for set_id, entry in sets.items()
                if entry.get("visibility", "private") != "private"
                and set_findings(self._companies / set_id)
            ]
            if unsafe:

                def change(data: dict[str, Any]) -> None:
                    for set_id in unsafe:
                        data[set_id]["visibility"] = "private"

                self._update(change)
        return unsafe

    def set_title(self, set_id: str, title: str | None) -> None:
        clean = (title or "").strip() or None
        if clean is not None and len(clean) > MAX_TITLE:
            raise TemplateAccessError(f"a title has at most {MAX_TITLE} characters")

        def change(sets: dict[str, Any]) -> None:
            self._entry_of(sets, set_id)["title"] = clean

        self._update(change)

    def forget_user(self, name: str, heir: str) -> None:
        """A removed user's sets go to `heir`; they are dropped from every share list."""

        def change(sets: dict[str, Any]) -> None:
            for entry in sets.values():
                entry["shared_with"] = [n for n in entry.get("shared_with", []) if n != name]
                if entry.get("owner") == name:
                    entry["owner"] = heir
                    entry["shared_with"] = [n for n in entry["shared_with"] if n != heir]

        self._update(change)
