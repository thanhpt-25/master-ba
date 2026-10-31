import base64
import json
import stat
from pathlib import Path

import pytest
from fastapi import FastAPI

from api_support import PASSWORD, ROLE_NAMES, ClientFor
from masterba.api.auth import AuthError, LoginThrottle, SessionSigner, UserStore


def users(tmp_path: Path) -> UserStore:
    return UserStore(tmp_path / "state" / "users.json", iterations=1000)


def test_users_are_stored_with_a_salted_hash_and_private_permissions(tmp_path: Path) -> None:
    store = users(tmp_path)
    store.add("alice", "approver", PASSWORD)
    store.add("bob", "viewer", PASSWORD)
    path = tmp_path / "state" / "users.json"
    text = path.read_text("utf-8")
    assert PASSWORD not in text
    data = json.loads(text)["users"]
    assert data["alice"]["salt"] != data["bob"]["salt"]
    assert data["alice"]["hash"] != data["bob"]["hash"]
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_verify_accepts_the_right_password_only(tmp_path: Path) -> None:
    store = users(tmp_path)
    store.add("alice", "approver", PASSWORD)
    assert store.verify("alice", PASSWORD) is not None
    assert store.verify("alice", PASSWORD + "x") is None
    assert store.verify("nobody", PASSWORD) is None
    assert [(u.name, u.role) for u in store.list()] == [("alice", "approver")]


@pytest.mark.parametrize(
    ("name", "role", "password", "message"),
    [
        ("bad name", "viewer", PASSWORD, "user name"),
        ("", "viewer", PASSWORD, "user name"),
        ("carol", "owner", PASSWORD, "role must be one of"),
        ("carol", "viewer", "short", "at least 8"),
    ],
)
def test_invalid_users_are_rejected(
    tmp_path: Path, name: str, role: str, password: str, message: str
) -> None:
    with pytest.raises(AuthError, match=message):
        users(tmp_path).add(name, role, password)


def test_duplicates_and_removal(tmp_path: Path) -> None:
    store = users(tmp_path)
    store.add("alice", "viewer", PASSWORD)
    with pytest.raises(AuthError, match="already exists"):
        store.add("alice", "admin", PASSWORD)
    store.remove("alice")
    assert store.get("alice") is None
    with pytest.raises(AuthError, match="does not exist"):
        store.remove("alice")


def test_sessions_are_signed_expire_and_reject_tampering(tmp_path: Path) -> None:
    now = [1000.0]
    signer = SessionSigner(tmp_path / "secret", clock=lambda: now[0])
    token = signer.issue("alice", hours=8)
    assert signer.verify(token) == "alice"
    assert stat.S_IMODE((tmp_path / "secret").stat().st_mode) == 0o600
    payload, _, signature = token.partition(".")
    assert signer.verify(f"{payload}.{'0' * len(signature)}") is None
    mallory_payload, _, mallory_signature = signer.issue("mallory", 8).partition(".")
    forged = base64.urlsafe_b64encode(b"alice\n99999999999").decode("ascii")
    assert signer.verify(f"{forged}.{mallory_signature}") is None
    assert signer.verify(f"{mallory_payload}.{mallory_signature}") == "mallory"
    assert signer.verify("garbage") is None
    assert signer.verify("") is None
    other = SessionSigner(tmp_path / "other-secret", clock=lambda: now[0])
    assert other.verify(token) is None
    now[0] += 8 * 3600 + 1
    assert signer.verify(token) is None


def test_five_failures_lock_a_name_for_five_minutes() -> None:
    now = [0.0]
    throttle = LoginThrottle(clock=lambda: now[0])
    for _ in range(4):
        throttle.failure("alice")
    assert not throttle.locked("alice")
    throttle.failure("alice")
    assert throttle.locked("alice")
    assert not throttle.locked("bob")
    now[0] += 301
    assert not throttle.locked("alice")
    throttle.failure("alice")
    throttle.success("alice")
    assert not throttle.locked("alice")


def test_login_sets_a_strict_http_only_cookie(empty_client: ClientFor) -> None:
    client = empty_client(None)
    reply = client.post("/api/login", json={"name": "alice", "password": PASSWORD})
    assert reply.json() == {"name": "alice", "role": "approver"}
    cookie = reply.headers["set-cookie"].lower()
    assert "httponly" in cookie
    assert "samesite=strict" in cookie
    assert "path=/" in cookie
    assert client.get("/api/me").json() == {"name": "alice", "role": "approver"}


def test_failures_look_the_same_whether_or_not_the_name_exists(empty_client: ClientFor) -> None:
    client = empty_client(None)
    wrong = client.post("/api/login", json={"name": "alice", "password": "wrong password"})
    unknown = client.post("/api/login", json={"name": "ghost", "password": "wrong password"})
    assert (wrong.status_code, wrong.json()) == (unknown.status_code, unknown.json())
    assert wrong.status_code == 401


def test_a_locked_name_is_refused_even_with_the_right_password(empty_client: ClientFor) -> None:
    client = empty_client(None)
    for _ in range(5):
        client.post("/api/login", json={"name": "alice", "password": "wrong password"})
    locked = client.post("/api/login", json={"name": "alice", "password": PASSWORD})
    assert (locked.status_code, locked.json()) == (401, {"detail": "sign-in failed"})
    assert client.post("/api/login", json={"name": "vera", "password": PASSWORD}).status_code == 200


def test_roles_are_re_read_on_every_request(empty_client: ClientFor, empty_app: FastAPI) -> None:
    client = empty_client("approver")
    assert client.get("/api/me").json()["role"] == "approver"
    store = empty_app.state.masterba.users
    store.remove("alice")
    store.add("alice", "viewer", PASSWORD)
    assert client.get("/api/me").json()["role"] == "viewer"
    store.remove("alice")
    assert client.get("/api/me").status_code == 401


def test_logout_clears_the_session(empty_client: ClientFor) -> None:
    client = empty_client("viewer")
    assert client.post("/api/logout").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_a_tampered_cookie_is_rejected(empty_client: ClientFor) -> None:
    client = empty_client("admin")
    token = client.cookies.get("masterba_session")
    assert token is not None
    client.cookies.clear()
    client.cookies.set("masterba_session", token[:-3] + "abc")
    assert client.get("/api/me").status_code == 401


def test_state_changing_requests_need_the_csrf_header(empty_client: ClientFor) -> None:
    client = empty_client(None)
    body = {"name": "alice", "password": PASSWORD}
    bare = client.post("/api/login", json=body, headers={"X-MasterBA": ""})
    assert bare.status_code == 403
    assert client.post("/api/login", json=body).status_code == 200
    assert client.get("/api/me", headers={"X-MasterBA": ""}).status_code == 200


def test_every_role_name_in_the_fixture_can_sign_in(empty_client: ClientFor) -> None:
    for role, name in ROLE_NAMES.items():
        assert empty_client(role).get("/api/me").json() == {"name": name, "role": role}
