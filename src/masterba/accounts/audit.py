"""Append-only audit log of administrative and security events (spec 24 section 2).

SQLite in `.masterba/audit.sqlite3`, beside the other account files and not in git. Nothing
here updates or deletes a row.
"""

import csv
import io
import json
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from masterba.accounts.usage import Clock, iso

# The first part of an action names its group; the dashboard filters by group.
GROUPS = ("auth", "user", "limits", "prices", "project", "job")
FORBIDDEN_KEYS = {"password", "hash", "salt"}
MAX_CSV_ROWS = 10_000


@dataclass(frozen=True)
class AuditFilter:
    actor: str | None = None
    action: str | None = None  # an exact action (`user.role`) or a group (`user`)
    target: str | None = None
    since: float | None = None


ALL = AuditFilter()


class AuditLog:
    def __init__(self, path: Path, clock: Clock = time.time) -> None:
        self._path = path
        self._clock = clock
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, actor TEXT NOT NULL,
                    action TEXT NOT NULL, target TEXT, project TEXT, detail TEXT, source TEXT
                );
                CREATE INDEX IF NOT EXISTS events_ts ON events (ts);
                """
            )

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self._path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def record(
        self,
        actor: str,
        action: str,
        *,
        target: str | None = None,
        project: str | None = None,
        detail: dict[str, Any] | None = None,
        source: str = "api",
    ) -> None:
        clean = {k: v for k, v in (detail or {}).items() if k not in FORBIDDEN_KEYS}
        with self._lock, self._db() as db:
            db.execute(
                "INSERT INTO events (ts, actor, action, target, project, detail, source) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    self._clock(),
                    actor,
                    action,
                    target,
                    project,
                    json.dumps(clean, ensure_ascii=False, sort_keys=True) if clean else None,
                    source,
                ),
            )

    @staticmethod
    def _where(found: AuditFilter, before: int | None) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        values: list[Any] = []
        if found.actor:
            clauses.append("actor = ?")
            values.append(found.actor)
        if found.action:
            if "." in found.action:
                clauses.append("action = ?")
                values.append(found.action)
            else:
                clauses.append("action LIKE ?")
                values.append(f"{found.action}.%")
        if found.target:
            clauses.append("(target = ? OR project = ?)")
            values.extend([found.target, found.target])
        if found.since is not None:
            clauses.append("ts >= ?")
            values.append(found.since)
        if before is not None:
            clauses.append("id < ?")
            values.append(before)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", values

    def query(
        self, found: AuditFilter = ALL, before: int | None = None, limit: int = 50
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Events newest first, and the cursor for the next page (None at the end)."""
        where, values = self._where(found, before)
        with self._db() as db:
            rows = db.execute(
                "SELECT id, ts, actor, action, target, project, detail, source FROM events"
                f"{where} ORDER BY id DESC LIMIT ?",
                [*values, limit + 1],
            ).fetchall()
        events = [self._json(row) for row in rows[:limit]]
        more = len(rows) > limit
        return events, (events[-1]["id"] if more and events else None)

    @staticmethod
    def _json(row: tuple[Any, ...]) -> dict[str, Any]:
        event_id, ts, actor, action, target, project, detail, source = row
        return {
            "id": event_id,
            "at": iso(ts),
            "actor": actor,
            "action": action,
            "target": target,
            "project_id": project,
            "detail": json.loads(detail) if detail else {},
            "source": source,
        }

    def csv(self, found: AuditFilter = ALL) -> str:
        events, _ = self.query(found, limit=MAX_CSV_ROWS)
        out = io.StringIO()
        writer = csv.writer(out)
        writer.writerow(["id", "at", "actor", "action", "target", "project_id", "source", "detail"])
        for e in events:
            detail = json.dumps(e["detail"], ensure_ascii=False) if e["detail"] else ""
            row = [e["id"], e["at"], e["actor"], e["action"], e["target"] or ""]
            row += [e["project_id"] or "", e["source"] or "", detail]
            # A spreadsheet must never run a cell as a formula.
            writer.writerow([_text(v) for v in row])
        return out.getvalue()

    def counts(self, since: float, until: float | None = None) -> dict[str, int]:
        """Events per action in a period."""
        query = "SELECT action, COUNT(*) FROM events WHERE ts >= ?"
        values: list[Any] = [since]
        if until is not None:
            query += " AND ts < ?"
            values.append(until)
        with self._db() as db:
            rows = db.execute(query + " GROUP BY action", values).fetchall()
        return {action: int(n) for action, n in rows}

    def actors(self, action: str, since: float) -> set[str]:
        with self._db() as db:
            rows = db.execute(
                "SELECT DISTINCT actor FROM events WHERE action = ? AND ts >= ?", (action, since)
            ).fetchall()
        return {r[0] for r in rows}


def _text(value: object) -> str:
    text = str(value)
    return f"'{text}" if text[:1] in {"=", "+", "-", "@", "\t", "\r"} else text
