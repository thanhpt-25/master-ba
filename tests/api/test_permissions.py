from typing import Any

import pytest

from api_support import ClientFor

RANK = {"viewer": 0, "approver": 1, "admin": 2}
P = "/api/projects/PRJ-001"
NEW_PROJECT = {"project_id": "PRJ-002", "company_id": "default"}
NEW_DR = {"trigger": "defect", "description": "Bug", "items": ["REQ-0001"]}
DECISION = {"decision": "ok"}
UPLOAD = {"file": ("note.txt", b"hello")}

# (method, path, request options, minimum role)
ROUTES: list[tuple[str, str, dict[str, Any], str]] = [
    ("GET", "/api/projects", {}, "viewer"),
    ("POST", "/api/projects", {"json": NEW_PROJECT}, "admin"),
    ("GET", P, {}, "viewer"),
    ("POST", f"{P}/intake", {"files": UPLOAD}, "approver"),
    ("POST", f"{P}/stages/brd/run", {"json": {}}, "approver"),
    ("GET", f"{P}/jobs", {}, "viewer"),
    ("GET", "/api/jobs/abc", {}, "viewer"),
    ("GET", f"{P}/documents", {}, "viewer"),
    ("GET", f"{P}/documents/DOC-SRS-0001", {}, "viewer"),
    ("GET", f"{P}/documents/DOC-SRS-0001/xlsx", {}, "viewer"),
    ("GET", f"{P}/documents/DOC-SRS-0001/diff?from=1&to=1", {}, "viewer"),
    ("GET", f"{P}/requirements", {}, "viewer"),
    ("GET", f"{P}/rtm/REQ-0001", {}, "viewer"),
    ("GET", f"{P}/links", {}, "viewer"),
    ("GET", f"{P}/impact?node=REQ-0001", {}, "viewer"),
    ("GET", f"{P}/runs", {}, "viewer"),
    ("GET", f"{P}/runs/RUN-0001", {}, "viewer"),
    ("GET", f"{P}/activity", {}, "viewer"),
    ("GET", f"{P}/drs", {}, "viewer"),
    ("POST", f"{P}/drs", {"json": NEW_DR}, "approver"),
    ("POST", f"{P}/drs/from-run", {"json": {"run_id": "RUN-0001"}}, "approver"),
    ("GET", f"{P}/drs/DR-0001", {}, "viewer"),
    ("POST", f"{P}/drs/DR-0001/approve", {"json": DECISION}, "approver"),
    ("POST", f"{P}/drs/DR-0001/reject", {"json": DECISION}, "approver"),
    ("POST", f"{P}/drs/DR-0001/close", {}, "approver"),
    ("POST", f"{P}/drs/DR-0001/propagate", {}, "approver"),
    ("GET", f"{P}/drs/DR-0001/diff", {}, "viewer"),
    ("GET", f"{P}/questions", {}, "viewer"),
    ("GET", f"{P}/questions/Q-0001", {}, "viewer"),
    ("POST", f"{P}/questions/Q-0001/answer", {"json": {"answer": "ok"}}, "approver"),
    ("POST", f"{P}/questions/Q-0001/withdraw", {}, "approver"),
    ("GET", "/api/me", {}, "viewer"),
]


@pytest.mark.parametrize(
    ("method", "path", "options", "minimum"),
    ROUTES,
    ids=[f"{m} {p.split('PRJ-001')[-1] or p}" for m, p, _, _ in ROUTES],
)
def test_every_route_enforces_its_minimum_role(
    seeded_client: ClientFor, method: str, path: str, options: dict[str, Any], minimum: str
) -> None:
    anonymous = seeded_client(None).request(method, path, **options)
    assert anonymous.status_code == 401, anonymous.text
    for role, rank in RANK.items():
        reply = seeded_client(role).request(method, path, **options)
        if rank < RANK[minimum]:
            assert reply.status_code == 403, f"{role}: {reply.text}"
        else:
            assert reply.status_code not in {401, 403}, f"{role}: {reply.text}"
            assert reply.status_code < 500, f"{role}: {reply.text}"


def test_a_viewer_can_read_everything_but_change_nothing(seeded_client: ClientFor) -> None:
    viewer = seeded_client("viewer")
    reads = [path for method, path, _, minimum in ROUTES if method == "GET" and minimum == "viewer"]
    assert reads
    writes = [(m, p, o) for m, p, o, minimum in ROUTES if m == "POST" and minimum != "viewer"]
    for method, path, options in writes:
        assert viewer.request(method, path, **options).status_code == 403, path
    assert viewer.get(f"{P}/documents").status_code == 200
    assert viewer.get(f"{P}/rtm/REQ-0001").status_code == 200


def test_only_an_admin_can_create_a_project(seeded_client: ClientFor) -> None:
    assert seeded_client("approver").post("/api/projects", json=NEW_PROJECT).status_code == 403
    created = seeded_client("admin").post("/api/projects", json=NEW_PROJECT)
    assert created.status_code == 201
    assert created.json()["project_id"] == "PRJ-002"
    assert seeded_client("admin").post("/api/projects", json=NEW_PROJECT).status_code == 400
