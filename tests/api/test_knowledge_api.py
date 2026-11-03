"""Knowledge API routes (spec 12, Requirement 14)."""

import subprocess

import pytest
from fastapi.testclient import TestClient

from api_support import ClientFor
from masterba.knowledge import indexer

P = "/api/projects/PRJ-001/knowledge"
GLOSSARY = ("glossary.md", "# 用語\n受注とは注文を受けること。".encode(), "text/markdown")


@pytest.fixture(autouse=True)
def keyword_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(indexer, "rag_available", lambda: False)


def test_roles_and_full_cycle(seeded_client: ClientFor) -> None:
    viewer, approver = seeded_client("viewer"), seeded_client("approver")
    assert viewer.get(P).json() == []
    assert viewer.post(P, files={"file": GLOSSARY}).status_code == 403
    added = approver.post(P, files={"file": GLOSSARY}, data={"added_by": "mallory"})
    assert added.status_code == 201, added.text
    body = added.json()
    me = approver.get("/api/me").json()["name"]
    assert (body["id"], body["status"], body["added_by"]) == ("KB-0001", "indexed", me)
    assert [s["id"] for s in viewer.get(P).json()] == ["KB-0001"]
    found = viewer.get(f"{P}/search", params={"q": "受注", "k": 3}).json()
    assert found["mode"] == "keyword"
    assert [p["chunk_ref"] for p in found["passages"]] == ["KB-0001#chunk.1"]
    assert viewer.put(f"{P}/KB-0001", files={"file": GLOSSARY}).status_code == 403
    new = ("g2.md", "受注 改訂".encode(), "text/markdown")
    replaced = approver.put(f"{P}/KB-0001", files={"file": new})
    assert replaced.status_code == 200 and replaced.json()["file_name"] == "g2.md"
    assert replaced.json()["dr_id"] is None
    assert viewer.delete(f"{P}/KB-0001").status_code == 403
    removed = approver.delete(f"{P}/KB-0001")
    assert removed.status_code == 200 and removed.json()["removed"] is True
    assert viewer.get(P).json() == []


def test_one_commit_with_only_the_manifest(seeded_client: ClientFor, seeded_root: object) -> None:
    approver = seeded_client("approver")
    approver.post(P, files={"file": GLOSSARY})
    out = subprocess.run(
        ["git", "show", "--name-only", "--format=%s", "HEAD"],
        cwd=str(seeded_root),
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    assert out[:3] == ["kb(PRJ-001):", "add", "KB-0001"]
    assert out[3:] == ["projects/PRJ-001/knowledge/manifest.json"]


def test_errors(seeded_client: ClientFor) -> None:
    approver = seeded_client("approver")
    refused = approver.post(P, files={"file": ("x.csv", b"a,b", "text/csv")})
    assert refused.status_code == 400 and "not supported" in refused.json()["detail"]
    approver.post(P, files={"file": GLOSSARY})
    dup = approver.post(P, files={"file": ("again.md", GLOSSARY[1], "text/markdown")})
    assert dup.status_code == 400 and "KB-0001" in dup.json()["detail"]
    missing = approver.delete(f"{P}/KB-0042")
    assert missing.status_code == 404 and "KB-0042" in missing.json()["detail"]
    assert approver.delete(f"{P}/bad-id").status_code == 404
    assert approver.get("/api/projects/PRJ-404/knowledge").status_code == 404
    cases: list[dict[str, str | int]] = [{"q": " "}, {"q": "受注", "k": 51}, {"q": "x" * 1001}]
    for params in cases:
        reply = approver.get(f"{P}/search", params=params)
        assert reply.status_code == 400 and "invalid" in reply.json()["detail"]


def test_search_without_an_index_is_409(seeded_client: ClientFor) -> None:
    reply = seeded_client("viewer").get(f"{P}/search", params={"q": "受注"})
    assert reply.status_code == 409 and "kb reindex" in reply.json()["detail"]


def test_signed_out_and_missing_header(seeded_client: ClientFor, seeded_app: object) -> None:
    anonymous = seeded_client(None)
    assert anonymous.get(P).status_code == 401
    assert anonymous.post(P, files={"file": GLOSSARY}).status_code == 401
    bare = TestClient(seeded_app)  # type: ignore[arg-type]
    assert bare.post(P, files={"file": GLOSSARY}).status_code == 403  # design open point 3
    approver = seeded_client("approver")
    approver.headers.pop("X-MasterBA")
    assert approver.delete(f"{P}/KB-0001").status_code == 403
