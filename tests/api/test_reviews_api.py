"""Phase review routes (spec 15 section 7)."""

from fastapi import FastAPI

from api_support import ClientFor, Script, wait_for
from factories import draft_for, intake_path, qa_pass
from masterba.change import PatchOp, RevisionPatch

LOGIN = "login_system.txt"
P = "/api/projects/PRJ-001"
BRD = "DOC-BRD-0001"


def brd_in_review(app: FastAPI, client: ClientFor, script: Script) -> None:
    admin, approver = client("admin"), client("approver")
    new = {"project_id": "PRJ-001", "document_language": "en"}
    assert admin.post("/api/projects", json=new).json()["review_gates"]
    approver.post(f"{P}/intake", files={"file": (LOGIN, intake_path(LOGIN).read_bytes())})
    script.add(draft_for(LOGIN), qa_pass())
    job = approver.post(f"{P}/stages/brd/run", json={"intake": LOGIN}).json()
    assert wait_for(app, approver, job["id"])["status"] == "done"


def test_roles_unknown_stages_and_the_review_list(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    brd_in_review(empty_app, empty_client, script)
    viewer, approver = empty_client("viewer"), empty_client("approver")
    listed = viewer.get(f"{P}/reviews").json()
    assert listed["review_gates"] is True and listed["reviews"] == []
    assert [p["state"] for p in listed["phases"]] == ["in_review"] + ["not_started"] * 3
    comments = {"comments": [{"text": "Too vague."}]}
    assert viewer.post(f"{P}/stages/brd/reject", json=comments).status_code == 403
    assert approver.post(f"{P}/stages/nope/approve").status_code == 404
    assert approver.post(f"{P}/stages/srs/approve").status_code == 409
    assert approver.post(f"{P}/stages/brd/reject", json={"comments": []}).status_code == 422
    unknown = {"comments": [{"ref": f"{BRD}#item.99", "text": "x"}]}
    refused = approver.post(f"{P}/stages/brd/reject", json=unknown)
    assert refused.status_code == 409 and "not active items" in refused.json()["detail"]
    named = {"comments": [{"text": "x"}], "by": "mallory"}
    assert approver.post(f"{P}/stages/brd/reject", json=named).status_code == 422


def test_a_rejection_runs_as_a_job_and_returns_a_new_version(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    brd_in_review(empty_app, empty_client, script)
    approver, viewer = empty_client("approver"), empty_client("viewer")
    op = PatchOp(
        op="update", item_id=f"{BRD}#item.1", fields={"title": "Sign in by e-mail"}, reason="r"
    )
    script.add(RevisionPatch(operations=[op], summary="renamed"), qa_pass())
    body = {"comments": [{"ref": f"{BRD}#item.1", "text": "Say how users sign in."}]}
    started = approver.post(f"{P}/stages/brd/reject", json=body)
    assert started.status_code == 202, started.text
    job = wait_for(empty_app, approver, started.json()["id"])
    assert job["status"] == "done", job
    assert job["result"]["review"]["by"] == "alice"
    assert job["result"]["revision"]["documents"][0]["version"] == 2
    read = viewer.get(f"{P}/documents/{BRD}").json()
    assert read["versions"] == [1, 2] and read["document"]["status"] == "in_review"
    assert [r["decision"] for r in viewer.get(f"{P}/reviews").json()["reviews"]] == ["rejected"]
