"""Local users, password hashing, signed sessions and login throttling (spec 08 section 2).

Kept free of any web framework so another identity provider can replace it later.
"""

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

ROLES = ("viewer", "approver", "admin")
RANK = {role: n for n, role in enumerate(ROLES)}
NAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,40}$")
MIN_PASSWORD_LENGTH = 8
LOCK_AFTER_FAILURES = 5
LOCK_SECONDS = 300.0


class AuthError(ValueError):
    """Invalid user data (bad name, weak password, unknown role, duplicate)."""


@dataclass(frozen=True)
class User:
    name: str
    role: str


def _hash(password: str, salt: bytes, iterations: int) -> bytes:
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(text)
    tmp.replace(path)


class UserStore:
    """`users.json`: name -> role, salt, PBKDF2 hash and the iteration count used."""

    def __init__(self, path: Path, iterations: int = 600_000) -> None:
        self._path = path
        self._iterations = iterations

    def _load(self) -> dict[str, dict[str, object]]:
        if not self._path.exists():
            return {}
        data = json.loads(self._path.read_text("utf-8"))
        users: dict[str, dict[str, object]] = data["users"]
        return users

    def _save(self, users: dict[str, dict[str, object]]) -> None:
        _write_private(self._path, json.dumps({"users": users}, indent=2, sort_keys=True) + "\n")

    def add(self, name: str, role: str, password: str) -> User:
        if not NAME_PATTERN.match(name):
            raise AuthError("a user name has 1 to 40 letters, digits, dots, dashes or underscores")
        if role not in ROLES:
            raise AuthError(f"role must be one of {', '.join(ROLES)}")
        if len(password) < MIN_PASSWORD_LENGTH:
            raise AuthError(f"a password needs at least {MIN_PASSWORD_LENGTH} characters")
        users = self._load()
        if name in users:
            raise AuthError(f"user {name} already exists")
        salt = secrets.token_bytes(16)
        users[name] = {
            "role": role,
            "salt": salt.hex(),
            "hash": _hash(password, salt, self._iterations).hex(),
            "iterations": self._iterations,
        }
        self._save(users)
        return User(name, role)

    def get(self, name: str) -> User | None:
        entry = self._load().get(name)
        return User(name, str(entry["role"])) if entry else None

    def list(self) -> list[User]:
        return [User(n, str(e["role"])) for n, e in sorted(self._load().items())]

    def remove(self, name: str) -> None:
        users = self._load()
        if name not in users:
            raise AuthError(f"user {name} does not exist")
        del users[name]
        self._save(users)

    def verify(self, name: str, password: str) -> User | None:
        """The user when the password matches; unknown names cost the same work."""
        entry = self._load().get(name)
        if entry is None:
            _hash(password, b"\x00" * 16, self._iterations)
            return None
        salt = bytes.fromhex(str(entry["salt"]))
        expected = bytes.fromhex(str(entry["hash"]))
        actual = _hash(password, salt, int(str(entry["iterations"])))
        return User(name, str(entry["role"])) if hmac.compare_digest(actual, expected) else None


class SessionSigner:
    """Cookie values `base64(name\\nexpiry).hmac`, signed with a secret kept in a 0600 file."""

    def __init__(self, secret_path: Path, clock: Callable[[], float] = time.time) -> None:
        if not secret_path.exists():
            _write_private(secret_path, secrets.token_hex(32))
        self._secret = secret_path.read_text("utf-8").strip().encode("utf-8")
        self._clock = clock

    def _sign(self, payload: bytes) -> str:
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def issue(self, name: str, hours: int) -> str:
        expiry = int(self._clock() + hours * 3600)
        payload = base64.urlsafe_b64encode(f"{name}\n{expiry}".encode()).decode("ascii")
        return f"{payload}.{self._sign(payload.encode('ascii'))}"

    def verify(self, token: str) -> str | None:
        payload, _, signature = token.partition(".")
        if not payload or not hmac.compare_digest(
            signature, self._sign(payload.encode("ascii", "ignore"))
        ):
            return None
        try:
            name, expiry = base64.urlsafe_b64decode(payload.encode("ascii")).decode().split("\n")
        except (ValueError, UnicodeError):
            return None
        return name if int(expiry) > self._clock() else None


class LoginThrottle:
    """Five failures within five minutes lock a name for five minutes (in memory)."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._failures: dict[str, list[float]] = {}

    def locked(self, name: str) -> bool:
        now = self._clock()
        recent = [t for t in self._failures.get(name, []) if now - t < LOCK_SECONDS]
        self._failures[name] = recent
        return len(recent) >= LOCK_AFTER_FAILURES

    def failure(self, name: str) -> None:
        self._failures.setdefault(name, []).append(self._clock())

    def success(self, name: str) -> None:
        self._failures.pop(name, None)
