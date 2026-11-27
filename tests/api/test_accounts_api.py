"""Spec 23: project isolation, sharing, usage metering, limits and user administration."""

from fastapi import FastAPI

from api_support import (
    LOGIN,
    PASSWORD,
    ClientFor,
    Script,
    brd_project,
    sign_in,
    start_brd,
    wait_for,
)
from factories import draft_for, qa_pass
from masterba.trace_store import open_project

P = "/api/projects/PRJ-001"


def test_the_seeded_project_is_migrated_to_the_admin_with_users_kept(
    seeded_client: ClientFor,
) -> None:
    access = seeded_client("viewer").get(f"{P}/access").json()
    assert access["owner"] == "root"
    assert access["members"] == [
        {"name": "alice", "role": "approver"},
        {"name": "vera", "role": "viewer"},
    ]
    assert access["my_role"] == "viewer"
    listed = seeded_client("approver").get("/api/projects").json()
    assert [(p["project_id"], p["owner"], p["my_role"]) for p in listed] == [
        ("PRJ-001", "root", "approver")
    ]


def test_a_new_user_sees_no_other_project_and_cannot_reach_it(
    seeded_app: FastAPI, seeded_client: ClientFor
) -> None:
    admin = seeded_client("admin")
    assert admin.get("/api/projects").is_success  # the upgrade migration ran before bob
    new = {"name": "bob", "role": "approver", "password": PASSWORD}
    assert admin.post("/api/admin/users", json=new).status_code == 201
    bob = sign_in(seeded_app, "bob")
    assert bob.get("/api/projects").json() == []
    for path in (P, f"{P}/documents", f"{P}/drs", f"{P}/access", f"{P}/questions"):
        assert bob.get(path).status_code == 404, path
    assert bob.post(f"{P}/stages/srs/run", json={}).status_code == 404
    job = seeded_app.state.masterba.jobs.submit("PRJ-001", "stage:x", lambda: {}, "root")
    assert bob.get(f"/api/jobs/{job.id}").status_code == 404
    assert seeded_client("viewer").get(f"/api/jobs/{job.id}").status_code == 200

    created = bob.post("/api/projects", json={"project_id": "PRJ-002"})
    assert created.status_code == 201
    alice = seeded_client("approver")
    assert [p["project_id"] for p in alice.get("/api/projects").json()] == ["PRJ-001"]
    assert alice.get("/api/projects/PRJ-002").status_code == 404
    assert [p["project_id"] for p in admin.get("/api/projects").json()] == ["PRJ-001", "PRJ-002"]

    # The owner shares it; the member role decides what alice may do.
    share = bob.post("/api/projects/PRJ-002/members", json={"name": "alice", "role": "viewer"})
    assert share.status_code == 200
    assert alice.get("/api/projects/PRJ-002").status_code == 200
    assert alice.post("/api/projects/PRJ-002/stages/srs/run", json={}).status_code == 403
    assert (
        alice.post(
            "/api/projects/PRJ-002/members", json={"name": "vera", "role": "viewer"}
        ).status_code
        == 403
    )
    budget = {"team_token_budget": 10}
    assert bob.post("/api/projects/PRJ-002/settings/token-budget", json=budget).is_success
    unknown = bob.post("/api/projects/PRJ-002/members", json={"name": "nobody", "role": "viewer"})
    assert unknown.status_code == 400

    # Removing bob hands PRJ-002 to the admin who removed him.
    assert admin.delete("/api/admin/users/bob").json() == {"removed": "bob", "projects_to": "root"}
    assert alice.get("/api/projects/PRJ-002/access").json()["owner"] == "root"
    assert bob.get("/api/me").status_code == 401


