"""Propagating several approved DRs at once (spec 07 section 5.2)."""

import datetime as dt
from pathlib import Path
from typing import Any

import pytest

from masterba.change import (
    BatchEntry,
    BatchResult,
    PatchOp,
    RevisionPatch,
    approve_dr,
    approved_dr_ids,
    batch,
    new_dr,
    propagate_many,
)
from masterba.llm import LLM, FakeLLM
from masterba.models import DecisionRecord
from masterba.models.enums import DrStatus, DrTrigger
from masterba.team import PROGRESS
from masterba.trace_store import ProjectStore, get_decision_record

TEMPLATES = Path(__file__).parents[2] / "templates"
UT = "DOC-TEST_UT-0001"
IT = "DOC-TEST_IT-0001"
EMPTY = RevisionPatch(operations=[], summary="nothing to change")


def bad_patch() -> RevisionPatch:
    """A patch the gate refuses: three of them escalate a document."""
    op = PatchOp(op="update", item_id="DOC-BRD-0001#item.2", fields={"colour": "red"}, reason="x")
    return RevisionPatch(operations=[op], summary="bad")


def approved(store: ProjectStore, item: str = "REQ-0002") -> DecisionRecord:
    dr = new_dr(store, DrTrigger.REQUIREMENT_CHANGE, f"Change {item}.", [item], dt.date.today)
    return approve_dr(store, dr.id, "Ms. Sato", "Go ahead.")[0]


def only(store: ProjectStore, doc_id: str) -> DecisionRecord:
    """A DR whose only affected document is the given test specification."""
    dr = approved(store, f"{doc_id}#item.1")
    assert dr.affected_documents == [doc_id]
    return dr


def test_drs_run_oldest_first_and_all_end_propagated(chain: ProjectStore) -> None:
    first, second = approved(chain), approved(chain)
    lines: list[str] = []
    token = PROGRESS.set(lines.append)
    try:
        llm = FakeLLM([EMPTY] * 14)
        result = propagate_many(chain, TEMPLATES, [second.id, first.id, second.id], llm)
    finally:
        PROGRESS.reset(token)

    assert [(e.dr_id, e.outcome) for e in result.entries] == [
        (first.id, "propagated"),
        (second.id, "propagated"),
    ]
    assert result.status == "done" and not result.stopped
    for dr in (first, second):
        assert get_decision_record(chain, dr.id).status is DrStatus.PROPAGATED
    assert f"{first.id}: propagating (1/2)" in lines
    assert f"{second.id}: propagated" in lines
    data = result.to_json()
    assert data["status"] == "done"
    assert data["results"][0]["propagation"]["status"] == "propagated"


def test_a_stopped_dr_skips_only_later_drs_on_the_same_documents(chain: ProjectStore) -> None:
    stuck, same, other = only(chain, UT), approved(chain), only(chain, IT)
    llm = FakeLLM([bad_patch()] * 3 + [EMPTY])
    result = propagate_many(chain, TEMPLATES, [stuck.id, same.id, other.id], llm)

    by_id = {e.dr_id: e for e in result.entries}
    assert by_id[stuck.id].outcome == "escalated"
    assert by_id[same.id].outcome == "skipped"
    assert by_id[same.id].blocked_by == stuck.id
    assert by_id[other.id].outcome == "propagated"
    assert result.status == "escalated" and result.stopped
    assert get_decision_record(chain, stuck.id).status is DrStatus.APPROVED
    assert get_decision_record(chain, same.id).status is DrStatus.APPROVED


def test_a_dr_that_is_not_approved_fails_alone(chain: ProjectStore) -> None:
    proposed = new_dr(chain, DrTrigger.REQUIREMENT_CHANGE, "Not yet.", ["REQ-0002"], dt.date.today)
    later = approved(chain)
    result = propagate_many(chain, TEMPLATES, [proposed.id, later.id], FakeLLM([EMPTY] * 7))

    assert [(e.dr_id, e.outcome) for e in result.entries] == [
        (proposed.id, "failed"),
        (later.id, "propagated"),
    ]
    assert "only an approved DR" in (result.entries[0].error or "")


def test_an_unexpected_error_is_reported_and_holds_back_the_same_documents(
    chain: ProjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    broken, same, other = only(chain, UT), approved(chain), only(chain, IT)
    real = getattr(batch, "propagate_dr")  # noqa: B009

    def flaky(store: ProjectStore, root: Path, dr_id: str, llm: LLM, **kw: Any) -> Any:
        if dr_id == broken.id:
            raise OSError("disk full")
        return real(store, root, dr_id, llm, **kw)

    monkeypatch.setattr(batch, "propagate_dr", flaky)
    result = propagate_many(chain, TEMPLATES, [broken.id, same.id, other.id], FakeLLM([EMPTY]))
    assert [(e.dr_id, e.outcome, e.blocked_by) for e in result.entries] == [
        (broken.id, "failed", None),
        (same.id, "skipped", broken.id),
        (other.id, "propagated", None),
    ]
    assert result.entries[0].error == "OSError: disk full"


def test_the_stop_hook_skips_the_rest(chain: ProjectStore) -> None:
    first, second = approved(chain), approved(chain)
    calls: list[int] = []

    def stop() -> str | None:
        calls.append(1)
        return "usage limit reached" if len(calls) > 1 else None

    result = propagate_many(
        chain, TEMPLATES, [first.id, second.id], FakeLLM([EMPTY] * 7), stop=stop
    )
    assert [(e.outcome, e.error) for e in result.entries] == [
        ("propagated", None),
        ("skipped", "usage limit reached"),
    ]


def test_waiting_only_gives_waiting_for_input() -> None:
    batch = BatchResult(
        (BatchEntry("DR-0001", "propagated"), BatchEntry("DR-0002", "waiting_for_input"))
    )
    assert batch.status == "waiting_for_input"
    assert BatchResult(()).status == "done"
    # Seen live: a DR waiting for an answer, and the DR on the same documents skipped behind it.
    behind = BatchResult(
        (
            BatchEntry("DR-0053", "waiting_for_input"),
            BatchEntry("DR-0054", "skipped", error="shares", blocked_by="DR-0053"),
        )
    )
    assert behind.status == "waiting_for_input"
    limited = BatchResult((BatchEntry("DR-0001", "skipped", error="usage limit reached"),))
    assert limited.status == "escalated"
    failed = BatchResult((BatchEntry("DR-0001", "failed", error="x"),))
    assert failed.status == "escalated"


def test_approved_dr_ids_lists_approved_records_with_an_impact(chain: ProjectStore) -> None:
    new_dr(chain, DrTrigger.REQUIREMENT_CHANGE, "Proposed only.", ["REQ-0002"], dt.date.today)
    one, two = approved(chain), approved(chain)
    propagate_many(chain, TEMPLATES, [one.id], FakeLLM([EMPTY] * 7))
    assert approved_dr_ids(chain) == [two.id]
