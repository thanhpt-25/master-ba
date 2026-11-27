"""Per-user token ledger and Claude-like usage windows (spec 23 sections 5 to 7).

A window starts with the first call after the previous one ended and resets `length` seconds
later. The ledger is SQLite so that job threads can append at the same time.
"""

import json
import os
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from masterba.llm import UsageLimitError

WINDOWS: tuple[tuple[str, float], ...] = (("session", 5 * 3600.0), ("weekly", 7 * 86400.0))
WINDOW_NAMES = tuple(name for name, _ in WINDOWS)
ENV = {"session": "MASTERBA_LIMIT_SESSION_TOKENS", "weekly": "MASTERBA_LIMIT_WEEKLY_TOKENS"}
Clock = Callable[[], float]


def iso(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


@dataclass(frozen=True)
class Limits:
    session: int | None = None
    weekly: int | None = None

    def of(self, window: str) -> int | None:
        value: int | None = getattr(self, window)
        return value

    def to_json(self) -> dict[str, int | None]:
        return {"session": self.session, "weekly": self.weekly}

    @classmethod
    def from_json(cls, data: dict[str, Any] | None) -> "Limits":
        data = data or {}
        values: dict[str, int | None] = {}
        for name in WINDOW_NAMES:
            raw = data.get(name)
            if raw is not None and (not isinstance(raw, int) or isinstance(raw, bool) or raw < 0):
                raise ValueError(f"{name} limit must be a whole number of tokens or null")
            values[name] = raw
        return cls(**values)


@dataclass(frozen=True)
class WindowStatus:
    window: str
    used: int
    limit: int | None
    started: float | None
    resets_at: float | None

    @property
    def reached(self) -> bool:
        return self.limit is not None and self.used >= self.limit

    @property
    def percent(self) -> int | None:
        if self.limit is None:
            return None
        if self.limit == 0:
            return 100
        return min(100, round(self.used * 100 / self.limit))

    def to_json(self) -> dict[str, Any]:
        return {
            "window": self.window,
            "used": self.used,
            "limit": self.limit,
            "percent": self.percent,
            "reached": self.reached,
            "started": iso(self.started),
            "resets_at": iso(self.resets_at),
        }

    def message(self) -> str:
        label = "5-hour" if self.window == "session" else "weekly"
        if self.resets_at is None:
            return f"your {label} usage limit is {self.limit} tokens; ask an administrator"
        return (
            f"usage limit reached: {self.used}/{self.limit} tokens in your {label} window; "
            f"it resets at {iso(self.resets_at)}"
        )


def _env_limit(window: str) -> int | None:
    raw = os.environ.get(ENV[window], "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{ENV[window]} must be a whole number, got {raw!r}") from exc
    return max(value, 0)


class LimitStore:
    """`.masterba/limits.json`: `default` limits and per-user `users` overrides."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._lock = threading.Lock()

    def _load(self) -> dict[str, Any]:
        if not self._path.exists():
            return {}
        data: dict[str, Any] = json.loads(self._path.read_text("utf-8"))
        return data

    def _save(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", "utf-8")
        tmp.replace(self._path)

    def default(self) -> Limits:
        data = self._load()
        if "default" in data:
            return Limits.from_json(data["default"])
        return Limits(**{name: _env_limit(name) for name in WINDOW_NAMES})

    def set_default(self, limits: Limits) -> None:
        with self._lock:
            data = self._load()
            data["default"] = limits.to_json()
            self._save(data)

    def override(self, user: str) -> Limits | None:
        found = self._load().get("users", {}).get(user)
        return Limits.from_json(found) if found is not None else None

    def set_override(self, user: str, limits: Limits | None) -> None:
        with self._lock:
            data = self._load()
            users = data.setdefault("users", {})
            if limits is None:
                users.pop(user, None)
            else:
                users[user] = limits.to_json()
            self._save(data)

    def effective(self, user: str) -> Limits:
        return self.override(user) or self.default()


class UsageLedger:
    """`.masterba/usage.sqlite3`: one row per model call and the start of each user's windows."""

    def __init__(self, path: Path, limits: LimitStore, clock: Clock = time.time) -> None:
        self._path = path
        self.limits = limits
        self._clock = clock
        self._lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS calls (
                    ts REAL NOT NULL, user TEXT NOT NULL, project TEXT, kind TEXT,
                    model TEXT, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL
                );
                CREATE INDEX IF NOT EXISTS calls_user_ts ON calls (user, ts);
                CREATE TABLE IF NOT EXISTS windows (
                    user TEXT NOT NULL, window TEXT NOT NULL, start REAL NOT NULL,
                    PRIMARY KEY (user, window)
                );
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
        user: str,
        *,
        project: str | None,
        kind: str | None,
        model: str | None,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        now = self._clock()
        with self._lock, self._db() as db:
            for name, length in WINDOWS:
                row = db.execute(
                    "SELECT start FROM windows WHERE user = ? AND window = ?", (user, name)
                ).fetchone()
                if row is None or now >= row[0] + length:
                    db.execute(
                        "INSERT OR REPLACE INTO windows (user, window, start) VALUES (?, ?, ?)",
                        (user, name, now),
                    )
            db.execute(
                "INSERT INTO calls VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now, user, project, kind, model, input_tokens, output_tokens),
            )

    def status(self, user: str) -> list[WindowStatus]:
        now = self._clock()
        limits = self.limits.effective(user)
        found = []
        with self._db() as db:
            for name, length in WINDOWS:
                row = db.execute(
                    "SELECT start FROM windows WHERE user = ? AND window = ?", (user, name)
                ).fetchone()
                start = row[0] if row is not None and now < row[0] + length else None
                used = 0
                if start is not None:
                    total = db.execute(
                        "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) FROM calls "
                        "WHERE user = ? AND ts >= ?",
                        (user, start),
                    ).fetchone()
                    used = int(total[0])
                resets = start + length if start is not None else None
                found.append(WindowStatus(name, used, limits.of(name), start, resets))
        return found

    def blocking(self, user: str) -> WindowStatus | None:
        """The first window whose limit is reached, if any."""
        return next((w for w in self.status(user) if w.reached), None)

    def check(self, user: str) -> None:
        reached = self.blocking(user)
        if reached is not None:
            raise UsageLimitError(reached.message())

    def reset(self, user: str) -> None:
        with self._lock, self._db() as db:
            db.execute("DELETE FROM windows WHERE user = ?", (user,))

    def by_project(self, user: str, days: int = 7) -> list[dict[str, Any]]:
        since = self._clock() - days * 86400
        with self._db() as db:
            rows = db.execute(
                "SELECT project, COUNT(*), SUM(input_tokens), SUM(output_tokens) FROM calls "
                "WHERE user = ? AND ts >= ? GROUP BY project ORDER BY SUM(input_tokens + "
                "output_tokens) DESC",
                (user, since),
            ).fetchall()
        return [
            {
                "project_id": project,
                "calls": calls,
                "input_tokens": int(inp),
                "output_tokens": int(out),
                "tokens": int(inp) + int(out),
            }
            for project, calls, inp, out in rows
        ]

    def recent(self, user: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute(
                "SELECT ts, project, kind, model, input_tokens, output_tokens FROM calls "
                "WHERE user = ? ORDER BY ts DESC LIMIT ?",
                (user, limit),
            ).fetchall()
        return [
            {
                "at": iso(ts),
                "project_id": project,
                "kind": kind,
                "model": model,
                "input_tokens": inp,
                "output_tokens": out,
            }
            for ts, project, kind, model, inp, out in rows
        ]


@dataclass(frozen=True)
class UserMeter:
    """The `Meter` of one job: checks and charges the user who started it."""

    ledger: UsageLedger
    user: str
    project: str | None
    kind: str | None

    def check(self) -> None:
        self.ledger.check(self.user)

    def record(self, model: str, input_tokens: int, output_tokens: int) -> None:
        self.ledger.record(
            self.user,
            project=self.project,
            kind=self.kind,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
