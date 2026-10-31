import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_support import PASSWORD, ClientFor
from masterba.api import routes_docs

P = "/api/projects/PRJ-001"


@pytest.mark.parametrize(
    "path",
    [
        "/api/projects/%2e%2e",
        "/api/projects/PRJ-001%2f..%2f..",
        "/api/projects/PRJ-1",
        "/api/projects/PRJ-999",
        f"{P}/documents/DOC-X",
        f"{P}/documents/..%2f..%2fproject.json",
        f"{P}/documents/DOC-SRS-0009",
        f"{P}/runs/RUN-1",
        f"{P}/drs/DR-1",
        f"{P}/rtm/REQ-1",
        f"{P}/impact?node=../../etc/passwd",
    ],
)
def test_malformed_or_hostile_ids_are_rejected_as_not_found(
    seeded_client: ClientFor, path: str
) -> None:
    reply = seeded_client("admin").get(path)
    assert reply.status_code == 404, reply.text
    assert reply.headers["content-type"].startswith("application/json")


@pytest.mark.parametrize(
    "name", ["../evil.txt", "a/b.txt", "note.docx", ".hidden.txt", "x" * 80 + ".txt", ""]
)
def test_upload_names_must_be_plain_text_file_names(
    seeded_client: ClientFor, seeded_app: FastAPI, name: str
) -> None:
    reply = seeded_client("approver").post(f"{P}/intake", files={"file": (name, b"hello")})
    assert reply.status_code in {400, 422}
    uploads = seeded_app.state.masterba.settings.uploads_dir
    assert not uploads.exists() or not list(uploads.rglob("*.*"))
    assert not list(seeded_app.state.masterba.settings.root.glob("evil*"))


def test_uploads_must_be_utf8_and_not_too_long(seeded_client: ClientFor) -> None:
    approver = seeded_client("approver")
    bad = approver.post(f"{P}/intake", files={"file": ("a.txt", b"\xff\xfe\x00bad")})
    assert (bad.status_code, bad.json()["detail"]) == (400, "the file must be UTF-8 text")
    big = approver.post(f"{P}/intake", files={"file": ("big.txt", b"x" * 200_001)})
    assert big.status_code == 400
    assert "longer than" in big.json()["detail"]
    ok = approver.post(f"{P}/intake", files={"file": ("ok.md", "要件\n".encode())})
    assert (ok.status_code, ok.json()) == (201, {"name": "ok.md"})


def test_a_hostile_dr_item_is_a_clean_error(seeded_client: ClientFor) -> None:
    reply = seeded_client("approver").post(
        f"{P}/drs",
        json={"trigger": "defect", "description": "x", "items": ["../../etc/passwd"]},
    )
    assert reply.status_code in {404, 422}


def test_unknown_fields_in_a_body_are_rejected(seeded_client: ClientFor) -> None:
    reply = seeded_client("admin").post(
        "/api/projects", json={"project_id": "PRJ-003", "role": "admin"}
    )
    assert reply.status_code == 422


def test_security_headers_are_on_every_response(seeded_client: ClientFor) -> None:
    client = seeded_client("viewer")
    for path in ("/", "/api/me", "/api/nothing", f"{P}/documents"):
        headers = client.get(path).headers
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["x-frame-options"] == "DENY"
        assert headers["referrer-policy"] == "same-origin"
        csp = headers["content-security-policy"]
        assert "default-src 'self'" in csp
        assert "unsafe-inline" not in csp
        assert "frame-ancestors 'none'" in csp


def test_the_web_app_is_served_and_unknown_api_paths_are_json_404(
    seeded_client: ClientFor,
) -> None:
    client = seeded_client(None)
    home = client.get("/")
    assert home.status_code == 200
    assert "MasterBA test" in home.text
    unknown = client.get("/api/nothing/here")
    assert (unknown.status_code, unknown.json()) == (404, {"detail": "no such endpoint"})
    assert client.post("/api/nothing").status_code == 404


def test_unexpected_errors_do_not_leak_details(
    seeded_app: FastAPI, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("secret path /home/x")

    monkeypatch.setattr(routes_docs, "run_summaries", boom)
    client = TestClient(seeded_app, raise_server_exceptions=False, headers={"X-MasterBA": "1"})
    client.post("/api/login", json={"name": "vera", "password": PASSWORD})
    reply = client.get(f"{P}/runs")
    assert (reply.status_code, reply.json()) == (500, {"detail": "internal error"})
    assert "secret" not in reply.text


def test_health_needs_no_login_and_shows_no_project_data(seeded_client: ClientFor) -> None:
    reply = seeded_client(None).get("/api/health")
    assert reply.status_code == 200
    assert reply.json()["status"] == "ok"
    assert set(reply.json()) == {"status", "version"}
