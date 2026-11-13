import threading
from io import BytesIO
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook
from pydantic import BaseModel

from api_support import ClientFor, Script, clients, make_app, wait_for
from factories import (
    bad_draft,
    draft_for,
    intake_path,
    login_design_draft,
    login_detail_draft,
    login_srs_draft,
    login_test_draft,
    login_unit_draft,
    qa_pass,
)
from masterba.change import PatchOp, RevisionPatch
from masterba.llm import LLM, LLMResult
from masterba.llm.base import T
from masterba.models.enums import DocType, TeamRunStatus
from masterba.team import Team
from masterba.trace_store import open_project

LOGIN = "login_system.txt"
P = "/api/projects/PRJ-001"
BRD2 = "DOC-BRD-0001#item.2"
EMPTY = RevisionPatch(operations=[], summary="nothing to change")


def test_project_token_budget_defaults_to_100k_and_is_admin_editable(
    empty_client: ClientFor,
) -> None:
    admin, approver, viewer = (
        empty_client("admin"),
        empty_client("approver"),
        empty_client("viewer"),
    )
    created = admin.post("/api/projects", json={"project_id": "PRJ-001"})
    assert created.status_code == 201
    assert created.json()["team_token_budget"] == 100_000
    assert (
        viewer.post(f"{P}/settings/token-budget", json={"team_token_budget": 5000}).status_code
        == 403
    )
    assert (
        approver.post(f"{P}/settings/token-budget", json={"team_token_budget": 5000}).status_code
        == 403
    )
    changed = admin.post(f"{P}/settings/token-budget", json={"team_token_budget": 5000})
    assert changed.status_code == 200
    assert changed.json()["team_token_budget"] == 5000
    unlimited = admin.post(f"{P}/settings/token-budget", json={"team_token_budget": None})
    assert unlimited.status_code == 200
    assert unlimited.json()["team_token_budget"] is None


def run_stage(
    app: FastAPI, client: TestClient, script: Script, stage: str, *answers: BaseModel, **body: Any
) -> dict[str, Any]:
    script.add(*answers)
    reply = client.post(f"{P}/stages/{stage}/run", json=body)
    assert reply.status_code == 202, reply.text
    return wait_for(app, client, reply.json()["id"])


