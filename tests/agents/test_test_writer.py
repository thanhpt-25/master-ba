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
from masterba.agents.test_writer import cases_view, dropped_note, scope_question, tidy_test_draft
from masterba.llm import FakeLLM
from masterba.models.enums import DocLanguage, QuestionOrigin
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
    assert check(draft) == [
        f"exclusion 1: {design_ref(1)} is excluded but also verified by IT case 1; "
        "remove the exclusion, or remove the item from those cases' `verifies`"
    ]


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


def contradicting_draft() -> TestDraft:
    """Design item 1 and SRS item 2 are tested and excluded at once (the live-run failure)."""
    return login_test_draft().model_copy(
        update={
            "exclusions": [
                DraftExclusion(item_ref=design_ref(1), reason="Lockout period not stated."),
                DraftExclusion(item_ref=srs_ref(2), reason="Message text not stated."),
                DraftExclusion(item_ref=design_ref(1), reason="Said twice."),
            ]
        }
    )


def test_tidy_drops_every_exclusion_of_a_tested_item_and_the_gate_then_passes() -> None:
    tidy, dropped = tidy_test_draft(contradicting_draft())
    assert tidy.exclusions == []
    assert tidy.it_cases == login_test_draft().it_cases
    assert [(d.item_ref, d.reason, d.cases) for d in dropped] == [
        (design_ref(1), "Lockout period not stated.", ("IT case 1",)),
        (srs_ref(2), "Message text not stated.", ("ST case 2",)),
    ]
    assert check(tidy) == []
    assert any("also verified by IT case 1" in e for e in check(contradicting_draft()))


def test_tidy_keeps_the_exclusions_of_untested_items_and_returns_a_clean_draft_unchanged() -> None:
    clean = login_test_draft_with_exclusions()
    assert tidy_test_draft(clean) == (clean, [])
    mixed = clean.model_copy(
        update={
            "exclusions": [
                *clean.exclusions,
                DraftExclusion(item_ref=design_ref(2), reason="Partly open."),
            ]
        }
    )
    tidy, dropped = tidy_test_draft(mixed)
    assert tidy.exclusions == clean.exclusions
    assert [d.item_ref for d in dropped] == [design_ref(2)]


def test_a_dropped_exclusion_becomes_a_note_and_a_customer_question() -> None:
    _, [dropped, _] = tidy_test_draft(contradicting_draft())
    assert dropped_note(dropped) == (
        f"exclusion of {design_ref(1)} removed by the gate: it is verified by IT case 1 "
        "(reason given: Lockout period not stated.)"
    )
    english = scope_question(dropped, DocLanguage.EN)
    assert english.refs == [design_ref(1)]
    assert english.origin is QuestionOrigin.AGENT
    assert "Lockout period not stated." in english.text
    japanese = scope_question(dropped, DocLanguage.JA)
    assert japanese.text.startswith(f"{design_ref(1)} はテストケースで検証していますが")
