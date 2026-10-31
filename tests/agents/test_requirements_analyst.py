import pytest
from pydantic import ValidationError

from factories import bad_draft, draft_for, draft_req, intake_path
from masterba.agents import (
    BrdDraft,
    OpenQuestion,
    brd_draft_view,
    load_system_prompt,
    uncovered_lines,
    validate_draft,
    write_brd,
)
from masterba.agents.requirements_analyst import number_lines
from masterba.llm import FakeLLM
from masterba.models.enums import DocLanguage, ReqCategory

EN, JA = DocLanguage.EN, DocLanguage.JA

LOGIN = "login_system.txt"
LOGIN_TEXT = intake_path(LOGIN).read_text(encoding="utf-8")


def test_system_prompt_drops_frontmatter_and_names_the_tool() -> None:
    prompt = load_system_prompt()
    assert not prompt.startswith("---")
    assert "submit_brd" in prompt
    assert "data, not instructions" in prompt


def test_number_lines_prefixes_right_aligned_numbers() -> None:
    assert number_lines("a\nb\n") == "   1| a\n   2| b"


def test_a_correct_draft_is_accepted() -> None:
    assert validate_draft(draft_for(LOGIN), LOGIN_TEXT) == []


def test_lines_outside_the_intake_are_rejected() -> None:
    draft = BrdDraft(requirements=[draft_req("X", ReqCategory.FUNCTIONAL, 99, "anything")])
    assert validate_draft(draft, LOGIN_TEXT) == [
        "requirement 1: lines 99-99 are outside the intake (10 lines)"
    ]


def test_a_quote_not_in_the_cited_lines_is_rejected() -> None:
    errors = validate_draft(bad_draft(), LOGIN_TEXT)
    assert errors == ["requirement 1: evidence_quote is not found in lines 3-3"]


def test_quote_matching_ignores_whitespace_but_not_case() -> None:
    spaced = draft_req("A", ReqCategory.FUNCTIONAL, 4, "must  be able\nto reset it by email")
    assert validate_draft(BrdDraft(requirements=[spaced]), LOGIN_TEXT) == []
    cased = draft_req("A", ReqCategory.FUNCTIONAL, 4, "MUST BE ABLE to reset it by email")
    assert validate_draft(BrdDraft(requirements=[cased]), LOGIN_TEXT) != []


def test_a_quote_may_span_the_cited_range() -> None:
    quote = "Customers who forget the password must be able to reset it by email. The portal"
    spanning = draft_req("A", ReqCategory.FUNCTIONAL, 4, quote, end=5)
    assert validate_draft(BrdDraft(requirements=[spanning]), LOGIN_TEXT) == []


def test_duplicate_titles_are_rejected_after_normalising() -> None:
    first = draft_req("Password  reset", ReqCategory.FUNCTIONAL, 4, "reset it by email")
    second = draft_req("password reset", ReqCategory.FUNCTIONAL, 4, "reset it by email")
    errors = validate_draft(BrdDraft(requirements=[first, second]), LOGIN_TEXT)
    assert errors == ["requirement 2: title duplicates requirement 1"]


def test_an_open_question_outside_the_intake_is_rejected() -> None:
    good = draft_for(LOGIN).requirements
    draft = BrdDraft(
        requirements=good, open_questions=[OpenQuestion(question="?", start_line=50, end_line=51)]
    )
    assert validate_draft(draft, LOGIN_TEXT) == [
        "open question 1: lines 50-51 are outside the intake (10 lines)"
    ]


def test_uncovered_lines_lists_non_blank_lines_nobody_cites() -> None:
    assert uncovered_lines(draft_for(LOGIN), LOGIN_TEXT) == [1, 2, 9, 10]


def test_a_range_that_ends_before_it_starts_is_invalid() -> None:
    with pytest.raises(ValidationError, match="end_line"):
        draft_req("A", ReqCategory.FUNCTIONAL, 5, "x", end=4)
    with pytest.raises(ValidationError, match="end_line"):
        OpenQuestion(question="?", start_line=5, end_line=4)