def test_the_whole_pipeline_runs_through_the_api_alone(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    admin, approver, viewer = (
        empty_client("admin"),
        empty_client("approver"),
        empty_client("viewer"),
    )
    created = admin.post("/api/projects", json={"project_id": "PRJ-001", "document_language": "en"})
    assert created.status_code == 201
    assert created.json()["team_token_budget"] == 100_000
    assert [p["project_id"] for p in viewer.get("/api/projects").json()] == ["PRJ-001"]
    overview = viewer.get(P).json()
    assert [s["status"] for s in overview["stages"]] == ["not_started"] * 4

    upload = approver.post(f"{P}/intake", files={"file": (LOGIN, intake_path(LOGIN).read_bytes())})
    assert upload.json() == {"name": LOGIN}

    brd = run_stage(empty_app, approver, script, "brd", draft_for(LOGIN), qa_pass(), intake=LOGIN)
    assert brd["status"] == "done"
    assert brd["result"]["requirement_ids"] == [f"REQ-000{n}" for n in range(1, 6)]
    assert any("round 1 started" in line for line in brd["log"])
    assert brd["log"][-1].endswith("done after 1 round(s)")

    # Review gates are on for a new project (spec 15): the next stage waits for approval.
    blocked = run_stage(empty_app, approver, script, "srs")
    assert blocked["status"] == "failed" and "approve the brd phase first" in blocked["error"]
    assert viewer.get(P).json()["stages"][1]["waiting_for"] == "brd"
    assert viewer.post(f"{P}/stages/brd/approve").status_code == 403
    approved = approver.post(f"{P}/stages/brd/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["review"]["by"] == "alice"  # the signed-in user
    assert approved.json()["open_questions"][0]["id"] == "Q-0001"
    assert approver.post(f"{P}/stages/brd/approve").status_code == 409  # no longer in review

    srs = run_stage(empty_app, approver, script, "srs", login_srs_draft(), qa_pass())
    assert approver.post(f"{P}/stages/srs/approve").status_code == 200
    basic = run_stage(
        empty_app, approver, script, "basic",
        login_design_draft(), login_test_draft(), qa_pass(), qa_pass(),
    )  # fmt: skip
    assert approver.post(f"{P}/stages/basic/approve").status_code == 200
    detail = run_stage(
        empty_app, approver, script, "detail",
        login_detail_draft(), login_unit_draft(), qa_pass(), qa_pass(),
    )  # fmt: skip
    assert [j["status"] for j in (srs, basic, detail)] == ["done"] * 3

    overview = viewer.get(P).json()
    assert [s["status"] for s in overview["stages"]] == ["done"] * 4
    assert overview["counts"] == {
        "requirements": 5,
        "links": 34,
        "open_drs": 0,
        "open_questions": 1,
    }
    assert overview["job"] is None
    assert overview["open_questions"] == ["Q-0001: What response time counts as fast?"]
    assert overview["stages"][2]["last_run"]["stage"] == "BASIC_DESIGN"

    documents = viewer.get(f"{P}/documents").json()
    assert len(documents) == 7
    read = viewer.get(f"{P}/documents/DOC-SRS-0001").json()
    assert read["versions"] == [1]
    assert len(read["content"]["items"]) == 4
    file = viewer.get(f"{P}/documents/DOC-SRS-0001/xlsx")
    assert file.headers["content-disposition"].endswith('"DOC-SRS-0001.v1.xlsx"')
    assert "機能要件" in load_workbook(BytesIO(file.content)).sheetnames

    trace = viewer.get(f"{P}/rtm/REQ-0002").json()
    ends = {path[-1] for path in trace["paths"]}
    assert {"DOC-TEST_IT-0001#item.3", "DOC-TEST_ST-0001#item.2", "DOC-TEST_UT-0001#item.3"} <= ends
    assert trace["nodes"]["REQ-0002"]["kind"] == "requirement"
    assert trace["nodes"]["DOC-SRS-0001#item.2"]["text"].startswith("The system shall let")

    runs = viewer.get(f"{P}/runs").json()
    assert [r["run_id"] for r in runs] == ["RUN-0004", "RUN-0003", "RUN-0002", "RUN-0001"]
    detail_run = viewer.get(f"{P}/runs/RUN-0003").json()
    assert {"summary", "tasks", "mailbox"} <= set(detail_run)
    assert detail_run["summary"]["stage"] == "BASIC_DESIGN"

    subjects = [e["subject"] for e in viewer.get(f"{P}/activity?limit=500").json()]
    assert subjects[-1] == "project(PRJ-001): create"
    assert subjects[-2] == "intake(PRJ-001): add login_system.txt"
    assert subjects[0] == "run(PRJ-001): RUN-0004 done"
    assert "render(PRJ-001): xlsx DOC-BRD-0001 v1" in subjects

    impact = viewer.get(
        f"{P}/impact", params={"node": "TC-UT-0003", "direction": "upstream"}
    ).json()
    assert "REQ-0002" in [n["node_id"] for n in impact]


def test_an_unfinished_stage_cannot_be_started_out_of_order(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    admin, approver = empty_client("admin"), empty_client("approver")
    admin.post("/api/projects", json={"project_id": "PRJ-001", "document_language": "en"})
    job = run_stage(empty_app, approver, script, "srs")
    assert job["status"] == "failed"
    assert "run the brd stage first" in job["error"]
    assert "Traceback" not in job["error"]
    missing = approver.post(f"{P}/stages/brd/run", json={})
    assert (missing.status_code, missing.json()["detail"]) == (
        400,
        "upload an intake first and name it",
    )
    assert approver.post(f"{P}/stages/nope/run", json={}).status_code == 404


def test_an_escalated_stage_ends_the_job_escalated_and_writes_no_document(
    empty_app: FastAPI, empty_client: ClientFor, script: Script
) -> None:
    admin, approver = empty_client("admin"), empty_client("approver")
    admin.post(
        "/api/projects",
        json={"project_id": "PRJ-001", "document_language": "en", "team_max_rounds": 1},
    )
    approver.post(f"{P}/intake", files={"file": (LOGIN, intake_path(LOGIN).read_bytes())})
    job = run_stage(empty_app, approver, script, "brd", bad_draft(), intake=LOGIN)
    assert job["status"] == "escalated"
    assert job["result"]["escalations"][0] == "max rounds reached (1)"
    assert approver.get(f"{P}/documents").json() == []
    overview = approver.get(P).json()
    assert overview["stages"][0]["status"] == "escalated"
    assert overview["stages"][0]["last_run"]["status"] == "escalated"


def test_latest_escalation_is_not_hidden_by_existing_documents(
    seeded_app: FastAPI, seeded_client: ClientFor
) -> None:
    from pathlib import Path

    root = Path(seeded_app.state.masterba.settings.projects) / "PRJ-001" / "runs" / "RUN-9999"
    root.mkdir(parents=True)
    (root / "team-summary.json").write_text(
        '{"run_id":"RUN-9999","stage":"BRD","trigger":"initial","status":"escalated"}',
        encoding="utf-8",
    )

    stages = seeded_client("viewer").get(P).json()["stages"]
    assert stages[0]["documents"]
    assert stages[0]["status"] == "escalated"


class BlockingLLM:
    """A model that waits until released, to keep a job running."""

    def __init__(self) -> None:
        self.started = threading.Event()
        self.release = threading.Event()

    def generate(self, *, system: str, user: str, output: type[T], tool_name: str) -> LLMResult[T]:
        self.started.set()
        self.release.wait(10)
        raise RuntimeError("released")


def approved_dr(client: TestClient) -> str:
    created = client.post(
        f"{P}/drs",
        json={"trigger": "requirement_change", "description": "SMS too.", "items": ["REQ-0002"]},
    )
    assert created.status_code == 201, created.text
    dr_id: str = created.json()["id"]
    approve = client.post(f"{P}/drs/{dr_id}/approve", json={"decision": "Go ahead"})
    assert approve.status_code == 200, approve.text
    return dr_id


def test_a_second_job_on_a_busy_project_is_refused(seeded_root: Path, frontend: Path) -> None:
    blocker = BlockingLLM()
    script = Script()
    script.factory = lambda model: blocker  # type: ignore[method-assign]
    app = make_app(seeded_root, script, frontend)
    approver = clients(app)("approver")
    dr_id = approved_dr(approver)
    first = approver.post(f"{P}/drs/{dr_id}/propagate")
    assert first.status_code == 202
    assert blocker.started.wait(10)
    assert approver.post(f"{P}/drs/{dr_id}/propagate").status_code == 409
    assert approver.post(f"{P}/stages/srs/run", json={}).status_code == 409
    assert approver.get(P).json()["job"]["status"] == "running"
    blocker.release.set()
    done = wait_for(app, approver, first.json()["id"])
    assert done["status"] == "failed"
    assert done["error"] == "RuntimeError: released"
    assert approver.get(P).json()["job"] is None


def test_a_decision_record_goes_from_proposal_to_closed_through_the_api(
    seeded_app: FastAPI, seeded_client: ClientFor, script: Script
) -> None:
    approver, viewer = seeded_client("approver"), seeded_client("viewer")
    created = approver.post(
        f"{P}/drs",
        json={"trigger": "requirement_change", "description": "SMS too.", "items": ["REQ-0002"]},
    )
    dr_id = created.json()["id"]
    assert created.json()["status"] == "proposed"
    assert len(created.json()["affected_documents"]) == 7

    approved = approver.post(
        f"{P}/drs/{dr_id}/approve", json={"decision": "Go ahead", "rationale": "Customer asked"}
    ).json()
    assert approved["dr"]["approver"] == "alice"
    assert approved["dr"]["status"] == "approved"
    shown = viewer.get(f"{P}/drs/{dr_id}").json()
    assert shown["impact"]["documents"][0] == "DOC-BRD-0001"
    assert shown["propagation"] is None

    patch = RevisionPatch(
        operations=[
            PatchOp(
                op="update",
                item_id=BRD2,
                fields={"description": "Reset by SMS or email."},
                reason=dr_id,
            )
        ],
        summary="SMS",
    )
    script.add(patch, qa_pass(), *[EMPTY] * 6)
    job = approver.post(f"{P}/drs/{dr_id}/propagate")
    assert job.status_code == 202
    finished = wait_for(seeded_app, approver, job.json()["id"])
    assert finished["status"] == "done"
    assert finished["result"]["dr_status"] == "propagated"
    assert [d["outcome"] for d in finished["result"]["documents"]] == ["revised"] + [
        "unchanged"
    ] * 6

    brd = viewer.get(f"{P}/documents/DOC-BRD-0001").json()
    assert brd["versions"] == [1, 2]
    assert brd["document"]["version"] == 2
    old = viewer.get(f"{P}/documents/DOC-BRD-0001", params={"version": 1}).json()
    assert old["content"]["items"][1]["description"] != "Reset by SMS or email."
    diff = viewer.get(f"{P}/documents/DOC-BRD-0001/diff", params={"from": 1, "to": 2}).json()
    assert [(r["item_id"], r["field"]) for r in diff["rows"]] == [(BRD2, "description")]
    dr_diff = viewer.get(f"{P}/drs/{dr_id}/diff").json()
    assert [d["doc_id"] for d in dr_diff["documents"]] == ["DOC-BRD-0001"]
    assert viewer.get(f"{P}/documents/DOC-BRD-0001/xlsx", params={"version": 2}).status_code == 200
    assert viewer.get(f"{P}/documents/DOC-SRS-0001/xlsx", params={"version": 2}).status_code == 404

    closed = approver.post(f"{P}/drs/{dr_id}/close").json()
    assert closed["status"] == "closed"
    assert viewer.get(P).json()["counts"]["open_drs"] == 0


def test_rejecting_and_the_lifecycle_rules_are_enforced(seeded_client: ClientFor) -> None:
    approver = seeded_client("approver")
    created = approver.post(
        f"{P}/drs", json={"trigger": "defect", "description": "Bug", "items": ["REQ-0001"]}
    )
    dr_id = created.json()["id"]
    rejected = approver.post(f"{P}/drs/{dr_id}/reject", json={"decision": "Not funded"}).json()
    assert (rejected["status"], rejected["approver"]) == ("closed", "alice")
    again = approver.post(f"{P}/drs/{dr_id}/approve", json={"decision": "ok"})
    assert again.status_code == 400
    assert "only a proposed DR can be approved" in again.json()["detail"]
    assert approver.post(f"{P}/drs/{dr_id}/close").status_code == 400
    unknown = approver.post(
        f"{P}/drs", json={"trigger": "defect", "description": "x", "items": ["REQ-0099"]}
    )
    assert unknown.status_code == 404
    none = approver.post(f"{P}/drs", json={"trigger": "defect", "description": "x", "items": []})
    assert none.status_code == 400


def test_a_decision_record_can_be_made_from_an_escalated_run(
    seeded_root: Path, seeded_client: ClientFor
) -> None:
    team = Team.open(
        open_project(seeded_root / "projects", "PRJ-001"), DocType.BASIC_DESIGN, 3, None
    )
    team.escalate(["max rounds reached (3)"])
    team.finish(TeamRunStatus.ESCALATED)
    approver = seeded_client("approver")
    made = approver.post(f"{P}/drs/from-run", json={"run_id": team.run_id})
    assert made.status_code == 201
    assert made.json()["trigger"] == "clarification"
    assert approver.post(f"{P}/drs/from-run", json={"run_id": "RUN-0001"}).status_code == 400


def test_a_stage_job_uses_the_models_configured_on_the_server(
    empty_root: Path, frontend: Path
) -> None:
    seen: list[str] = []
    script = Script()

    def factory(model: str) -> LLM:
        seen.append(model)
        return script.llm

    from masterba.api import Settings, create_app

    settings = Settings(
        root=empty_root,
        llm_factory=factory,
        model="writer-m",
        qa_model="qa-m",
        test_model="test-m",
        hash_iterations=1000,
    )
    app = create_app(settings, frontend)
    app.state.masterba.users.add("root", "admin", "correct horse battery")
    admin = TestClient(app, headers={"X-MasterBA": "1"})
    admin.post("/api/login", json={"name": "root", "password": "correct horse battery"})
    admin.post("/api/projects", json={"project_id": "PRJ-001", "document_language": "en"})
    admin.post(f"{P}/intake", files={"file": (LOGIN, intake_path(LOGIN).read_bytes())})
    script.add(draft_for(LOGIN), qa_pass())
    reply = admin.post(f"{P}/stages/brd/run", json={"intake": LOGIN})
    wait_for(app, admin, reply.json()["id"])
    assert seen == ["writer-m", "qa-m", "test-m"]
