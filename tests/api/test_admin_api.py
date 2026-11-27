"""Spec 24: account life cycle, audit log, limit events, prices, dashboard and all projects."""

import base64
import time

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
from masterba.api.deps import COOKIE, AppState


def state(app: FastAPI) -> AppState:
    found: AppState = app.state.masterba
    return found


def actions(app: FastAPI) -> list[tuple[str, str, str | None]]:
    events, _ = state(app).audit.query(limit=200)
    return [(e["actor"], e["action"], e["target"]) for e in reversed(events)]


def test_a_disabled_user_is_signed_out_and_cannot_sign_in_until_enabled(
    seeded_app: FastAPI, seeded_client: ClientFor
) -> None:
    admin, viewer = seeded_client("admin"), seeded_client("viewer")
    assert viewer.get("/api/me").status_code == 200
    disabled = admin.post("/api/admin/users/vera/disable")
    assert disabled.json()["disabled"] is True
    assert viewer.get("/api/me").status_code == 401
    login = {"name": "vera", "password": PASSWORD}
    assert viewer.post("/api/login", json=login).status_code == 401
    assert admin.post("/api/admin/users/root/disable").status_code == 400
    assert admin.post("/api/admin/users/nobody/disable").status_code == 404
    assert admin.post("/api/admin/users/vera/enable").json()["disabled"] is False
    assert viewer.post("/api/login", json=login).status_code == 200
    assert viewer.get("/api/me").status_code == 200
    listed = {u["name"]: u for u in admin.get("/api/admin/users").json()["users"]}
    assert listed["vera"]["last_login"] is not None
    assert listed["vera"]["created"] is not None
    assert ("root", "user.disable", "vera") in actions(seeded_app)
    assert ("anonymous", "auth.login_failed", "vera") in actions(seeded_app)


def test_sign_out_everywhere_and_a_password_reset_end_open_sessions(
    seeded_app: FastAPI, seeded_client: ClientFor
) -> None:
    admin = seeded_client("admin")
    first, second = sign_in(seeded_app, "alice"), sign_in(seeded_app, "alice")
    assert admin.post("/api/admin/users/alice/signout").is_success
    assert first.get("/api/me").status_code == 401
    assert second.get("/api/me").status_code == 401
    assert admin.post("/api/admin/users/root/signout").status_code == 400
    again = sign_in(seeded_app, "alice")
    assert admin.patch("/api/admin/users/alice", json={"password": "a new password"}).is_success
    assert again.get("/api/me").status_code == 401
    # The admin's own password change keeps the admin signed in.
    assert admin.patch("/api/admin/users/root", json={"password": "root password 2"}).is_success
    assert admin.get("/api/me").status_code == 200


def test_a_cookie_of_the_old_form_still_works_until_sessions_are_ended(
    seeded_app: FastAPI, seeded_client: ClientFor
) -> None:
    app = state(seeded_app)
    expiry = int(time.time() + 3600)
    payload = base64.urlsafe_b64encode(f"vera\n{expiry}".encode()).decode("ascii")
    old = f"{payload}.{app.signer._sign(payload.encode('ascii'))}"
    viewer = seeded_client(None)
    viewer.cookies.set(COOKIE, old)
    assert viewer.get("/api/me").json()["name"] == "vera"
    app.users.end_sessions("vera")
    assert viewer.get("/api/me").status_code == 401
    assert app.signer.session("garbage") is None
    assert app.signer.session(f"{base64.urlsafe_b64encode(b'a').decode()}.x") is None


def test_every_admin_action_writes_one_audit_row_without_passwords(
    seeded_app: FastAPI, seeded_client: ClientFor
) -> None:
    admin = seeded_client("admin")
    new = {"name": "dan", "role": "viewer", "password": "dan password"}
    assert admin.post("/api/admin/users", json=new).status_code == 201
    admin.patch("/api/admin/users/dan", json={"role": "approver", "limits": {"session": 5}})
    admin.post("/api/admin/users/dan/reset-usage")
    admin.put("/api/admin/limits", json={"session": None, "weekly": 9})
    admin.post("/api/projects/PRJ-001/members", json={"name": "dan", "role": "viewer"})
    admin.delete("/api/projects/PRJ-001/members/dan")
    admin.post("/api/projects/PRJ-001/owner", json={"name": "alice"})
    admin.delete("/api/admin/users/dan")
    admin.post("/api/logout")
    found = [a for a in actions(seeded_app) if a[0] == "root"]
    assert [a[1] for a in found] == [
        "auth.login",
        "user.create",
        "user.role",
        "user.limits",
        "user.usage_reset",
        "limits.default",
        "project.member_set",
        "project.member_remove",
        "project.owner",
        "user.remove",
        "auth.logout",
    ]
    events, _ = state(seeded_app).audit.query(limit=200)
    assert all("password" not in str(e) for e in events)
    owner = next(e for e in events if e["action"] == "project.owner")
    assert owner["project_id"] == "PRJ-001"
    assert owner["detail"] == {"previous": "root"}


