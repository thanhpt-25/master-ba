"""Spec 29 section 6.1: the set register, sharing, and a project's set over the API."""

import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import load_workbook

from api_support import REPO, ClientFor

P = "/api/projects/PRJ-001"
S = "/api/template-sets"


def _head(root: Path) -> str:
    done = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True)
    return done.stdout.strip()


@pytest.fixture
def with_sample(seeded_root: Path) -> Path:
    shutil.copytree(
        REPO / "templates" / "companies" / "sample-sier",
        seeded_root / "templates" / "companies" / "sample-sier",
        ignore=shutil.ignore_patterns("*.preview.xlsx"),
    )
    return seeded_root


def _ids(client) -> list[str]:  # type: ignore[no-untyped-def]
    reply = client.get(S)
    assert reply.status_code == 200, reply.text
    return [s["id"] for s in reply.json()]


def test_the_register_shows_what_each_user_may_see(
    with_sample: Path, seeded_client: ClientFor
) -> None:
    admin, approver, viewer = (seeded_client(r) for r in ("admin", "approver", "viewer"))
    assert seeded_client(None).get(S).status_code == 401

    assert _ids(viewer) == ["default", "sample-sier"]  # the sample becomes public
    clone = approver.post(f"{S}/sample-sier/clone", json={"target": "alice-co"})
    assert clone.status_code == 201, clone.text
    assert clone.json()["owner"] == "alice" and clone.json()["visibility"] == "private"
    assert viewer.post(f"{S}/sample-sier/clone", json={"target": "x"}).status_code == 403
    assert approver.post(f"{S}/sample-sier/clone", json={"target": "alice-co"}).status_code == 400

    assert _ids(viewer) == ["default", "sample-sier"]
    assert "alice-co" in _ids(admin)
    assert viewer.post(f"{S}/alice-co/visibility", json={"visibility": "public"}).status_code == 404
    assert admin.post(f"{S}/sample-sier/clone", json={"target": "default"}).status_code == 400

    shared = approver.post(
        f"{S}/alice-co/visibility", json={"visibility": "shared", "shared_with": ["vera"]}
    )
    assert shared.status_code == 200, shared.text
    assert shared.json()["shared_with"] == ["vera"]
    assert "alice-co" in _ids(viewer)
    shown = next(s for s in viewer.get(S).json() if s["id"] == "alice-co")
    assert shown["can_manage"] is False and "shared_with" not in shown
    assert viewer.post(f"{S}/alice-co/visibility", json={"visibility": "public"}).status_code == 403
    bad = approver.post(
        f"{S}/alice-co/visibility", json={"visibility": "shared", "shared_with": ["nobody"]}
    )
    assert bad.status_code == 400

    titled = approver.post(f"{S}/alice-co/title", json={"title": "Alice 標準"})
    assert titled.json()["title"] == "Alice 標準"
    assert approver.post(f"{S}/default/title", json={"title": "x"}).status_code == 403
    actions = {e["action"] for e in admin.get("/api/admin/audit").json()["events"]}
    assert {"template.clone", "template.visibility"} <= actions


def test_a_project_switches_set_after_seeing_the_gaps(
    with_sample: Path, seeded_client: ClientFor
) -> None:
    admin, viewer = seeded_client("admin"), seeded_client("viewer")

    shown = viewer.get(f"{P}/template").json()
    assert shown["current"] == "default" and shown["can_change"] is False
    assert [s["id"] for s in shown["sets"]] == ["default", "sample-sier"]
    assert all(d["kept"] is False for d in shown["documents"])

    report = viewer.get(f"{P}/template/coverage", params={"set": "sample-sier"}).json()
    assert report["gaps"] > 0
    assert viewer.get(f"{P}/template/coverage", params={"set": "ghost"}).status_code == 404

    before = _head(with_sample)
    preview = viewer.get(f"{P}/template/preview/DOC-BRD-0001.xlsx", params={"set": "sample-sier"})
    assert preview.status_code == 200
    assert "表紙" in load_workbook(BytesIO(preview.content)).sheetnames
    assert _head(with_sample) == before

    body = {"set": "sample-sier"}
    assert viewer.put(f"{P}/template", json=body).status_code == 403
    refused = admin.put(f"{P}/template", json=body)
    assert refused.status_code == 409 and refused.json()["coverage"]["gaps"] == report["gaps"]
    assert _head(with_sample) == before

    done = admin.put(f"{P}/template", json={**body, "accept_gaps": True})
    assert done.status_code == 200, done.text
    assert done.json()["rendered"] and done.json()["kept"] == []
    assert viewer.get(f"{P}/template").json()["current"] == "sample-sier"


def test_an_approved_version_downloads_as_issued_until_it_is_reissued(
    with_sample: Path, seeded_client: ClientFor
) -> None:
    from masterba.models.enums import DocStatus
    from masterba.trace_store import ProjectStore, set_document_status

    store = ProjectStore(with_sample / "projects", "PRJ-001")
    set_document_status(store, "DOC-BRD-0001", 1, DocStatus.APPROVED, "test: approve")
    admin, approver, viewer = (seeded_client(r) for r in ("admin", "approver", "viewer"))
    issued = (store.path / "xlsx" / "brd" / "DOC-BRD-0001.v1.xlsx").read_bytes()

    switched = admin.put(f"{P}/template", json={"set": "sample-sier", "accept_gaps": True})
    assert switched.json()["kept"] == ["DOC-BRD-0001 v1"]
    assert viewer.get(f"{P}/documents/DOC-BRD-0001/xlsx").content == issued

    assert viewer.post(f"{P}/documents/DOC-BRD-0001/reissue").status_code == 403
    assert approver.post(f"{P}/documents/DOC-SRS-0001/reissue").status_code == 400
    again = approver.post(f"{P}/documents/DOC-BRD-0001/reissue")
    assert again.status_code == 200, again.text
    assert viewer.get(f"{P}/documents/DOC-BRD-0001/xlsx").content != issued


def test_a_project_cannot_be_created_on_a_set_its_creator_cannot_see(
    with_sample: Path, seeded_client: ClientFor
) -> None:
    approver = seeded_client("approver")
    seeded_client("admin").post(f"{S}/sample-sier/visibility", json={"visibility": "private"})

    hidden = approver.post(
        "/api/projects", json={"project_id": "PRJ-002", "company_id": "sample-sier"}
    )
    assert hidden.status_code == 400
    plain = approver.post("/api/projects", json={"project_id": "PRJ-002"})
    assert plain.status_code == 201, plain.text
