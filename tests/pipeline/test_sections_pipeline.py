"""Sections and style feedback through the BRD and SRS stages (spec 19 part 2)."""

from pathlib import Path

from openpyxl import load_workbook

from factories import draft_for, intake_path, login_srs_draft, qa_pass
from masterba.agents.sections import DraftSection
from masterba.llm import FakeLLM
from masterba.models import BrdContent, SrsContent
from masterba.models.enums import SectionKey, TeamRunStatus
from masterba.pipeline import BRD_DOC_ID, run_brd, run_srs
from masterba.pipeline.srs import SRS_DOC_ID
from masterba.trace_store import ProjectStore, get_document

TEMPLATES = Path(__file__).parents[2] / "templates"
LOGIN = "login_system.txt"
BACKGROUND = DraftSection(
    key=SectionKey.BACKGROUND,
    body="Registered customers need a portal to sign in and see their orders.",
    sources=["L3", "L6"],
)
CONSTRAINTS = DraftSection(
    key=SectionKey.CONSTRAINTS,
    body="Customer accounts stay in the existing admin tool.",
    sources=["L7"],
)


def brd_with_sections() -> FakeLLM:
    draft = draft_for(LOGIN).model_copy(update={"sections": [CONSTRAINTS, BACKGROUND]})
    return FakeLLM([draft, qa_pass()])


def test_brd_sections_are_stored_with_intake_citations_and_rendered(store: ProjectStore) -> None:
    result = run_brd(store, TEMPLATES, brd_with_sections(), intake_path(LOGIN))
    assert result.status is TeamRunStatus.DONE
    _, content = get_document(store, BRD_DOC_ID)
    assert isinstance(content, BrdContent)
    assert [(s.key, s.sources) for s in content.sections] == [
        (SectionKey.BACKGROUND, [f"intake/{LOGIN}#L3-L3", f"intake/{LOGIN}#L6-L6"]),
        (SectionKey.CONSTRAINTS, [f"intake/{LOGIN}#L7-L7"]),
    ]
    assert result.xlsx_path is not None
    wb = load_workbook(result.xlsx_path)
    assert wb["背景・目的"]["A8"].value == BACKGROUND.body
    assert wb["背景・目的"]["A11"].value == f"intake/{LOGIN}#L3-L3\nintake/{LOGIN}#L6-L6"
    assert wb["前提条件・制約事項"]["A8"].value == CONSTRAINTS.body


def test_a_missing_section_says_the_input_does_not_state_it(store: ProjectStore) -> None:
    result = run_brd(store, TEMPLATES, FakeLLM([draft_for(LOGIN), qa_pass()]), intake_path(LOGIN))
    assert result.xlsx_path is not None
    sheet = load_workbook(result.xlsx_path)["背景・目的"]
    assert sheet["A8"].value == "（入力資料に記載がないため、本版では記載していません。）"
    assert sheet["A11"].value is None


def test_a_section_citing_lines_outside_the_intake_goes_back_to_the_writer(
    store: ProjectStore,
) -> None:
    bad = BACKGROUND.model_copy(update={"sources": ["L99"]})
    first = draft_for(LOGIN).model_copy(update={"sections": [bad]})
    llm = FakeLLM([first, draft_for(LOGIN), qa_pass()])
    result = run_brd(store, TEMPLATES, llm, intake_path(LOGIN))
    assert result.status is TeamRunStatus.DONE
    assert "section background: source L99 is outside the intake" in llm.calls[1].user


def test_style_findings_go_back_to_the_writer_once(store: ProjectStore) -> None:
    vague = draft_for(LOGIN)
    first_item = vague.requirements[1].model_copy(
        update={"description": "Customers can reset the password by email as needed."}
    )
    styled = vague.model_copy(
        update={"requirements": [vague.requirements[0], first_item, *vague.requirements[2:]]}
    )
    # The same wording comes back: the second time it is not sent again, QA decides.
    llm = FakeLLM([styled, styled, qa_pass()])
    result = run_brd(store, TEMPLATES, llm, intake_path(LOGIN))
    assert result.status is TeamRunStatus.DONE
    assert "style STY-01 requirement 2: vague wording" in llm.calls[1].user
    assert len(llm.calls) == 3


def test_srs_sections_may_cite_brd_sections(store: ProjectStore) -> None:
    run_brd(store, TEMPLATES, brd_with_sections(), intake_path(LOGIN))
    section = DraftSection(
        key=SectionKey.BACKGROUND,
        body="The system lets registered customers sign in and see their orders.",
        sources=[f"{BRD_DOC_ID}#background", "REQ-0001"],
    )
    llm = FakeLLM([login_srs_draft().model_copy(update={"sections": [section]}), qa_pass()])
    result = run_srs(store, TEMPLATES, llm)
    assert result.status is TeamRunStatus.DONE
    assert f"{BRD_DOC_ID}#background 背景・目的: Registered customers" in llm.calls[0].user
    _, content = get_document(store, SRS_DOC_ID)
    assert isinstance(content, SrsContent)
    assert content.sections[0].sources == [f"{BRD_DOC_ID}#background", "REQ-0001"]