def test_the_audit_log_filters_pages_and_downloads_as_csv(
    seeded_app: FastAPI, seeded_client: ClientFor
) -> None:
    admin = seeded_client("admin")
    for name, role in (("alice", "viewer"), ("vera", "approver")):
        assert admin.patch(f"/api/admin/users/{name}", json={"role": role}).is_success
    log = state(seeded_app).audit
    log.record("=evil", "user.role", target="x", detail={"note": "+1"})
    page = admin.get("/api/admin/audit", params={"limit": 2}).json()
    assert len(page["events"]) == 2
    rest = admin.get("/api/admin/audit", params={"limit": 50, "before": page["next"]}).json()
    assert rest["next"] is None
    assert page["events"][-1]["id"] > rest["events"][0]["id"]
    users = admin.get("/api/admin/audit", params={"action": "user", "days": 1}).json()["events"]
    assert {e["action"] for e in users} == {"user.role"}
    by_actor = admin.get("/api/admin/audit", params={"actor": "root", "target": "vera"}).json()
    assert [e["action"] for e in by_actor["events"]] == ["user.role"]
    exact = admin.get("/api/admin/audit", params={"action": "auth.login"}).json()["events"]
    assert {e["actor"] for e in exact} == {"root"}
    csv = admin.get("/api/admin/audit.csv", params={"action": "user"})
    assert csv.headers["content-type"].startswith("text/csv")
    assert "attachment" in csv.headers["content-disposition"]
    lines = csv.text.lstrip("﻿").splitlines()
    assert lines[0].startswith("id,at,actor,action")
    assert any(",'=evil,user.role," in line for line in lines)
    assert seeded_client("approver").get("/api/admin/audit").status_code == 403


def test_limit_hits_are_recorded_and_counted_on_the_dashboard(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    admin, approver = brd_project(empty_client)
    assert admin.put("/api/admin/limits", json={"session": 150, "weekly": None}).is_success
    script.add(draft_for(LOGIN), qa_pass())
    job = wait_for(empty_app, approver, start_brd(approver).json()["id"])
    assert job["status"] == "escalated"
    assert start_brd(approver).status_code == 429
    hits = state(empty_app).usage.limit_events(0)
    assert [h["context"] for h in hits] == ["job_start", "run"]
    board = admin.get("/api/admin/dashboard", params={"days": 7}).json()
    assert board["kpis"]["limits"]["hits"] == 2
    assert board["kpis"]["limits"]["at_limit"] == 1
    assert board["attention"]["near_limit"][0]["name"] == "alice"
    assert board["kpis"]["jobs"]["escalated"] == 1
    assert board["attention"]["jobs"][0]["status"] == "escalated"
    assert ("alice", "job.start", job["id"]) in actions(empty_app)


def test_the_dashboard_totals_match_the_recorded_calls_with_every_day_present(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    admin, approver = brd_project(empty_client)
    script.add(draft_for(LOGIN), qa_pass())
    assert wait_for(empty_app, approver, start_brd(approver).json()["id"])["status"] == "done"
    ledger = state(empty_app).usage
    ledger.record("root", project=None, kind=None, model="other", input_tokens=7, output_tokens=3)
    board = admin.get("/api/admin/dashboard", params={"days": 30, "tz": -540}).json()
    assert len(board["daily"]) == 30
    assert board["daily"][-1]["tokens"] == board["kpis"]["tokens"]["tokens"] == 310
    assert sum(d["calls"] for d in board["daily"]) == board["kpis"]["tokens"]["calls"] == 3
    assert board["kpis"]["tokens"]["previous"] == 0
    assert board["top_users"][0] == {
        "name": "alice",
        "input": 200,
        "output": 100,
        "calls": 2,
        "tokens": 300,
        "cost": None,
        "unpriced_tokens": 300,
    }
    assert board["top_projects"][0]["project_id"] == "PRJ-001"
    assert {k["kind"] for k in board["kinds"]} == {"stage:brd", None}
    assert board["kpis"]["cost"]["total"] is None
    assert board["kpis"]["users"] == {"total": 3, "active": 2, "disabled": 0, "admins": 1}
    assert board["kpis"]["projects"] == {"total": 1, "active": 1}
    assert board["kpis"]["sign_ins"]["ok"] == 2
    delivery = board["delivery"]
    assert delivery["documents"]["in_review"] == 1
    assert delivery["stages"]["brd"] == {"done": 1}
    assert delivery["waiting_reviews"] == [{"project_id": "PRJ-001", "stage": "brd"}]
    assert board["audit"][0]["action"] == "job.start"

    # Prices: the model of the run is priced, `other` stays unpriced.
    model = board["models"][0]["model"]
    prices = {"currency": "JPY", "models": {model: {"input": 1000, "output": 2000}}}
    saved = admin.put("/api/admin/prices", json=prices).json()
    assert saved["currency"] == "JPY"
    assert set(saved["seen_models"]) == {model, "other"}
    priced = admin.get("/api/admin/dashboard", params={"days": 7}).json()
    assert priced["kpis"]["cost"] == {
        "total": 0.4,
        "previous": 0.0,
        "currency": "JPY",
        "unpriced_tokens": 10,
        "priced": True,
    }
    assert admin.get("/api/admin/dashboard", params={"days": 5}).status_code == 400
    bad = {"currency": "yen", "models": {}}
    assert admin.put("/api/admin/prices", json=bad).status_code == 422
    assert approver.get("/api/admin/dashboard").status_code == 403


def test_all_projects_lists_owner_members_stages_and_tokens(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    admin, approver = brd_project(empty_client)
    script.add(draft_for(LOGIN), qa_pass())
    assert wait_for(empty_app, approver, start_brd(approver).json()["id"])["status"] == "done"
    data = admin.get("/api/admin/projects").json()
    project = data["projects"][0]
    assert project["project_id"] == "PRJ-001"
    assert project["owner"] == "root"
    assert {m["name"] for m in project["members"]} == {"alice", "vera"}
    assert project["stages"][0] == {
        "stage": "brd",
        "status": "done",
        "review": "in_review",
        "open_questions": 1,
    }
    assert project["open_questions"] == 1
    assert project["tokens_30d"] == 300
    assert project["last_activity"] is not None
    assert {u["name"] for u in data["users"]} == {"alice", "root", "vera"}
    assert approver.get("/api/admin/projects").status_code == 403
