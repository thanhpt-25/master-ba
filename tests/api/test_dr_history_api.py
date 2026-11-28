"""The 履歴 sheet of a Decision Record: the commits that touched it (spec 26 section 7)."""

from api_support import ClientFor

P = "/api/projects/PRJ-001"


def test_the_history_lists_the_record_commits_oldest_first(seeded_client: ClientFor) -> None:
    approver = seeded_client("approver")
    created = approver.post(
        f"{P}/drs",
        json={"trigger": "requirement_change", "description": "SMS too.", "items": ["REQ-0002"]},
    )
    assert created.status_code == 201, created.text
    dr_id = created.json()["id"]
    assert approver.post(f"{P}/drs/{dr_id}/approve", json={"decision": "Go"}).status_code == 200

    reply = seeded_client("viewer").get(f"{P}/drs/{dr_id}/history")
    assert reply.status_code == 200
    subjects = [e["subject"] for e in reply.json()]
    assert subjects[0] == f"dr(PRJ-001): create {dr_id}"
    assert any("approve" in s for s in subjects[1:])
    assert all(dr_id in s for s in subjects)
    assert set(reply.json()[0]) == {"commit", "author", "time", "subject"}


def test_an_unknown_record_has_no_history(seeded_client: ClientFor) -> None:
    viewer = seeded_client("viewer")
    assert viewer.get(f"{P}/drs/DR-9999/history").status_code == 404
    assert viewer.get(f"{P}/drs/nope/history").status_code in (404, 422)
