"""Several approved DRs in one job (spec 07 section 5.2)."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api_support import ClientFor, Script, clients, wait_for
from masterba.change import RevisionPatch

P = "/api/projects/PRJ-001"
EMPTY = RevisionPatch(operations=[], summary="nothing to change")


def new_dr(client: TestClient, approve: bool = True) -> str:
    created = client.post(
        f"{P}/drs",
        json={"trigger": "requirement_change", "description": "SMS too.", "items": ["REQ-0002"]},
    )
    dr_id = str(created.json()["id"])
    if approve:
        reply = client.post(f"{P}/drs/{dr_id}/approve", json={"decision": "Go ahead"})
        assert reply.status_code == 200, reply.text
    return dr_id


def test_every_approved_dr_runs_in_one_job(seeded_app: FastAPI, script: Script) -> None:
    approver = clients(seeded_app)("approver")
    first, second = new_dr(approver), new_dr(approver)
    new_dr(approver, approve=False)
    script.add(*[EMPTY] * 14)
    reply = approver.post(f"{P}/drs/propagate", json={})
    assert reply.status_code == 202, reply.text
    assert reply.json()["kind"] == f"propagate:{first},{second}"
    job = wait_for(seeded_app, approver, reply.json()["id"])
    assert job["status"] == "done"
    assert [(r["dr_id"], r["outcome"]) for r in job["result"]["results"]] == [
        (first, "propagated"),
        (second, "propagated"),
    ]
    assert f"{second}: propagating (2/2)" in job["log"]
    for dr_id in (first, second):
        assert approver.get(f"{P}/drs/{dr_id}").json()["dr"]["status"] == "propagated"


def test_named_drs_must_exist_and_be_approved(seeded_client: ClientFor) -> None:
    approver = seeded_client("approver")
    assert approver.post(f"{P}/drs/propagate", json={}).status_code == 409
    approved, proposed = new_dr(approver), new_dr(approver, approve=False)
    refused = approver.post(f"{P}/drs/propagate", json={"dr_ids": [approved, proposed]})
    assert refused.status_code == 409
    assert proposed in refused.json()["detail"]
    assert approver.post(f"{P}/drs/propagate", json={"dr_ids": ["DR-9999"]}).status_code == 404
    assert approver.post(f"{P}/drs/propagate", json={"dr_ids": ["../x"]}).status_code == 404