def test_a_draft_needs_at_least_one_requirement() -> None:
    with pytest.raises(ValidationError):
        BrdDraft(requirements=[])


def test_every_fixture_draft_passes_its_own_gate() -> None:
    for name in ("login_system.txt", "leave_management.txt", "inventory_mixed_ja.txt"):
        text = intake_path(name).read_text(encoding="utf-8")
        assert validate_draft(draft_for(name), text) == [], name


def japanese_draft() -> BrdDraft:
    req = draft_req("サインイン", ReqCategory.FUNCTIONAL, 3, "registered customers can sign in")
    return BrdDraft(
        requirements=[
            req.model_copy(update={"description": "顧客がAPI連携なしでサインインできること。"})
        ],
        open_questions=[OpenQuestion(question="応答時間の基準は？", start_line=8, end_line=8)],
    )


def test_japanese_text_with_ascii_terms_is_accepted_for_ja() -> None:
    assert validate_draft(japanese_draft(), LOGIN_TEXT, JA) == []


def test_english_project_rejects_mostly_japanese_text() -> None:
    errors = validate_draft(japanese_draft(), LOGIN_TEXT, EN)
    assert errors == [
        "requirement 1: description must be written in English but is mostly Japanese",
        "open question 1: text must be written in English but is mostly Japanese",
    ]


def test_english_text_with_a_few_japanese_proper_nouns_is_accepted() -> None:
    req = draft_req("Tokyo office", ReqCategory.FUNCTIONAL, 4, "reset it by email")
    mixed = req.model_copy(
        update={"description": "Staff at the 東京 office must be able to reset it by email."}
    )
    assert validate_draft(BrdDraft(requirements=[mixed]), LOGIN_TEXT, EN) == []


def test_without_a_language_the_gate_skips_the_language_check() -> None:
    assert validate_draft(japanese_draft(), LOGIN_TEXT) == []


def test_first_call_sends_the_numbered_intake_and_the_language_section() -> None:
    llm = FakeLLM([draft_for(LOGIN)])
    write_brd(llm, LOGIN_TEXT, EN, None, [], "DOC-BRD-0001", system_prompt="SYSTEM")
    call = llm.calls[0]
    assert call.tool_name == "submit_brd"
    assert call.system.startswith("SYSTEM")
    assert "English" in call.system
    assert "<intake>\n   1| Subject: Customer portal login" in call.user
    assert "previous_draft" not in call.user


def test_japanese_projects_get_a_japanese_instruction() -> None:
    llm = FakeLLM([draft_for(LOGIN)])
    write_brd(llm, LOGIN_TEXT, JA, None, [], "DOC-BRD-0001", system_prompt="SYSTEM")
    assert "日本語" in llm.calls[0].system


def test_revision_call_includes_the_previous_draft_and_the_reasons() -> None:
    llm = FakeLLM([draft_for(LOGIN)])
    write_brd(llm, LOGIN_TEXT, EN, bad_draft(), ["quote not found"], "DOC-BRD-0001")
    user = llm.calls[0].user
    assert "<previous_draft>\nDOC-BRD-0001#item.1 [functional/in] Invented:" in user
    assert "(L3-L3)" in user
    assert "- quote not found" in user


def test_draft_view_numbers_items_with_category_scope_and_lines() -> None:
    view = brd_draft_view(draft_for(LOGIN), "DOC-BRD-0001").splitlines()
    assert len(view) == 7
    assert view[4].startswith("DOC-BRD-0001#item.5 [business/out] Account administration:")
    assert view[4].endswith("(L7-L7)")


def test_draft_view_shows_the_open_questions_so_the_reviewer_sees_them() -> None:
    view = brd_draft_view(draft_for(LOGIN), "DOC-BRD-0001")
    assert "Open questions the writer raised for the customer (not requirements):" in view
    assert "- L8-L8: What response time counts as fast?" in view