def test_every_model_call_of_a_job_is_charged_to_the_user_who_started_it(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    admin, approver = brd_project(empty_client)
    script.add(draft_for(LOGIN), qa_pass())
    job = start_brd(approver).json()
    assert job["user"] == "alice"
    assert wait_for(empty_app, approver, job["id"])["status"] == "done"
    usage = approver.get("/api/me/usage").json()
    assert [w["used"] for w in usage["windows"]] == [300, 300]
    assert usage["by_project"][0]["project_id"] == "PRJ-001"
    assert usage["by_project"][0]["calls"] == 2
    assert usage["recent"][0]["kind"] == "stage:brd"
    assert admin.get("/api/me/usage").json()["windows"][0]["used"] == 0
    listed = {u["name"]: u for u in admin.get("/api/admin/users").json()["users"]}
    assert listed["alice"]["usage"][0]["used"] == 300


def test_a_reached_limit_refuses_a_job_with_the_reset_time(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    admin, approver = brd_project(empty_client)
    limits = {"limits": {"session": 0, "weekly": None}}
    changed = admin.patch("/api/admin/users/alice", json=limits)
    assert changed.status_code == 200
    assert changed.json()["custom_limits"] is True
    refused = start_brd(approver)
    assert refused.status_code == 429
    detail = refused.json()["detail"]
    assert detail["code"] == "usage_limit"
    assert detail["window"] == "session"
    me = approver.get("/api/me").json()
    assert me["usage"][0]["reached"] is True
    # Back to the defaults (no limit): the run may start.
    assert admin.patch("/api/admin/users/alice", json={"limits": None}).json()["limits"] == {
        "session": None,
        "weekly": None,
    }
    script.add(draft_for(LOGIN), qa_pass())
    job = start_brd(approver)
    assert job.status_code == 202
    assert wait_for(empty_app, approver, job.json()["id"])["status"] == "done"


def test_a_limit_reached_during_a_run_escalates_it_with_a_checkpoint(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    admin, approver = brd_project(empty_client)
    assert admin.put("/api/admin/limits", json={"session": 150, "weekly": None}).is_success
    script.add(draft_for(LOGIN), qa_pass())
    job = wait_for(empty_app, approver, start_brd(approver).json()["id"])
    assert job["status"] == "escalated"
    store = open_project(empty_app.state.masterba.settings.projects, "PRJ-001")
    runs = approver.get(f"{P}/runs").json()
    assert "usage limit reached" in " ".join(runs[0]["escalations"])
    assert (store.path / "runs" / runs[0]["run_id"] / "checkpoint.json").exists()
    assert start_brd(approver).status_code == 429
    # The admin starts a new window; the run resumes where it stopped.
    reset = admin.post("/api/admin/users/alice/reset-usage").json()
    assert reset["usage"][0]["used"] == 0
    assert admin.put("/api/admin/limits", json={"session": 400, "weekly": None}).is_success
    script.responses.insert(1, draft_for(LOGIN))  # the resumed round starts with the writer
    resume = approver.post(
        f"{P}/stages/brd/run", json={"intake": LOGIN, "resume": runs[0]["run_id"]}
    )
    assert resume.status_code == 202, resume.text
    assert wait_for(empty_app, approver, resume.json()["id"])["status"] == "done"


def test_user_administration_is_for_admins_only(seeded_client: ClientFor) -> None:
    approver, admin = seeded_client("approver"), seeded_client("admin")
    for method, path, body in (
        ("GET", "/api/admin/users", None),
        ("POST", "/api/admin/users", {"name": "x1", "role": "viewer", "password": PASSWORD}),
        ("PATCH", "/api/admin/users/vera", {"role": "approver"}),
        ("DELETE", "/api/admin/users/vera", None),
        ("POST", "/api/admin/users/vera/reset-usage", None),
        ("GET", "/api/admin/limits", None),
        ("PUT", "/api/admin/limits", {"session": 1, "weekly": 1}),
    ):
        assert approver.request(method, path, json=body).status_code == 403, path
    assert admin.patch("/api/admin/users/vera", json={"role": "approver"}).json()["role"] == (
        "approver"
    )
    assert admin.patch("/api/admin/users/vera", json={"password": "another pass 1"}).is_success
    assert admin.patch("/api/admin/users/root", json={"role": "viewer"}).status_code == 400
    assert admin.delete("/api/admin/users/root").status_code == 400
    assert admin.delete("/api/admin/users/nobody").status_code == 404
    short = {"name": "x2", "role": "viewer", "password": "short"}
    assert admin.post("/api/admin/users", json=short).status_code == 400
    assert admin.put("/api/admin/limits", json={"session": 500, "weekly": None}).json() == {
        "session": 500,
        "weekly": None,
    }
    assert admin.get("/api/admin/users").json()["default_limits"]["session"] == 500


def test_the_owner_hands_a_project_over(seeded_client: ClientFor) -> None:
    admin = seeded_client("admin")
    handed = admin.post(f"{P}/owner", json={"name": "alice"})
    assert handed.json()["owner"] == "alice"
    assert seeded_client("approver").get(f"{P}/access").json()["my_role"] == "admin"
    removed = seeded_client("approver").delete(f"{P}/members/vera")
    assert removed.json()["members"] == [{"name": "root", "role": "approver"}]
    assert seeded_client("viewer").get(P).status_code == 404
