from factories import (
    DETAIL_DOC,
    detail_ref,
    login_detail_draft,
    login_unit_draft,
    login_unit_draft_with_exclusion,
    login_unit_draft_with_question,
    tcase,
)
from masterba.agents import (
    DesignQuestion,
    DraftExclusion,
    UnitTestDraft,
    validate_unit_test_draft,
    write_unit_tests,
)
from masterba.agents.unit_test_writer import unit_cases_view
from masterba.llm import FakeLLM
from masterba.models.enums import DocLanguage

UT_DOC = "DOC-TEST_UT-0001"
DETAIL = login_detail_draft()


def check(draft: UnitTestDraft, language: DocLanguage | None = DocLanguage.EN) -> list[str]:
    return validate_unit_test_draft(draft, DETAIL, DETAIL_DOC, language)


def test_complete_unit_tests_are_accepted() -> None:
    assert check(login_unit_draft()) == []


def test_an_exclusion_can_stand_in_for_a_case() -> None:
    assert check(login_unit_draft_with_exclusion()) == []


def test_questions_do_not_fail_the_gate() -> None:
    assert check(login_unit_draft_with_question()) == []


def test_cases_must_cite_detail_items_of_the_draft() -> None:
    draft = login_unit_draft().model_copy(
        update={"ut_cases": [*login_unit_draft().ut_cases, tcase(detail_ref(9))]}
    )
    assert check(draft) == [f"UT case 6: {detail_ref(9)} is not a detail design item"]


def test_every_detail_item_needs_a_case_or_an_exclusion() -> None:
    draft = UnitTestDraft(ut_cases=[tcase(detail_ref(1))])
    errors = check(draft)
    assert len(errors) == 1
    assert errors[0].startswith("detail items with no UT case and no exclusion: ")
    assert detail_ref(5) in errors[0]


def test_an_item_cannot_be_both_tested_and_excluded() -> None:
    draft = login_unit_draft().model_copy(
        update={"exclusions": [DraftExclusion(item_ref=detail_ref(1), reason="Skip.")]}
    )
    assert check(draft) == [f"exclusion 1: {detail_ref(1)} is also tested"]


def test_exclusions_and_questions_must_name_detail_items() -> None:
    draft = login_unit_draft().model_copy(
        update={
            "exclusions": [DraftExclusion(item_ref=detail_ref(9), reason="No such item.")],
            "questions": [DesignQuestion(ref=detail_ref(8), question="Which?")],
        }
    )
    assert check(draft) == [
        f"exclusion 1: {detail_ref(9)} is not a detail design item",
        f"question 1: {detail_ref(8)} is not a detail design item",
    ]


def test_language_is_checked_for_case_text_and_reasons() -> None:
    errors = check(login_unit_draft_with_exclusion(), DocLanguage.JA)
    assert any(e.startswith("UT case 1: text must be written in Japanese") for e in errors)
    assert any(e.startswith("exclusion 1: reason must be written in Japanese") for e in errors)


def test_unit_cases_view_numbers_cases_and_lists_exclusions_and_questions() -> None:
    draft = login_unit_draft_with_exclusion().model_copy(
        update={"questions": login_unit_draft_with_question().questions}
    )
    lines = unit_cases_view(draft, UT_DOC).splitlines()
    assert lines[0].startswith(f"{UT_DOC}#item.1 [UT] verifies {detail_ref(1)} | precondition:")
    assert "steps: 1. Open the page 2. Submit the form" in lines[0]
    assert "Items left without a test case:" in lines
    assert f"- {detail_ref(4)}: A policy, not executable code." in lines
    assert lines[-2] == "Questions the tester asked the designer:"
    assert lines[-1].startswith(f"- {detail_ref(2)}: How many failed attempts")


def test_first_call_sends_the_detail_design() -> None:
    llm = FakeLLM([login_unit_draft()])
    write_unit_tests(
        llm, DETAIL, [], DocLanguage.EN, None, [], DETAIL_DOC, UT_DOC, system_prompt="BASE"
    )
    call = llm.calls[0]
    assert call.tool_name == "submit_unit_tests"
    assert call.system.startswith("BASE")
    assert f"<detail_design>\n{detail_ref(1)} [module] AuthModule" in call.user
    assert "previous_tests" not in call.user


def test_revision_includes_previous_tests_and_feedback() -> None:
    llm = FakeLLM([login_unit_draft()])
    write_unit_tests(
        llm, DETAIL, [], DocLanguage.JA, login_unit_draft_with_question(),
        ["the design was revised; re-check every case against it"], DETAIL_DOC, UT_DOC,
    )  # fmt: skip
    user = llm.calls[0].user
    assert "<previous_tests>" in user
    assert "- the design was revised; re-check every case against it" in user
    assert "日本語" in llm.calls[0].system
