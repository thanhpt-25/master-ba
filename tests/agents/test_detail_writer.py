from factories import (
    DESIGN_DOC,
    DETAIL_DOC,
    design_ref,
    detail_item,
    detail_ref,
    login_design_draft,
    login_detail_answered,
    login_detail_draft,
    login_srs_draft,
    login_test_draft,
)
from masterba.agents import (
    DesignAnswer,
    DetailDesignDraft,
    validate_detail_draft,
    write_detail,
)
from masterba.agents.design_writer import active_srs_items
from masterba.agents.detail_writer import active_basic_items, basic_view, detail_view
from masterba.llm import FakeLLM
from masterba.models import BasicDesignContent, BasicDesignItem
from masterba.models.enums import DetailDesignKind, DocLanguage, ItemStatus
from masterba.pipeline import assign_basic_ids, assign_srs_ids
from masterba.team import DesignTestResult

SRS_ITEMS = active_srs_items(assign_srs_ids(login_srs_draft(), project_id="PRJ-001").content)


def _basic_items() -> list[BasicDesignItem]:
    artifacts = assign_basic_ids(
        DesignTestResult(login_design_draft(), login_test_draft()), project_id="PRJ-001"
    )
    content = artifacts.documents[0][1]
    assert isinstance(content, BasicDesignContent)
    return active_basic_items(content)


BASIC_ITEMS = _basic_items()


def test_removed_basic_items_are_not_given_to_the_designer() -> None:
    items = list(BASIC_ITEMS)
    items[0] = items[0].model_copy(update={"status": ItemStatus.REMOVED})
    content = BasicDesignContent(items=items)
    assert [i.item_id for i in active_basic_items(content)] == [design_ref(n) for n in range(2, 6)]


def test_basic_view_lists_refs_kinds_and_descriptions() -> None:
    first = basic_view(BASIC_ITEMS).splitlines()[0]
    assert first.startswith(f"{design_ref(1)} [screen] Login screen: Form with email")


def test_a_detail_design_that_refines_every_basic_item_is_accepted() -> None:
    draft = login_detail_draft()
    assert validate_detail_draft(draft, BASIC_ITEMS, DETAIL_DOC, DocLanguage.EN) == []


def test_refining_an_unknown_basic_item_is_rejected() -> None:
    items = [*login_detail_draft().items, detail_item(DetailDesignKind.MODULE, "X", "x.", 9)]
    errors = validate_detail_draft(DetailDesignDraft(items=items), BASIC_ITEMS, DETAIL_DOC)
    assert errors == [f"item 6: {design_ref(9)} is not an active Basic Design item"]


def test_every_basic_item_must_be_refined() -> None:
    draft = DetailDesignDraft(items=login_detail_draft().items[:3])
    errors = validate_detail_draft(draft, BASIC_ITEMS, DETAIL_DOC)
    assert errors == [
        f"Basic Design items not refined by any detail item: {design_ref(4)}, {design_ref(5)}"
    ]


def test_names_are_unique_within_a_kind_only() -> None:
    items = list(login_detail_draft().items)
    same = detail_item(DetailDesignKind.MODULE, " authmodule ", "again.", 1)
    other = detail_item(DetailDesignKind.API, "AuthModule", "api.", 1)
    errors = validate_detail_draft(DetailDesignDraft(items=[*items, same]), BASIC_ITEMS, DETAIL_DOC)
    assert errors == ["item 6: name duplicates item 1 of the same kind"]
    assert (
        validate_detail_draft(DetailDesignDraft(items=[*items, other]), BASIC_ITEMS, DETAIL_DOC)
        == []
    )


def test_answers_must_point_at_detail_items() -> None:
    draft = login_detail_draft().model_copy(
        update={"answers": [DesignAnswer(ref=detail_ref(9), text="Five.")]}
    )
    assert validate_detail_draft(draft, BASIC_ITEMS, DETAIL_DOC) == [
        f"answer 1: {detail_ref(9)} is not an item of the detail design"
    ]


def test_language_is_checked_for_specs_and_answers() -> None:
    errors = validate_detail_draft(login_detail_answered(), BASIC_ITEMS, DETAIL_DOC, DocLanguage.JA)
    assert any(e.startswith("item 1: spec must be written in Japanese") for e in errors)
    assert any(e.startswith("answer 1: text") for e in errors)


def test_detail_view_numbers_items_and_lists_answers() -> None:
    lines = detail_view(login_detail_answered(), DETAIL_DOC).splitlines()
    assert lines[0].startswith(f"{detail_ref(1)} [module] AuthModule:")
    assert lines[0].endswith(f"(refines {design_ref(1)}, {design_ref(2)})")
    assert lines[-1] == f"- {detail_ref(2)}: Five failed attempts lock the account for 15 minutes."


def test_first_call_sends_only_the_basic_design() -> None:
    llm = FakeLLM([login_detail_draft()])
    write_detail(llm, BASIC_ITEMS, DocLanguage.EN, None, [], DETAIL_DOC, system_prompt="BASE")
    call = llm.calls[0]
    assert call.tool_name == "submit_detail_design"
    assert call.system.startswith("BASE")
    assert "English" in call.system
    assert call.user.startswith(f"<basic_design>\n{design_ref(1)} [screen]")
    assert "previous_design" not in call.user
    assert DESIGN_DOC in call.user


def test_revision_carries_the_previous_design_and_the_questions() -> None:
    llm = FakeLLM([login_detail_answered()])
    feedback = [f"question {detail_ref(2)}: How many failed attempts lock the account?"]
    write_detail(llm, BASIC_ITEMS, DocLanguage.JA, login_detail_draft(), feedback, DETAIL_DOC)
    user = llm.calls[0].user
    assert "<previous_design>" in user
    assert f"- question {detail_ref(2)}:" in user
    assert "also list it in `answers`" in user
    assert "日本語" in llm.calls[0].system
