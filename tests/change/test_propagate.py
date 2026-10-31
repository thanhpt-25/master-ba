import datetime as dt
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from openpyxl import load_workbook
from pydantic import BaseModel

from factories import qa_block, qa_pass
from masterba.change import (
    LifecycleError,
    PatchOp,
    RevisionPatch,
    approve_dr,
    close_dr,
    dr_diff,
    new_dr,
    propagate_dr,
    reject_dr,
    rows,
)
from masterba.llm import FakeLLM
from masterba.models import BrdContent, DecisionRecord
from masterba.models.enums import DrStatus, DrTrigger
from masterba.trace_store import (
    ProjectStore,
    get_decision_record,
    get_document,
    get_dr_extra,
    get_requirement,
    get_trace_links,
)

TEMPLATES = Path(__file__).parents[2] / "templates"
BRD2 = "DOC-BRD-0001#item.2"
DOCS = [
    "DOC-BRD-0001",
    "DOC-SRS-0001",
    "DOC-BASIC_DESIGN-0001",
    "DOC-TEST_IT-0001",
    "DOC-TEST_ST-0001",
    "DOC-DETAIL_DESIGN-0001",
    "DOC-TEST_UT-0001",
]
SMS = "Customers who forget the password must be able to reset it by SMS or by email."


def update(item_id: str, **fields: object) -> PatchOp:
    return PatchOp(op="update", item_id=item_id, fields=fields, reason="DR-0001")


def patch(*ops: PatchOp) -> RevisionPatch:
    return RevisionPatch(operations=list(ops), summary="done")


EMPTY = patch()


def proposed(store: ProjectStore, item: str = "REQ-0002") -> DecisionRecord:
    return new_dr(
        store, DrTrigger.REQUIREMENT_CHANGE, "Password reset by SMS too.", [item], dt.date.today
    )


def approved(store: ProjectStore, item: str = "REQ-0002") -> DecisionRecord:
    dr = proposed(store, item)
    return approve_dr(store, dr.id, "Ms. Sato", "Approved for release 2.")[0]


def full_script() -> list[BaseModel | Exception]:
    """Reviser and QA answers for the seven documents of the demo chain, in V order."""
    return [
        patch(update(BRD2, description=SMS)),
        qa_pass(),
        patch(
            update(
                "DOC-SRS-0001#item.2",
                statement="The system shall let a customer reset a forgotten password by e-mail.",
            )
        ),
        qa_pass(),
        patch(
            update(
                "DOC-BASIC_DESIGN-0001#item.3", description="Sends a reset link by email or SMS."
            )
        ),
        qa_pass(),
        patch(update("DOC-TEST_IT-0001#item.3", expected="A reset link is sent by email or SMS.")),
        qa_pass(),
        EMPTY,
        patch(
            update(
                "DOC-DETAIL_DESIGN-0001#item.3",
                spec="requestReset(contact) sends a link by email or SMS.",
            )
        ),
        qa_pass(),
        EMPTY,
    ]


def bad_patch() -> RevisionPatch:
    return patch(update(BRD2, colour="red"))


def raw(store: ProjectStore, doc_id: str, version: int) -> bytes:
    kind = doc_id.split("-", 1)[1].rsplit("-", 1)[0].lower()
    return (store.path / "json" / kind / f"{doc_id}.v{version}.json").read_bytes()


