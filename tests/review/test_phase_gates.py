"""Phase review gates (spec 15 sections 3 to 6)."""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from factories import draft_for, intake_path, login_srs_draft, make_config, qa_pass
from masterba.change import PatchOp, RevisionPatch
from masterba.llm import FakeLLM
from masterba.models import ReviewComment, payload_items
from masterba.models.enums import DocStatus, DrStatus, DrTrigger, ReviewDecision, ReviewStage
from masterba.pipeline import run_brd, run_srs
from masterba.review import ReviewError, phase_state
from masterba.review.actions import approve_phase, parse_comment, reject_phase
from masterba.trace_store import (
    ProjectStore,
    create_project,
    get_decision_record,
    get_document,
    get_review,
    list_questions,
)

TEMPLATES = Path(__file__).parents[2] / "templates"
LOGIN = "login_system.txt"
SRS = "DOC-SRS-0001"


def gated(projects_root: Path, max_rounds: int = 3) -> ProjectStore:
    config = make_config(max_rounds=max_rounds).model_copy(update={"review_gates": True})
    return create_project(projects_root, config)


def with_brd(store: ProjectStore) -> ProjectStore:
    run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    return store


def with_srs(store: ProjectStore) -> ProjectStore:
    with_brd(store)
    approve_phase(store, TEMPLATES, ReviewStage.BRD, "alice")
    run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), qa_pass()]))
    return store


def revise(item: str, statement: str) -> RevisionPatch:
    op = PatchOp(op="update", item_id=item, fields={"statement": statement}, reason="review")
    return RevisionPatch(operations=[op], summary="as the review asks")


def test_a_done_stage_waits_for_review_and_the_next_stage_refuses_to_start(
    projects_root: Path, commit_log: Callable[[], list[str]]
) -> None:
    store = with_brd(gated(projects_root))
    assert get_document(store, "DOC-BRD-0001")[0].status is DocStatus.IN_REVIEW
    assert phase_state(store, ReviewStage.BRD) == "in_review"
    runs, commits = sorted((store.path / "runs").iterdir()), commit_log()
    llm = FakeLLM([])
    with pytest.raises(ReviewError, match="DOC-BRD-0001 v1 is in_review") as refused:
        run_srs(store, TEMPLATES, llm)
    assert "masterba review approve --project PRJ-001 --stage brd --by NAME" in str(refused.value)
    assert llm.calls == [] and commit_log() == commits
    assert sorted((store.path / "runs").iterdir()) == runs


def test_approval_opens_the_next_stage_and_records_the_open_questions(
    projects_root: Path, commit_log: Callable[[], list[str]]
) -> None:
    store = with_brd(gated(projects_root))
    open_ids = [q.id for q in list_questions(store) if q.status.value == "open"]
    assert open_ids, "the login BRD raises customer questions"
    review = approve_phase(store, TEMPLATES, ReviewStage.BRD, "alice")
    assert (review.id, review.decision, review.by) == ("REV-0001", ReviewDecision.APPROVED, "alice")
    assert review.open_questions == open_ids
    assert get_document(store, "DOC-BRD-0001")[0].status is DocStatus.APPROVED
    assert "review(PRJ-001): approve brd (DOC-BRD-0001 v1)" in commit_log()
    assert commit_log()[0] == "render(PRJ-001): xlsx DOC-BRD-0001 v1"  # status is printed
    result = run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), qa_pass()]))
    assert result.status.value == "done"
    assert get_document(store, SRS)[0].status is DocStatus.IN_REVIEW


