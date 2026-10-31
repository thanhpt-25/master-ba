import datetime as dt
import json
from collections.abc import Callable

import pytest

from masterba.change import (
    LifecycleError,
    approve_dr,
    close_dr,
    dr_from_run,
    new_dr,
    reject_dr,
)
from masterba.change.lifecycle import mark_propagated, next_dr_id
from masterba.models.enums import DocType, DrStatus, DrTrigger, TeamRunStatus
from masterba.team import MessageType, Team
from masterba.trace_store import (
    NotFoundError,
    ProjectStore,
    get_decision_record,
    get_dr_extra,
    list_decision_records,
)

DAY = dt.date(2026, 10, 31)


def today() -> dt.date:
    return DAY


def propose(store: ProjectStore, *items: str) -> str:
    dr = new_dr(
        store,
        DrTrigger.REQUIREMENT_CHANGE,
        "Password reset must also work by SMS.",
        items or ("REQ-0002",),
        today,
    )
    return dr.id


def test_a_new_dr_is_proposed_with_its_affected_documents_and_one_commit(
    chain: ProjectStore, chain_commits: Callable[[], list[str]]
) -> None:
    dr = new_dr(chain, DrTrigger.REQUIREMENT_CHANGE, " Change it. ", ["REQ-0002"], today)
    assert (dr.id, dr.status, dr.date, dr.description) == (
        "DR-0001",
        DrStatus.PROPOSED,
        DAY,
        "Change it.",
    )
    assert dr.affected_documents[0] == "DOC-BRD-0001"
    assert len(dr.affected_documents) == 7
    assert chain_commits()[0] == "dr(PRJ-001): create DR-0001"
    assert get_decision_record(chain, "DR-0001") == dr


def test_dr_ids_are_sequential_and_items_are_normalised_and_deduplicated(
    chain: ProjectStore,
) -> None:
    propose(chain)
    dr = new_dr(chain, DrTrigger.DEFECT, "Bug", ["TC-IT-0002", "DOC-TEST_IT-0001#item.2"], today)
    assert dr.id == "DR-0002"
    assert dr.impacted_items == ["DOC-TEST_IT-0001#item.2"]
    assert next_dr_id(chain) == "DR-0003"


def test_a_dr_needs_a_description_known_items_and_items_unless_it_is_a_clarification(
    chain: ProjectStore,
) -> None:
    with pytest.raises(LifecycleError, match="description"):
        new_dr(chain, DrTrigger.DEFECT, "  ", ["REQ-0001"], today)
    with pytest.raises(LifecycleError, match="at least one --item"):
        new_dr(chain, DrTrigger.DEFECT, "Bug", [], today)
    with pytest.raises(NotFoundError):
        new_dr(chain, DrTrigger.DEFECT, "Bug", ["REQ-0099"], today)
    with pytest.raises(LifecycleError, match="documents"):
        new_dr(chain, DrTrigger.DEFECT, "Bug", ["DOC-SRS-0001"], today)
    clarification = new_dr(chain, DrTrigger.CLARIFICATION, "What is the limit?", [], today)
    assert clarification.impacted_items == []
    assert clarification.affected_documents == []


def test_approving_signs_the_dr_and_stores_the_impact_in_the_same_commit(
    chain: ProjectStore, chain_commits: Callable[[], list[str]]
) -> None:
    dr_id = propose(chain)
    approved, impact = approve_dr(chain, dr_id, " Ms. Sato ", "Go ahead", "Customer asked")
    assert (approved.status, approved.approver, approved.decision, approved.rationale) == (
        DrStatus.APPROVED,
        "Ms. Sato",
        "Go ahead",
        "Customer asked",
    )
    assert chain_commits()[0] == "dr(PRJ-001): approve DR-0001"
    stored = get_dr_extra(chain, dr_id, "impact")
    assert stored == impact.to_json()
    assert list(approved.affected_documents) == list(impact.documents)