def test_a_requirement_change_revises_exactly_the_affected_documents(
    chain: ProjectStore, chain_commits: Callable[[], list[str]]
) -> None:
    dr = approved(chain)
    before = {doc: raw(chain, doc, 1) for doc in DOCS}
    links_before = get_trace_links(chain)
    llm = FakeLLM(full_script())
    result = propagate_dr(chain, TEMPLATES, dr.id, llm)

    assert result.status is DrStatus.PROPAGATED
    assert [(d.doc_id, d.outcome, d.version) for d in result.documents] == [
        (DOCS[0], "revised", 2),
        (DOCS[1], "revised", 2),
        (DOCS[2], "revised", 2),
        (DOCS[3], "revised", 2),
        (DOCS[4], "unchanged", None),
        (DOCS[5], "revised", 2),
        (DOCS[6], "unchanged", None),
    ]
    assert get_decision_record(chain, dr.id).status is DrStatus.PROPAGATED
    for doc in DOCS:
        assert raw(chain, doc, 1) == before[doc]
    assert get_document(chain, DOCS[4])[0].version == 1
    assert get_document(chain, DOCS[0])[0].version == 2

    _, brd = get_document(chain, DOCS[0])
    _, brd_v1 = get_document(chain, DOCS[0], 1)
    assert isinstance(brd, BrdContent)
    assert isinstance(brd_v1, BrdContent)
    assert brd.items[1].description == SMS
    for n in (0, 2, 3, 4):
        assert brd.items[n] == brd_v1.items[n]
    assert get_requirement(chain, "REQ-0002").text == SMS
    assert get_trace_links(chain) == links_before
    for doc, kind in ((DOCS[0], "brd"), (DOCS[2], "basic_design"), (DOCS[5], "detail_design")):
        assert (chain.path / "xlsx" / kind / f"{doc}.v2.xlsx").exists()
    assert not (chain.path / "xlsx" / "test_st" / f"{DOCS[4]}.v2.xlsx").exists()
    assert (
        load_workbook(chain.path / "xlsx" / "brd" / f"{DOCS[0]}.v2.xlsx")["業務要件"]["E9"].value
        == SMS
    )

    progress = get_dr_extra(chain, dr.id, "propagation")
    assert progress is not None
    assert progress["documents"][DOCS[4]] == {
        "outcome": "unchanged",
        "version": None,
        "run_id": "RUN-0009",
    }
    commits = chain_commits()
    assert commits[0] == "dr(PRJ-001): propagate DR-0001"
    assert commits[1] == f"dr(PRJ-001): propagate DR-0001 {DOCS[6]}"
    assert "dr(PRJ-001): propagate DR-0001 DOC-BRD-0001" in commits

    qa_systems = [c.system for c in llm.calls if c.tool_name == "submit_qa_report"]
    assert [
        next(s for s in ("BRD-01", "SRS-01", "BD-01", "TS-01", "DD-01") if s in system)
        for system in qa_systems
    ] == [
        "BRD-01",
        "SRS-01",
        "BD-01",
        "TS-01",
        "DD-01",
    ]
    brd_prompt = next(c.user for c in llm.calls if c.tool_name == "submit_patch")
    assert f"<focus_items>\n{BRD2}" in brd_prompt
    srs_prompt = [c.user for c in llm.calls if c.tool_name == "submit_patch"][1]
    assert "DOC-BRD-0001 v2: DOC-BRD-0001#item.2 field_changed description" in srs_prompt


def test_every_revision_is_a_recorded_team_run_triggered_by_the_dr(chain: ProjectStore) -> None:
    dr = approved(chain)
    propagate_dr(chain, TEMPLATES, dr.id, FakeLLM(full_script()))
    summaries = [
        json.loads((chain.path / "runs" / f"RUN-{n:04d}" / "team-summary.json").read_text("utf-8"))
        for n in range(5, 12)
    ]
    assert [s["trigger"] for s in summaries] == ["DR-0001"] * 7
    assert [s["stage"] for s in summaries] == [
        "BRD",
        "SRS",
        "BASIC_DESIGN",
        "TEST_IT",
        "TEST_ST",
        "DETAIL_DESIGN",
        "TEST_UT",
    ]
    assert {s["status"] for s in summaries} == {"done"}


def test_the_diff_shows_changed_rows_with_their_classification(chain: ProjectStore) -> None:
    dr = approved(chain)
    propagate_dr(chain, TEMPLATES, dr.id, FakeLLM(full_script()))
    diffs = {d.doc_id: d for d in dr_diff(chain, dr.id)}
    assert set(diffs) == {DOCS[0], DOCS[1], DOCS[2], DOCS[3], DOCS[5]}
    brd_row = rows(diffs[DOCS[0]])[0]
    assert (brd_row["item_id"], brd_row["field"], brd_row["classification"]) == (
        BRD2,
        "description",
        "structural_change",
    )
    assert rows(diffs[DOCS[1]])[0]["classification"] == "reworded_only"
    structural = {d.doc_id for d in dr_diff(chain, dr.id, structural_only=True) if d.changes}
    assert DOCS[1] not in structural
    assert DOCS[0] in structural


def test_an_escalated_document_stops_the_propagation_and_a_rerun_retries_it(
    chain: ProjectStore,
) -> None:
    dr = approved(chain)
    first = propagate_dr(chain, TEMPLATES, dr.id, FakeLLM([bad_patch()] * 3))
    assert first.escalated
    assert [(d.doc_id, d.outcome) for d in first.documents] == [(DOCS[0], "escalated")]
    assert first.documents[0].escalations[0] == "max rounds reached (3)"
    assert get_decision_record(chain, dr.id).status is DrStatus.APPROVED
    assert get_dr_extra(chain, dr.id, "propagation") is None
    assert get_document(chain, DOCS[0])[0].version == 1

    second = propagate_dr(chain, TEMPLATES, dr.id, FakeLLM(full_script()))
    assert second.status is DrStatus.PROPAGATED
    assert second.documents[0].run_id == "RUN-0006"


