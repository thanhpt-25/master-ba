from factories import (
    DESIGN_DOC,
    design_item,
    design_ref,
    login_design_answered,
    login_design_draft,
    login_srs_draft,
    srs_ref,
)
from masterba.agents import (
    BasicDesignDraft,
    DesignAnswer,
    validate_design_draft,
    write_design,
)
from masterba.agents.design_writer import active_srs_items, design_view, srs_view
from masterba.llm import FakeLLM
from masterba.models import SrsContent
from masterba.models.enums import BasicDesignKind, DocLanguage, ItemStatus
from masterba.pipeline import assign_srs_ids

SRS_ITEMS = active_srs_items(assign_srs_ids(login_srs_draft(), project_id="PRJ-001").content)


def test_removed_srs_items_are_not_given_to_the_designer() -> None:
    items = list(SRS_ITEMS)
    items[1] = items[1].model_copy(update={"status": ItemStatus.REMOVED})
    assert [i.item_id for i in active_srs_items(SrsContent(items=items))] == [
        srs_ref(1),
        srs_ref(3),
        srs_ref(4),
    ]


def test_srs_view_shows_refs_kinds_and_hints() -> None:
    lines = srs_view(SRS_ITEMS).splitlines()
    assert lines[0].startswith(f"{srs_ref(1)} [functional] The system shall let a registered")
    assert "| acceptance: Sign in with valid credentials" in lines[0]
    assert "acceptance" not in lines[2]


def test_a_design_that_realises_every_srs_item_is_accepted() -> None:
    assert validate_design_draft(login_design_draft(), SRS_ITEMS, DESIGN_DOC, DocLanguage.EN) == []


def test_realising_an_unknown_srs_item_is_rejected() -> None:
    items = [*login_design_draft().items, design_item(BasicDesignKind.SCREEN, "Extra", "x.", 9)]
    errors = validate_design_draft(BasicDesignDraft(items=items), SRS_ITEMS, DESIGN_DOC)
    assert errors == [f"item 6: {srs_ref(9)} is not an active SRS item"]


def test_every_srs_item_must_be_realised() -> None:
    draft = BasicDesignDraft(items=login_design_draft().items[:3])
    errors = validate_design_draft(draft, SRS_ITEMS, DESIGN_DOC)
    assert errors == [f"SRS items not realised by any design item: {srs_ref(3)}, {srs_ref(4)}"]


def test_names_must_be_unique_within_a_kind_but_not_across_kinds() -> None:
    items = list(login_design_draft().items)
    same_kind = design_item(BasicDesignKind.FUNCTION, " authentication ", "again.", 1)
    other_kind = design_item(BasicDesignKind.SCREEN, "Authentication", "screen.", 1)
    errors = validate_design_draft(
        BasicDesignDraft(items=[*items, same_kind]), SRS_ITEMS, DESIGN_DOC
    )
    assert errors == ["item 6: name duplicates item 2 of the same kind"]
    assert (
        validate_design_draft(BasicDesignDraft(items=[*items, other_kind]), SRS_ITEMS, DESIGN_DOC)
        == []
    )


def test_answers_must_point_at_design_items() -> None:
    draft = login_design_draft().model_copy(
        update={"answers": [DesignAnswer(ref=design_ref(9), text="Eight characters.")]}
    )
    assert validate_design_draft(draft, SRS_ITEMS, DESIGN_DOC) == [
        f"answer 1: {design_ref(9)} is not an item of the design"
    ]


def test_language_is_checked_loosely_for_descriptions_and_answers() -> None:
    ja = validate_design_draft(login_design_answered(), SRS_ITEMS, DESIGN_DOC, DocLanguage.JA)
    assert len(ja) == 6
    assert "description must be written in Japanese" in ja[0]
    assert any(e.startswith("answer 1:") for e in ja)


def test_design_view_numbers_items_and_lists_the_answers() -> None:
    lines = design_view(login_design_answered(), DESIGN_DOC).splitlines()
    assert lines[0].startswith(f"{design_ref(1)} [screen] Login screen:")
    assert lines[0].endswith(f"(realizes {srs_ref(1)})")
    assert lines[-2] == "Answers the designer gave to the tester:"
    assert lines[-1] == f"- {design_ref(2)}: Passwords are 8 to 64 characters long."


def test_first_call_sends_only_the_srs() -> None:
    llm = FakeLLM([login_design_draft()])
    write_design(llm, SRS_ITEMS, DocLanguage.EN, None, [], DESIGN_DOC, system_prompt="BASE")
    call = llm.calls[0]
    assert call.tool_name == "submit_basic_design"
    assert call.system.startswith("BASE")
    assert "English" in call.system
    assert call.user.startswith(f"<srs>\n{srs_ref(1)} [functional]")
    assert "previous_design" not in call.user


def test_revision_includes_the_previous_design_and_the_questions() -> None:
    llm = FakeLLM([login_design_answered()])
    feedback = [f"question {design_ref(2)}: What are the password limits?"]
    write_design(llm, SRS_ITEMS, DocLanguage.JA, login_design_draft(), feedback, DESIGN_DOC)
    user = llm.calls[0].user
    assert "<previous_design>" in user
    assert f"- question {design_ref(2)}: What are the password limits?" in user
    assert "also list it in `answers`" in user
    assert "日本語" in llm.calls[0].system
