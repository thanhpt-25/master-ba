"""Automatic propagation after a decision (spec 07 section 5.1)."""

import json
from pathlib import Path

from fastapi import FastAPI

from api_support import BlockingLLM, ClientFor, Script, clients, make_app, wait_for
from factories import qa_pass
from masterba.agents import QaIssue, QaReport
from masterba.change import PatchOp, RevisionPatch
from masterba.models import QuestionDraft
from masterba.models.enums import DocType, PropagationMode
from masterba.questions import record_questions
from masterba.trace_store import get_config, open_project, set_config

P = "/api/projects/PRJ-001"
BRD2 = "DOC-BRD-0001#item.2"
EMPTY = RevisionPatch(operations=[], summary="nothing to change")
SMS = RevisionPatch(
    operations=[
        PatchOp(op="update", item_id=BRD2, fields={"description": "By SMS or email."}, reason="DR")
    ],
    summary="SMS",
)


def set_auto(root: Path) -> None:
    store = open_project(root / "projects", "PRJ-001")
    mode = get_config(store).model_copy(update={"propagation_mode": PropagationMode.AUTO})
    set_config(store, mode)


def new_dr(client: object) -> str:
    created = client.post(  # type: ignore[attr-defined]
        f"{P}/drs",
        json={"trigger": "requirement_change", "description": "SMS too.", "items": ["REQ-0002"]},
    )
    return str(created.json()["id"])


def test_approving_in_auto_mode_starts_propagation(
    seeded_root: Path, seeded_app: FastAPI, script: Script
) -> None:
    set_auto(seeded_root)
    approver = clients(seeded_app)("approver")
    script.add(SMS, qa_pass(), *[EMPTY] * 6)
    dr_id = new_dr(approver)
    reply = approver.post(f"{P}/drs/{dr_id}/approve", json={"decision": "Go ahead"})
    assert reply.status_code == 200, reply.text
    job = wait_for(seeded_app, approver, reply.json()["job"]["id"])
    assert (job["kind"], job["status"]) == (f"propagate:{dr_id}", "done")
    assert approver.get(f"{P}/drs/{dr_id}").json()["dr"]["status"] == "propagated"


def test_approving_in_manual_mode_starts_nothing(seeded_client: ClientFor) -> None:
    approver = seeded_client("approver")
    dr_id = new_dr(approver)
    body = approver.post(f"{P}/drs/{dr_id}/approve", json={"decision": "Go ahead"}).json()
    assert "job" not in body and "propagation_note" not in body
    assert approver.get(f"{P}/drs/{dr_id}").json()["dr"]["status"] == "approved"


def test_answering_a_question_in_auto_mode_updates_the_documents(
    seeded_root: Path, seeded_app: FastAPI, script: Script
) -> None:
    set_auto(seeded_root)
    store = open_project(seeded_root / "projects", "PRJ-001")
    [question_id] = record_questions(
        store,
        "RUN-0009",
        DocType.SRS,
        [QuestionDraft(refs=["REQ-0002"], text="Does the limit count business days?")],
    ).ids
    approver = clients(seeded_app)("approver")
    script.add(SMS, qa_pass(), *[EMPTY] * 6)
    reply = approver.post(f"{P}/questions/{question_id}/answer", json={"answer": "Business days."})
    assert reply.status_code == 200, reply.text
    body = reply.json()
    assert wait_for(seeded_app, approver, body["job"]["id"])["status"] == "done"
    assert approver.get(f"{P}/drs/{body['dr']['id']}").json()["dr"]["status"] == "propagated"


def test_a_busy_project_keeps_the_approval_and_explains(seeded_root: Path, frontend: Path) -> None:
    set_auto(seeded_root)
    blocker = BlockingLLM()
    script = Script()
    script.factory = lambda model: blocker  # type: ignore[method-assign]
    app = make_app(seeded_root, script, frontend)
    approver = clients(app)("approver")
    first, second = new_dr(approver), new_dr(approver)
    started = approver.post(f"{P}/drs/{first}/approve", json={"decision": "Go"}).json()
    assert blocker.started.wait(10)
    busy = approver.post(f"{P}/drs/{second}/approve", json={"decision": "Go"})
    assert busy.status_code == 200
    assert busy.json()["dr"]["status"] == "approved"
    assert "press Propagate" in busy.json()["propagation_note"]
    blocker.release.set()
    wait_for(app, approver, started["job"]["id"])


def test_only_an_admin_changes_the_propagation_mode(seeded_client: ClientFor) -> None:
    url = f"{P}/settings/propagation-mode"
    assert seeded_client("approver").post(url, json={"propagation_mode": "auto"}).status_code == 403
    done = seeded_client("admin").post(url, json={"propagation_mode": "auto"})
    assert done.status_code == 200
    assert done.json()["propagation_mode"] == "auto"
    assert (
        json.loads(json.dumps(seeded_client("viewer").get(P).json()))["project"]["propagation_mode"]
        == "auto"
    )


def test_answering_an_intake_line_question_updates_the_documents_that_cite_it(
    seeded_root: Path, seeded_app: FastAPI, script: Script
) -> None:
    set_auto(seeded_root)
    store = open_project(seeded_root / "projects", "PRJ-001")
    [question_id] = record_questions(
        store,
        "RUN-0009",
        DocType.BRD,
        [QuestionDraft(refs=["intake/login_system.txt#L4-L4"], text="Which channels reset?")],
    ).ids
    approver = clients(seeded_app)("approver")
    script.add(SMS, qa_pass(), *[EMPTY] * 6)
    body = approver.post(
        f"{P}/questions/{question_id}/answer", json={"answer": "Email only."}
    ).json()
    assert body["dr"]["impacted_items"] == ["REQ-0002"]
    assert wait_for(seeded_app, approver, body["job"]["id"])["status"] == "done"


def test_a_document_waiting_for_an_answer_ends_the_job_waiting_for_input(
    seeded_root: Path, seeded_app: FastAPI, script: Script
) -> None:
    set_auto(seeded_root)
    approver = clients(seeded_app)("approver")
    asking = QaReport(
        issues=[
            QaIssue(
                checklist_id="BRD-01",
                severity="blocking",
                ref=BRD2,
                message="Which channel?",
                action_required="Name it.",
                customer_question=True,
            )
        ]
    )
    script.add(SMS, asking)
    dr_id = new_dr(approver)
    started = approver.post(f"{P}/drs/{dr_id}/approve", json={"decision": "Go"}).json()
    job = wait_for(seeded_app, approver, started["job"]["id"])
    assert job["status"] == "waiting_for_input"
    [doc] = job["result"]["documents"]
    assert doc["outcome"] == "waiting_for_input" and len(doc["question_ids"]) == 1
    assert approver.get(f"{P}/drs/{dr_id}").json()["dr"]["status"] == "approved"
    open_questions = approver.get(f"{P}/questions?status=open").json()
    assert doc["question_ids"][0] in [q["id"] for q in open_questions]