def test_a_rerun_skips_the_documents_that_are_already_done(chain: ProjectStore) -> None:
    dr = approved(chain)
    script = full_script()
    stalled = FakeLLM([*script[:2], bad_patch(), bad_patch(), bad_patch()])
    first = propagate_dr(chain, TEMPLATES, dr.id, stalled)
    assert [(d.doc_id, d.outcome) for d in first.documents] == [
        (DOCS[0], "revised"),
        (DOCS[1], "escalated"),
    ]
    progress = get_dr_extra(chain, dr.id, "propagation")
    assert progress is not None
    assert set(progress["documents"]) == {DOCS[0]}

    rest = FakeLLM(script[2:])
    second = propagate_dr(chain, TEMPLATES, dr.id, rest)
    assert second.status is DrStatus.PROPAGATED
    assert [d.outcome for d in second.documents][0] == "revised"
    assert get_document(chain, DOCS[0])[0].version == 2
    srs_call = next(c for c in rest.calls if c.tool_name == "submit_patch")
    assert "<focus_items>\nDOC-SRS-0001#item.2" in srs_call.user
    assert "DOC-BRD-0001 v2" in srs_call.user


def test_qa_feedback_on_a_patch_sends_the_reviser_back(chain: ProjectStore) -> None:
    dr = approved(chain)
    blocked = qa_block("BRD-06", BRD2, "Contradicts item 3.")
    script = [
        patch(update(BRD2, description="x" * 30)),
        blocked,
        patch(update(BRD2, description=SMS)),
        qa_pass(),
        *[EMPTY] * 6,
    ]
    llm = FakeLLM(script)
    result = propagate_dr(chain, TEMPLATES, dr.id, llm)
    assert result.status is DrStatus.PROPAGATED
    assert "Contradicts item 3." in llm.calls[2].user
    mailbox = json.loads((chain.path / "runs" / "RUN-0005" / "mailbox.json").read_text("utf-8"))
    assert [(m["sender"], m["ref"]) for m in mailbox] == [("qa", BRD2)]
    assert get_requirement(chain, "REQ-0002").text == SMS


def test_no_patch_means_no_new_version_anywhere(chain: ProjectStore) -> None:
    dr = approved(chain)
    result = propagate_dr(chain, TEMPLATES, dr.id, FakeLLM([EMPTY] * 7))
    assert result.status is DrStatus.PROPAGATED
    assert {d.outcome for d in result.documents} == {"unchanged"}
    for doc in DOCS:
        assert get_document(chain, doc)[0].version == 1
    assert dr_diff(chain, dr.id) == []


def test_a_new_requirement_enters_through_a_brd_add(chain: ProjectStore) -> None:
    dr = approved(chain, "REQ-0001")
    add = PatchOp(
        op="add",
        fields={"title": "SMS reset", "description": SMS, "scope": "in", "category": "functional"},
        reason="DR-0001",
    )
    llm = FakeLLM([patch(add), qa_pass(), *[EMPTY] * 6])
    result = propagate_dr(chain, TEMPLATES, dr.id, llm)
    assert result.status is DrStatus.PROPAGATED
    assert get_requirement(chain, "REQ-0006").text == SMS
    _, brd = get_document(chain, DOCS[0])
    assert isinstance(brd, BrdContent)
    assert [i.item_id for i in brd.items][-1] == "DOC-BRD-0001#item.6"
    assert brd.items[-1].source_ref == "DR-0001"
    assert any(
        link.from_id == "REQ-0006" and link.to_id == "DOC-BRD-0001#item.6"
        for link in get_trace_links(chain)
    )


def test_only_an_approved_dr_can_be_propagated(chain: ProjectStore) -> None:
    dr = proposed(chain)
    llm = FakeLLM([])
    with pytest.raises(LifecycleError, match="only an approved DR can be propagated"):
        propagate_dr(chain, TEMPLATES, dr.id, llm)
    reject_dr(chain, dr.id, "Ms. Sato", "No")
    with pytest.raises(LifecycleError, match="is closed"):
        propagate_dr(chain, TEMPLATES, dr.id, llm)
    assert llm.calls == []
    assert not (chain.path / "runs" / "RUN-0005").exists()


def test_a_propagated_dr_cannot_be_propagated_again_and_can_then_be_closed(
    chain: ProjectStore,
) -> None:
    dr = approved(chain)
    propagate_dr(chain, TEMPLATES, dr.id, FakeLLM([EMPTY] * 7))
    with pytest.raises(LifecycleError, match="is propagated"):
        propagate_dr(chain, TEMPLATES, dr.id, FakeLLM([]))
    assert close_dr(chain, dr.id).status is DrStatus.CLOSED
