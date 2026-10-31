import pytest
from pydantic import ValidationError

from factories import (
    DESIGN_DOC,
    design_ref,
    login_design_draft,
    login_srs_draft,
    login_test_draft,
    login_test_draft_with_exclusions,
    login_test_draft_with_question,
    srs_ref,
    tcase,
)
from masterba.agents import (
    DesignQuestion,
    DraftExclusion,
    DraftTestCase,
    TestDraft,
    validate_test_draft,
    write_tests,
)
from masterba.agents.design_writer import active_srs_items
from masterba.agents.test_writer import cases_view
from masterba.llm import FakeLLM
from masterba.models.enums import DocLanguage
from masterba.pipeline import assign_srs_ids

IT_DOC = "DOC-TEST_IT-0001"
ST_DOC = "DOC-TEST_ST-0001"
DESIGN = login_design_draft()
SRS_ITEMS = active_srs_items(assign_srs_ids(login_srs_draft(), project_id="PRJ-001").content)


def check(draft: TestDraft, language: DocLanguage | None = DocLanguage.EN) -> list[str]:
    return validate_test_draft(draft, DESIGN, SRS_ITEMS, DESIGN_DOC, language)


def test_complete_tests_are_accepted() -> None:
    assert check(login_test_draft()) == []


def test_exclusions_can_stand_in_for_cases() -> None:
    assert check(login_test_draft_with_exclusions()) == []


def test_questions_do_not_fail_the_gate() -> None:
    assert check(login_test_draft_with_question()) == []


def test_it_cases_must_cite_design_items_and_st_cases_active_srs_items() -> None:
    draft = login_test_draft().model_copy(
        update={
            "it_cases": [*login_test_draft().it_cases, tcase(srs_ref(1))],
            "st_cases": [*login_test_draft().st_cases, tcase(design_ref(1))],
        }
    )
    assert check(draft) == [
        f"IT case 6: {srs_ref(1)} is not a design item",
        f"ST case 5: {design_ref(1)} is not an active SRS item",
    ]


def test_every_design_item_and_srs_item_needs_a_case_or_an_exclusion() -> None:
    draft = TestDraft(it_cases=[tcase(design_ref(1))], st_cases=[tcase(srs_ref(1))])
    errors = check(draft)
    assert errors[0].startswith("design items with no IT case and no exclusion: ")
    assert design_ref(5) in errors[0]
    assert errors[1].startswith("SRS items with no ST case and no exclusion: ")
    assert srs_ref(4) in errors[1]


def test_an_item_cannot_be_both_tested_and_excluded() -> None:
    draft = login_test_draft().model_copy(
        update={"exclusions": [DraftExclusion(item_ref=design_ref(1), reason="Skip it.")]}
    )
    assert check(draft) == [f"exclusion 1: {design_ref(1)} is also tested"]


def test_an_exclusion_must_name_a_known_item() -> None:
    draft = login_test_draft().model_copy(
        update={"exclusions": [DraftExclusion(item_ref=design_ref(9), reason="No such item.")]}
    )
    assert check(draft) == [f"exclusion 1: {design_ref(9)} is not a design or SRS item"]


def test_a_question_must_name_a_design_item() -> None:
    draft = login_test_draft().model_copy(
        update={"questions": [DesignQuestion(ref=design_ref(9), question="Which?")]}
    )
    assert check(draft) == [f"question 1: {design_ref(9)} is not a design item"]


def test_blank_steps_and_empty_expectations_are_rejected_by_the_model() -> None:
    base = {"precondition": "", "input": "", "verifies": [design_ref(1)]}
    with pytest.raises(ValidationError, match="blank"):
        DraftTestCase.model_validate({**base, "steps": ["Open", "  "], "expected": "ok"})
    with pytest.raises(ValidationError):
        DraftTestCase.model_validate({**base, "steps": [], "expected": "ok"})
    with pytest.raises(ValidationError):
        DraftTestCase.model_validate({**base, "steps": ["Open"], "expected": ""})


def test_language_is_checked_for_case_text_and_reasons() -> None:
    errors = check(login_test_draft_with_exclusions(), DocLanguage.JA)
    assert any(e.startswith("IT case 1: text must be written in Japanese") for e in errors)
    assert any(e.startswith("exclusion 1: reason must be written in Japanese") for e in errors)


def test_cases_view_numbers_cases_per_document_and_lists_exclusions_and_questions() -> None:
    draft = login_test_draft_with_exclusions().model_copy(
        update={"questions": login_test_draft_with_question().questions}
    )
    lines = cases_view(draft, IT_DOC, ST_DOC).splitlines()
    assert lines[0].startswith(f"{IT_DOC}#item.1 [IT] verifies {design_ref(1)} | precondition:")
    assert "steps: 1. Open the page 2. Submit the form" in lines[0]
    assert any(line.startswith(f"{ST_DOC}#item.1 [ST] verifies {srs_ref(1)}") for line in lines)
    assert "Items left without a test case:" in lines
    assert f"- {srs_ref(3)}: Cannot be shown in a test period." in lines
    assert lines[-2] == "Questions the tester asked the designer:"
    assert lines[-1].startswith(f"- {design_ref(2)}: What are the minimum")


def test_first_call_sends_the_srs_and_the_design() -> None:
    llm = FakeLLM([login_test_draft()])
    write_tests(
        llm, DESIGN, SRS_ITEMS, DocLanguage.EN, None, [], DESIGN_DOC, IT_DOC, ST_DOC,
        system_prompt="BASE",
    )  # fmt: skip
    call = llm.calls[0]
    assert call.tool_name == "submit_tests"
    assert call.system.startswith("BASE")
    assert f"<srs>\n{srs_ref(1)} [functional]" in call.user
    assert f"<design>\n{design_ref(1)} [screen] Login screen" in call.user
    assert "previous_tests" not in call.user


def test_revision_includes_previous_tests_and_feedback() -> None:
    llm = FakeLLM([login_test_draft()])
    write_tests(
        llm, DESIGN, SRS_ITEMS, DocLanguage.JA, login_test_draft_with_question(),
        ["the design was revised; re-check every case against it"], DESIGN_DOC, IT_DOC, ST_DOC,
    )  # fmt: skip
    user = llm.calls[0].user
    assert "<previous_tests>" in user
    assert "- the design was revised; re-check every case against it" in user
    assert "Questions the tester asked the designer:" in user
    assert "日本語" in llm.calls[0].system
