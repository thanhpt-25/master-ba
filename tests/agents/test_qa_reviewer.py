import inspect

import pytest
from pydantic import ValidationError

from masterba.agents import (
    Check,
    Checklist,
    QaIssue,
    QaOutputInvalidError,
    QaReport,
    QaReview,
    load_checklist,
    qa_reviewer,
    review,
)
from masterba.agents.qa_reviewer import (
    CHECKLIST_DIR,
    cap_severity,
    checklist_path,
    system_prompt_for,
    validate_report,
)
from masterba.llm import FakeLLM, LLMOutputError
from masterba.models.enums import DocLanguage, DocType

BRD = load_checklist(checklist_path(DocType.BRD))
SRS = load_checklist(checklist_path(DocType.SRS))
DOC = "DOC-SRS-0001"
REF = f"{DOC}#item.2"


def issue(
    checklist_id: str = "SRS-01", severity: str = "blocking", ref: str | None = REF
) -> QaIssue:
    return QaIssue.model_validate(
        {"checklist_id": checklist_id, "severity": severity, "ref": ref, "message": "Problem."}
    )


def run_review(llm: FakeLLM, checklist: Checklist = SRS, items: int = 3) -> QaReview:
    return review(
        llm,
        checklist=checklist,
        item_counts={DOC: items},
        upstream="UPSTREAM TEXT",
        draft_view="DRAFT TEXT",
        language=DocLanguage.EN,
        system_prompt="BASE",
    )


@pytest.mark.parametrize("stage", [DocType.BRD, DocType.SRS])
def test_shipped_checklists_load_with_unique_ids(stage: DocType) -> None:
    checklist = load_checklist(checklist_path(stage))
    assert checklist.stage == stage.value
    assert len(checklist.checks) >= 6
    assert checklist_path(stage).parent == CHECKLIST_DIR


def test_a_checklist_with_duplicate_ids_is_invalid() -> None:
    check = Check(id="X-1", severity="blocking", text="t")
    with pytest.raises(ValidationError, match="unique"):
        Checklist(stage="X", checks=[check, check])


def test_the_prompt_lists_the_checklist_and_the_language() -> None:
    prompt = system_prompt_for(SRS, DocLanguage.JA, base="BASE")
    assert prompt.startswith("BASE")
    assert "SRS-01 (blocking)" in prompt
    assert "SRS-07 (advisory)" in prompt
    assert "Japanese" in prompt


def test_the_same_reviewer_serves_both_stages_with_only_the_checklist_changing() -> None:
    brd_prompt = system_prompt_for(BRD, DocLanguage.EN, base="BASE")
    srs_prompt = system_prompt_for(SRS, DocLanguage.EN, base="BASE")
    assert "BRD-01" in brd_prompt
    assert "SRS-01" not in brd_prompt
    assert "SRS-01" in srs_prompt
    assert "BRD-01" not in srs_prompt
    source = inspect.getsource(qa_reviewer)
    assert "DocType.BRD" not in source
    assert "DocType.SRS" not in source


def test_a_clean_review_passes_and_sends_upstream_and_draft() -> None:
    llm = FakeLLM([QaReport()])
    outcome = run_review(llm)
    assert outcome.report.passed
    assert outcome.attempts == 1
    call = llm.calls[0]
    assert call.tool_name == "submit_qa_report"
    assert "<upstream>\nUPSTREAM TEXT\n</upstream>" in call.user
    assert "<draft>\nDRAFT TEXT\n</draft>" in call.user


def test_a_blocking_issue_makes_the_report_fail_and_an_advisory_one_does_not() -> None:
    assert not QaReport(issues=[issue()]).passed
    assert QaReport(issues=[issue("SRS-07", "advisory")]).passed


def test_unknown_checklist_id_or_foreign_ref_is_reported() -> None:
    report = QaReport(
        issues=[issue("SRS-99"), issue(ref="DOC-BRD-0001#item.1"), issue(ref=f"{DOC}#item.9")]
    )
    errors = validate_report(report, SRS, {DOC: 3})
    assert errors == [
        "issue 1: unknown checklist_id 'SRS-99'",
        "issue 2: ref DOC-BRD-0001#item.1 is not an item of the draft",
        f"issue 3: ref {DOC}#item.9 is not an item of the draft",
    ]
    assert validate_report(QaReport(issues=[issue(ref=None)]), SRS, {DOC: 3}) == []


def test_an_unusable_report_is_retried_once_and_the_errors_are_sent_back() -> None:
    llm = FakeLLM([QaReport(issues=[issue("SRS-99")]), QaReport(issues=[issue()])])
    outcome = run_review(llm)
    assert outcome.attempts == 2
    assert (outcome.input_tokens, outcome.output_tokens) == (200, 100)
    assert "previous report was unusable" in llm.calls[1].user
    assert "unknown checklist_id 'SRS-99'" in llm.calls[1].user
    assert "unusable" not in llm.calls[0].user


def test_a_model_output_error_counts_as_an_unusable_report() -> None:
    llm = FakeLLM([LLMOutputError("no tool call"), QaReport()])
    assert run_review(llm).attempts == 2


def test_two_unusable_reports_raise_with_the_tokens_spent() -> None:
    llm = FakeLLM([QaReport(issues=[issue("SRS-99")]), QaReport(issues=[issue("SRS-98")])])
    with pytest.raises(QaOutputInvalidError, match="SRS-98") as caught:
        run_review(llm)
    assert (caught.value.input_tokens, caught.value.output_tokens) == (200, 100)
    assert len(llm.calls) == 2


def test_the_model_cannot_raise_a_severity_above_the_checklist() -> None:
    report = QaReport(issues=[issue("SRS-07", "blocking"), issue("SRS-01", "advisory")])
    capped = cap_severity(report, SRS)
    assert [i.severity for i in capped.issues] == ["advisory", "advisory"]
    assert capped.passed


def test_review_applies_the_severity_cap() -> None:
    outcome = run_review(FakeLLM([QaReport(issues=[issue("SRS-07", "blocking")])]))
    assert outcome.report.passed


def test_one_review_validates_refs_of_several_documents() -> None:
    counts = {"DOC-TEST_IT-0001": 2, "DOC-TEST_ST-0001": 1}
    report = QaReport(
        issues=[
            issue("SRS-01", ref="DOC-TEST_IT-0001#item.2"),
            issue("SRS-01", ref="DOC-TEST_ST-0001#item.1"),
            issue("SRS-01", ref="DOC-TEST_ST-0001#item.2"),
            issue("SRS-01", ref="DOC-OTHER-0001#item.1".replace("OTHER", "BRD")),
        ]
    )
    assert validate_report(report, SRS, counts) == [
        "issue 3: ref DOC-TEST_ST-0001#item.2 is not an item of the draft",
        "issue 4: ref DOC-BRD-0001#item.1 is not an item of the draft",
    ]


def test_checklists_can_be_found_by_stem_and_the_stage_ones_exist() -> None:
    assert checklist_path("tests").name == "tests.toml"
    assert checklist_path(DocType.BASIC_DESIGN).name == "basic_design.toml"
    assert load_checklist(checklist_path("tests")).stage == "TESTS"
    assert load_checklist(checklist_path(DocType.BASIC_DESIGN)).stage == "BASIC_DESIGN"