def test_approving_needs_an_approver_and_a_decision_and_a_proposed_dr(chain: ProjectStore) -> None:
    dr_id = propose(chain)
    with pytest.raises(LifecycleError, match="approver and a decision"):
        approve_dr(chain, dr_id, "", "ok")
    with pytest.raises(LifecycleError, match="approver and a decision"):
        approve_dr(chain, dr_id, "Ms. Sato", "  ")
    assert get_decision_record(chain, dr_id).status is DrStatus.PROPOSED
    approve_dr(chain, dr_id, "Ms. Sato", "ok")
    with pytest.raises(LifecycleError, match="only a proposed DR can be approved"):
        approve_dr(chain, dr_id, "Ms. Sato", "ok")
    with pytest.raises(LifecycleError, match="only a proposed DR can be rejected"):
        reject_dr(chain, dr_id, "Ms. Sato", "no")


def test_rejecting_closes_the_dr_and_stores_no_impact(
    chain: ProjectStore, chain_commits: Callable[[], list[str]]
) -> None:
    dr_id = propose(chain)
    rejected = reject_dr(chain, dr_id, "Ms. Sato", "Out of scope", "Not funded")
    assert (rejected.status, rejected.decision) == (DrStatus.CLOSED, "Out of scope")
    assert chain_commits()[0] == "dr(PRJ-001): reject DR-0001"
    assert get_dr_extra(chain, dr_id, "impact") is None


def test_close_only_follows_propagation(
    chain: ProjectStore, chain_commits: Callable[[], list[str]]
) -> None:
    dr_id = propose(chain)
    with pytest.raises(LifecycleError, match="only a propagated DR can be closed"):
        close_dr(chain, dr_id)
    approved, _ = approve_dr(chain, dr_id, "Ms. Sato", "ok")
    with pytest.raises(LifecycleError, match="only a propagated DR can be closed"):
        close_dr(chain, dr_id)
    mark_propagated(chain, approved)
    assert chain_commits()[0] == "dr(PRJ-001): propagate DR-0001"
    closed = close_dr(chain, dr_id)
    assert closed.status is DrStatus.CLOSED
    assert chain_commits()[0] == "dr(PRJ-001): close DR-0001"
    assert [r.id for r in list_decision_records(chain)] == ["DR-0001"]


def escalated_run(store: ProjectStore, *lines: str) -> str:
    team = Team.open(store, DocType.BASIC_DESIGN, 3, None)
    team.begin_round()
    team.escalate(list(lines))
    team.post(
        "tester",
        "designer",
        MessageType.QUESTION,
        "DOC-SRS-0001#item.2",
        "How long is the link valid?",
    )
    team.finish(TeamRunStatus.ESCALATED)
    return team.run_id


def test_a_clarification_dr_is_made_from_an_escalated_run(chain: ProjectStore) -> None:
    run_id = escalated_run(
        chain,
        "max rounds reached (3)",
        "question DOC-SRS-0001#item.1: What are the password limits?",
        "question DOC-BASIC_DESIGN-0009#item.4: unknown draft item",
    )
    dr = dr_from_run(chain, run_id, today)
    assert dr.trigger is DrTrigger.CLARIFICATION
    assert dr.status is DrStatus.PROPOSED
    assert run_id in dr.description
    assert "- max rounds reached (3)" in dr.description
    assert dr.impacted_items == ["DOC-SRS-0001#item.2", "DOC-SRS-0001#item.1"]
    assert "DOC-SRS-0001" in dr.affected_documents


def test_only_an_escalated_run_can_become_a_dr(chain: ProjectStore) -> None:
    team = Team.open(chain, DocType.SRS, 3, None)
    team.finish(TeamRunStatus.DONE)
    with pytest.raises(LifecycleError, match="only an escalated run needs a DR"):
        dr_from_run(chain, team.run_id, today)
    with pytest.raises(NotFoundError):
        dr_from_run(chain, "RUN-0099", today)


def test_the_dr_file_is_stable_json(chain: ProjectStore) -> None:
    dr_id = propose(chain)
    text = (chain.path / "decision-records" / f"{dr_id}.json").read_text("utf-8")
    assert json.loads(text)["status"] == "proposed"
    assert text.endswith("\n")
