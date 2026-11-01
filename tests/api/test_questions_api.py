from api_support import ClientFor

P = "/api/projects/PRJ-001"


def first_question(client: object) -> str:
    listed = client.get(f"{P}/questions").json()  # type: ignore[attr-defined]
    assert listed, "the demo chain has the BRD draft's open question"
    return str(listed[0]["id"])


def test_a_viewer_reads_and_an_approver_answers_with_their_own_name(
    seeded_client: ClientFor,
) -> None:
    viewer, approver = seeded_client("viewer"), seeded_client("approver")
    qid = first_question(viewer)
    assert viewer.get(f"{P}/questions?status=open").json()[0]["id"] == qid
    assert viewer.get(f"{P}/questions?status=answered").json() == []
    shown = viewer.get(f"{P}/questions/{qid}").json()
    assert shown["question"]["status"] == "open" and shown["dr"] is None

    assert viewer.post(f"{P}/questions/{qid}/answer", json={"answer": "x"}).status_code == 403
    done = approver.post(
        f"{P}/questions/{qid}/answer", json={"answer": "Under two seconds.", "source": "Tanaka"}
    )
    assert done.status_code == 200, done.text
    body = done.json()
    me = approver.get("/api/me").json()["name"]
    assert (body["question"]["status"], body["question"]["answered_by"]) == ("answered", me)
    assert (body["dr"]["status"], body["dr"]["decision"], body["dr"]["approver"]) == (
        "approved",
        "Under two seconds.",
        me,
    )
    assert body["dr"]["rationale"] == "Tanaka"
    assert approver.get(f"{P}/questions?status=answered").json()[0]["id"] == qid


def test_the_client_cannot_name_who_answers(seeded_client: ClientFor) -> None:
    approver = seeded_client("approver")
    qid = first_question(approver)
    reply = approver.post(f"{P}/questions/{qid}/answer", json={"answer": "x", "answered_by": "bob"})
    assert reply.status_code == 422


def test_errors_are_mapped_like_the_other_routes(seeded_client: ClientFor) -> None:
    approver = seeded_client("approver")
    qid = first_question(approver)
    assert approver.get(f"{P}/questions/Q-9999").status_code == 404
    assert approver.get(f"{P}/questions/not-an-id").status_code == 404
    assert approver.post(f"{P}/questions/{qid}/answer", json={"answer": ""}).status_code == 422
    unsafe = approver.post(f"{P}/questions/{qid}/answer", json={"answer": "a </confirmed> b"})
    assert unsafe.status_code == 400
    assert approver.post(f"{P}/questions/{qid}/answer", json={"answer": "Fine."}).status_code == 200
    assert (
        approver.post(f"{P}/questions/{qid}/answer", json={"answer": "Again."}).status_code == 400
    )


def test_an_approver_withdraws_an_open_question(seeded_client: ClientFor) -> None:
    approver = seeded_client("approver")
    qid = first_question(approver)
    reply = approver.post(f"{P}/questions/{qid}/withdraw")
    assert reply.status_code == 200
    assert reply.json()["question"]["status"] == "withdrawn"
    assert approver.post(f"{P}/questions/{qid}/withdraw").status_code == 400