def test_a_rejection_revises_the_phase_into_a_new_version_for_review(
    projects_root: Path,
) -> None:
    store = with_srs(gated(projects_root))
    _, before = get_document(store, SRS, 1)
    comment = parse_comment(f"{SRS}#item.1: Name the login identifier explicitly.")
    reviser = FakeLLM(
        [revise(f"{SRS}#item.1", "The system shall log users in by e-mail."), qa_pass()]
    )
    review, result = reject_phase(store, TEMPLATES, ReviewStage.SRS, "bob", [comment], reviser)
    assert not result.escalated and result.status is DrStatus.PROPAGATED
    dr = get_decision_record(store, review.dr_id or "")
    assert dr.trigger is DrTrigger.REVIEW_FEEDBACK and dr.approver == "bob"
    assert dr.impacted_items == [f"{SRS}#item.1"] and dr.affected_documents == [SRS]
    assert "Name the login identifier explicitly." in reviser.calls[0].user
    assert get_document(store, SRS, 1)[0].status is DocStatus.SUPERSEDED
    revised, after = get_document(store, SRS, 2)
    assert revised.status is DocStatus.IN_REVIEW
    assert {i.item_id for i in payload_items(before)} <= {i.item_id for i in payload_items(after)}
    assert get_review(store, review.id).revision_run == result.documents[0].run_id
    approve_phase(store, TEMPLATES, ReviewStage.SRS, "alice")  # the new version is reviewed
    assert get_document(store, SRS)[0].status is DocStatus.APPROVED


def test_an_escalated_revision_keeps_the_rejected_version_in_review(projects_root: Path) -> None:
    store = with_srs(gated(projects_root, max_rounds=1))
    bad = RevisionPatch(
        operations=[
            PatchOp(op="update", item_id=f"{SRS}#item.1", fields={"colour": "red"}, reason="x")
        ],
        summary="bad",
    )
    review, result = reject_phase(
        store, TEMPLATES, ReviewStage.SRS, "bob", [ReviewComment(text="Too vague.")], FakeLLM([bad])
    )
    assert result.escalated
    assert get_review(store, review.id).revision_run == result.documents[0].run_id
    doc, _ = get_document(store, SRS)
    assert (doc.version, doc.status) == (1, DocStatus.IN_REVIEW)


def test_only_a_phase_in_review_can_be_approved_or_rejected(projects_root: Path) -> None:
    store = with_brd(gated(projects_root))
    with pytest.raises(ReviewError, match="no DOC-SRS-0001"):
        approve_phase(store, TEMPLATES, ReviewStage.SRS, "alice")
    with pytest.raises(ReviewError, match="say who reviews"):
        approve_phase(store, TEMPLATES, ReviewStage.BRD, " ")
    with pytest.raises(ReviewError, match="needs at least one comment"):
        reject_phase(store, TEMPLATES, ReviewStage.BRD, "bob", [], FakeLLM([]))
    with pytest.raises(ReviewError, match="not active items"):
        reject_phase(
            store,
            TEMPLATES,
            ReviewStage.BRD,
            "bob",
            [parse_comment("DOC-BRD-0001#item.99: x")],
            FakeLLM([]),
        )
    approve_phase(store, TEMPLATES, ReviewStage.BRD, "alice")
    with pytest.raises(ReviewError, match="DOC-BRD-0001 v1 is approved"):
        approve_phase(store, TEMPLATES, ReviewStage.BRD, "alice")
    run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), qa_pass()]))
    with pytest.raises(ReviewError, match="the srs phase has started"):
        approve_phase(store, TEMPLATES, ReviewStage.BRD, "alice")


def test_without_gates_documents_stay_drafts_and_nothing_is_gated(store: ProjectStore) -> None:
    with_brd(store)
    assert get_document(store, "DOC-BRD-0001")[0].status is DocStatus.DRAFT
    assert run_srs(store, TEMPLATES, FakeLLM([login_srs_draft(), qa_pass()])).status.value == "done"
    stored = json.loads((store.path / "project.json").read_text("utf-8"))
    assert stored["review_gates"] is False


def test_comment_parsing() -> None:
    assert parse_comment("DOC-SRS-0001#item.3: Split it.") == ReviewComment(
        ref="DOC-SRS-0001#item.3", text="Split it."
    )
    assert parse_comment("  The whole SRS is too vague. ") == ReviewComment(
        text="The whole SRS is too vague."
    )
