from factories import (
    incomplete_srs_draft,
    login_srs_draft,
    make_brd,
    make_brd_item,
    make_requirement,
    srs_item,
)
from masterba.agents import (
    BrdRequirement,
    SrsDraft,
    SrsOpenQuestion,
    brd_requirements,
    validate_srs_draft,
    write_srs,
)
from masterba.agents.srs_writer import brd_view, draft_view
from masterba.llm import FakeLLM
from masterba.models import BrdItem, RequirementItem
from masterba.models.enums import DocLanguage, ItemStatus, ReqCategory, Scope, SrsKind

BRD_DOC = "DOC-BRD-0001"
SRS_DOC = "DOC-SRS-0001"


def brd_fixture() -> tuple[list[RequirementItem], list[BrdItem]]:
    reqs = [make_requirement(n) for n in range(1, 5)]
    reqs[2] = reqs[2].model_copy(update={"category": ReqCategory.NON_FUNCTIONAL})
    items = [
        make_brd_item(BRD_DOC, 1, req="REQ-0001"),
        make_brd_item(BRD_DOC, 2, req="REQ-0002", status=ItemStatus.REMOVED),
        make_brd_item(BRD_DOC, 3, req="REQ-0003"),
        make_brd_item(BRD_DOC, 4, req="REQ-0004").model_copy(update={"scope": Scope.OUT}),
    ]
    return reqs, items


def brd_reqs() -> list[BrdRequirement]:
    reqs, items = brd_fixture()
    return brd_requirements(make_brd(*items), reqs)


def test_only_active_in_scope_requirements_are_given_to_the_writer() -> None:
    reqs = brd_reqs()
    assert [r.req_id for r in reqs] == ["REQ-0001", "REQ-0003"]
    assert reqs[1].category is ReqCategory.NON_FUNCTIONAL
    assert brd_view(reqs).splitlines()[1].startswith("REQ-0003 [non_functional] Requirement 3:")


def cover(*ids: str, statement: str = "The system shall do it.") -> SrsDraft:
    return SrsDraft(items=[srs_item(SrsKind.FUNCTIONAL, f"{statement} {i}", [i]) for i in ids])


def test_a_draft_that_covers_every_requirement_is_accepted() -> None:
    assert validate_srs_draft(cover("REQ-0001", "REQ-0003"), brd_reqs(), DocLanguage.EN) == []


def test_citing_an_unknown_removed_or_out_of_scope_requirement_is_rejected() -> None:
    errors = validate_srs_draft(
        cover("REQ-0001", "REQ-0003", "REQ-0002", "REQ-0004", "REQ-0099"), brd_reqs()
    )
    assert errors == [
        f"item {n}: {req} is not an in-scope BRD requirement"
        for n, req in [(3, "REQ-0002"), (4, "REQ-0004"), (5, "REQ-0099")]
    ]


def test_every_in_scope_requirement_must_be_covered() -> None:
    errors = validate_srs_draft(cover("REQ-0001"), brd_reqs())
    assert errors == ["in-scope requirements not covered by any item: REQ-0003"]


def test_duplicate_statements_are_rejected_after_normalising() -> None:
    first = srs_item(SrsKind.FUNCTIONAL, "The system  shall sign in.", ["REQ-0001"])
    second = srs_item(SrsKind.FUNCTIONAL, "the system shall SIGN IN.", ["REQ-0003"])
    errors = validate_srs_draft(SrsDraft(items=[first, second]), brd_reqs())
    assert errors == ["item 2: statement duplicates item 1"]


def test_the_language_check_applies_to_statements_and_hints() -> None:
    japanese = srs_item(
        SrsKind.FUNCTIONAL, "システムは顧客のサインインを許可すること。", ["REQ-0001"]
    )
    other = srs_item(SrsKind.FUNCTIONAL, "システムはAPIを提供すること。", ["REQ-0003"], "確認する")
    draft = SrsDraft(items=[japanese, other])
    assert validate_srs_draft(draft, brd_reqs(), DocLanguage.JA) == []
    en = validate_srs_draft(draft, brd_reqs(), DocLanguage.EN)
    assert len(en) == 3
    assert all("must be written in English" in e for e in en)
    english = validate_srs_draft(cover("REQ-0001", "REQ-0003"), brd_reqs(), DocLanguage.JA)
    assert len(english) == 2


def test_draft_view_numbers_items_with_their_final_refs() -> None:
    view = draft_view(login_srs_draft(), SRS_DOC).splitlines()
    assert view[0].startswith(f"{SRS_DOC}#item.1 [functional] The system shall let a registered")
    assert "| acceptance: Sign in with valid credentials" in view[0]
    assert view[0].endswith("(from REQ-0001)")
    assert "acceptance" not in view[2]


def test_first_call_sends_only_the_brd() -> None:
    llm = FakeLLM([cover("REQ-0001", "REQ-0003")])
    write_srs(llm, brd_reqs(), DocLanguage.EN, None, [], SRS_DOC, system_prompt="BASE")
    call = llm.calls[0]
    assert call.tool_name == "submit_srs"
    assert call.system.startswith("BASE")
    assert "English" in call.system
    assert call.user.startswith("<brd>\nREQ-0001 [functional]")
    assert "previous_draft" not in call.user


def test_revision_call_includes_the_previous_draft_and_the_feedback() -> None:
    previous = incomplete_srs_draft()
    llm = FakeLLM([login_srs_draft()])
    write_srs(
        llm, brd_reqs(), DocLanguage.JA, previous, ["[SRS-01] DOC-SRS-0001#item.2: Split."], SRS_DOC
    )
    user = llm.calls[0].user
    assert "<previous_draft>" in user
    assert f"{SRS_DOC}#item.2" in user
    assert "- [SRS-01] DOC-SRS-0001#item.2: Split." in user
    assert "日本語" in llm.calls[0].system


def test_open_questions_must_name_in_scope_requirements_and_follow_the_language() -> None:
    questions = [
        SrsOpenQuestion(question="What availability figure applies?", req_ids=["REQ-0003"]),
        SrsOpenQuestion(question="Unknown requirement?", req_ids=["REQ-0002", "REQ-0099"]),
    ]
    draft = cover("REQ-0001", "REQ-0003").model_copy(update={"open_questions": questions})
    assert validate_srs_draft(draft, brd_reqs(), DocLanguage.EN) == [
        "open question 2: REQ-0002 is not an in-scope BRD requirement",
        "open question 2: REQ-0099 is not an in-scope BRD requirement",
    ]
    in_japanese = validate_srs_draft(draft, brd_reqs(), DocLanguage.JA)
    assert any("open question 1: text must be written in Japanese" in e for e in in_japanese)


def test_the_reviewer_sees_the_open_questions_in_the_draft_view() -> None:
    question = SrsOpenQuestion(question="What availability figure applies?", req_ids=["REQ-0003"])
    draft = login_srs_draft().model_copy(update={"open_questions": [question]})
    view = draft_view(draft, SRS_DOC).splitlines()
    assert view[-2] == "Open questions the writer raised for the customer (not requirements):"
    assert view[-1] == "- REQ-0003: What availability figure applies?"
