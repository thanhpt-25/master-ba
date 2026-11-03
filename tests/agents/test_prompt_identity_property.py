# Feature: local-rag, Property 20: Empty knowledge base leaves prompts unchanged
from collections.abc import Callable

from hypothesis import given
from hypothesis import strategies as st

import prompt_oracle as oracle
from factories import (
    draft_for,
    login_design_draft,
    login_detail_draft,
    login_srs_draft,
    login_test_draft,
    login_unit_draft,
    make_basic_item,
    make_brd,
    make_brd_item,
    make_requirement,
    qa_pass,
)
from masterba.agents import (
    brd_draft_view,
    brd_requirements,
    load_checklist,
    number_lines,
    review,
    write_brd,
    write_design,
    write_detail,
    write_srs,
    write_tests,
    write_unit_tests,
)
from masterba.agents.design_writer import active_srs_items, design_view, srs_view
from masterba.agents.detail_writer import basic_view, detail_view
from masterba.agents.qa_reviewer import checklist_path, system_prompt_for
from masterba.agents.srs_writer import brd_view, draft_view
from masterba.agents.test_writer import cases_view
from masterba.agents.unit_test_writer import unit_cases_view
from masterba.llm import FakeLLM
from masterba.models.enums import DocLanguage
from masterba.pipeline import assign_srs_ids

_text = st.text(st.characters(blacklist_categories=["Cs"]), max_size=60)
_feedback = st.lists(_text, max_size=3)
SRS_ITEMS = active_srs_items(assign_srs_ids(login_srs_draft(), project_id="PRJ-001").content)
BASIC = [make_basic_item("DOC-BASIC_DESIGN-0001", i) for i in (1, 2)]
BRD = brd_requirements(make_brd(make_brd_item("DOC-BRD-0001", 1)), [make_requirement(1)])


@given(_text.filter(str.strip), _feedback, st.booleans())
def test_writer_prompts_unchanged(intake: str, feedback: list[str], revise: bool) -> None:
    lang = DocLanguage.EN
    cases = [
        (
            lambda llm: write_brd(
                llm,
                intake,
                lang,
                draft_for("login_system.txt") if revise else None,
                feedback,
                "DOC-BRD-0001",
                references="",
            ),
            oracle.brd_user(
                number_lines(intake),
                brd_draft_view(draft_for("login_system.txt"), "DOC-BRD-0001") if revise else None,
                feedback,
            ),
            draft_for("login_system.txt"),
        ),
        (
            lambda llm: write_srs(
                llm,
                BRD,
                lang,
                login_srs_draft() if revise else None,
                feedback,
                "DOC-SRS-0001",
                references="",
            ),
            oracle.srs_user(
                brd_view(BRD),
                draft_view(login_srs_draft(), "DOC-SRS-0001") if revise else None,
                feedback,
            ),
            login_srs_draft(),
        ),
        (
            lambda llm: write_design(
                llm,
                SRS_ITEMS,
                lang,
                login_design_draft() if revise else None,
                feedback,
                "DOC-BASIC_DESIGN-0001",
                references="",
            ),
            oracle.design_user(
                srs_view(SRS_ITEMS),
                design_view(login_design_draft(), "DOC-BASIC_DESIGN-0001") if revise else None,
                feedback,
            ),
            login_design_draft(),
        ),
        (
            lambda llm: write_tests(
                llm,
                login_design_draft(),
                SRS_ITEMS,
                lang,
                login_test_draft() if revise else None,
                feedback,
                "DOC-BASIC_DESIGN-0001",
                "DOC-TEST_IT-0001",
                "DOC-TEST_ST-0001",
                references="",
            ),
            oracle.tests_user(
                srs_view(SRS_ITEMS),
                design_view(login_design_draft(), "DOC-BASIC_DESIGN-0001"),
                cases_view(login_test_draft(), "DOC-TEST_IT-0001", "DOC-TEST_ST-0001")
                if revise
                else None,
                feedback,
            ),
            login_test_draft(),
        ),
        (
            lambda llm: write_detail(
                llm,
                BASIC,
                lang,
                login_detail_draft() if revise else None,
                feedback,
                "DOC-DETAIL_DESIGN-0001",
                references="",
            ),
            oracle.detail_user(
                basic_view(BASIC),
                detail_view(login_detail_draft(), "DOC-DETAIL_DESIGN-0001") if revise else None,
                feedback,
            ),
            login_detail_draft(),
        ),
        (
            lambda llm: write_unit_tests(
                llm,
                login_detail_draft(),
                BASIC,
                lang,
                login_unit_draft() if revise else None,
                feedback,
                "DOC-DETAIL_DESIGN-0001",
                "DOC-TEST_UT-0001",
                references="",
            ),
            oracle.unit_tests_user(
                basic_view(BASIC),
                detail_view(login_detail_draft(), "DOC-DETAIL_DESIGN-0001"),
                unit_cases_view(login_unit_draft(), "DOC-TEST_UT-0001") if revise else None,
                feedback,
            ),
            login_unit_draft(),
        ),
    ]
    for call, expected, response in cases:
        llm = FakeLLM([response])
        writer: Callable[[FakeLLM], object] = call
        writer(llm)
        assert llm.calls[0].user == expected


@given(
    _text,
    _text,
    st.sampled_from(["brd", "srs", "basic_design", "detail_design", "tests", "unit_tests"]),
)
def test_qa_prompts_unchanged(upstream: str, draft: str, name: str) -> None:
    checklist = load_checklist(checklist_path(name))
    llm = FakeLLM([qa_pass()])
    review(
        llm,
        checklist=checklist,
        item_counts={},
        upstream=upstream,
        draft_view=draft,
        language=DocLanguage.EN,
        references="",
    )
    assert llm.calls[0].user == oracle.qa_user(upstream, draft)
    plain = [(c.id, c.severity, c.text) for c in checklist.checks if not c.requires_reference]
    base = system_prompt_for(checklist, DocLanguage.EN).split("\n\n## Checklist")[0]
    language = llm.calls[0].system.rsplit("## Output language\n\n", 1)[1]
    assert llm.calls[0].system == oracle.qa_system(base, checklist.stage, plain, language)
    assert not any(c.id.endswith("-KB") for c in checklist.checks if c.id in llm.calls[0].system)
