"""Style findings and the once-only style feedback (spec 19 part 2, section 8)."""

from dataclasses import dataclass

from factories import FUNCTIONAL, doc_id, draft_req, make_test_item
from masterba.agents.requirements_analyst import BrdDraft, OpenQuestion
from masterba.agents.srs_writer import DraftSrsItem, SrsDraft, SrsOpenQuestion
from masterba.models import SrsContent, SrsItem, TestSpecContent
from masterba.models.enums import DocLanguage, DocType, Level, SrsKind
from masterba.quality import StyleFeedback, lint_brd_draft, lint_document, lint_srs_draft
from masterba.quality.lint import lint_expected, lint_statement, lint_text

JA, EN = DocLanguage.JA, DocLanguage.EN
SRS = doc_id(DocType.SRS)


def rules(findings: list) -> list[str]:  # type: ignore[type-arg]
    return [f.rule for f in findings]


def test_vague_japanese_words_are_named() -> None:
    [finding] = lint_text("item 1", "システムは適宜バックアップを取得すること。", JA)
    assert finding.rule == "STY-01"
    assert "「適宜」" in finding.message


def test_vague_english_words_are_whole_words_only() -> None:
    assert rules(lint_text("x", "Reports are shown as needed.", EN)) == ["STY-01"]
    assert lint_text("x", "The appropriateness check is logged.", EN) == []


def test_polite_style_and_long_sentences_are_reported() -> None:
    assert rules(lint_text("x", "申請を承認します。", JA)) == ["STY-06"]
    assert rules(lint_text("x", "あ" * 151 + "。", JA)) == ["STY-03"]
    assert rules(lint_text("x", " ".join(["word"] * 51) + ".", EN)) == ["STY-03"]


def test_requirement_statements_need_an_obligation_ending() -> None:
    assert lint_statement("x", "利用者はログインできること。", JA) == []
    assert lint_statement("x", "承認しなければならない", JA) == []
    assert rules(lint_statement("x", "利用者はログインする。", JA)) == ["STY-02"]
    assert lint_statement("x", "The system shall log sign-ins.", EN) == []
    assert rules(lint_statement("x", "The system logs sign-ins.", EN)) == ["STY-02"]


def test_expected_results_must_be_observable() -> None:
    assert rules(lint_expected("TC", "正常に動作すること。", JA)) == ["STY-04"]
    assert rules(lint_expected("TC", "It works correctly.", EN)) == ["STY-04"]
    assert lint_expected("TC", "「承認しました」と表示されること。", JA) == []


def test_brd_vagueness_covered_by_an_open_question_is_not_reported() -> None:
    vague = draft_req(
        "Speed", FUNCTIONAL, 8, "Please make it fast", description="画面を高速に表示する。"
    )
    asked = BrdDraft(
        requirements=[vague],
        open_questions=[OpenQuestion(question="何秒以内か？", start_line=8, end_line=8)],
    )
    assert "STY-01" not in rules(lint_brd_draft(asked, JA))
    alone = BrdDraft(requirements=[vague])
    assert "STY-01" in rules(lint_brd_draft(alone, JA))


def test_srs_non_functional_needs_a_figure_unless_asked() -> None:
    item = DraftSrsItem(
        kind=SrsKind.NON_FUNCTIONAL,
        statement="システムは常時利用できること。",
        derives_from=["REQ-0001"],
    )
    assert rules(lint_srs_draft(SrsDraft(items=[item]), JA)) == ["STY-05"]
    asked = SrsDraft(
        items=[item], open_questions=[SrsOpenQuestion(question="稼働率は？", req_ids=["REQ-0001"])]
    )
    assert lint_srs_draft(asked, JA) == []


def test_lint_document_covers_srs_and_tests() -> None:
    srs = SrsContent(
        items=[
            SrsItem(
                item_id=f"{SRS}#item.1",
                requirement_id="REQ-0001",
                kind=SrsKind.NON_FUNCTIONAL,
                statement="応答は速やかであること。",
            )
        ]
    )
    assert sorted(rules(lint_document(srs, JA))) == ["STY-01", "STY-05"]
    case = make_test_item(doc_id(DocType.TEST_IT), 1, "TC-IT-0001", Level.IT).model_copy(
        update={"expected": "It works correctly."}
    )
    assert rules(lint_document(TestSpecContent(items=[case]), EN)) == ["STY-04"]


@dataclass
class Rounds:
    rounds: int
    max_rounds: int = 3


def test_style_feedback_is_given_once_and_only_with_two_rounds_left() -> None:
    findings = lint_text("item 1", "適宜対応する。", JA)
    style = StyleFeedback()
    assert style.feedback(Rounds(2), findings) == []  # one round left: never
    assert style.feedback(Rounds(1), findings) == [f"style STY-01 item 1: {findings[0].message}"]
    assert style.feedback(Rounds(1), findings) == []  # already used
    assert StyleFeedback().feedback(Rounds(1), []) == []


def test_style_feedback_is_capped() -> None:
    findings = lint_text("x", "適宜対応する。", JA) * 15
    lines = StyleFeedback().feedback(Rounds(1, 5), findings)
    assert len(lines) == 13
    assert lines[-1] == "style: 3 more findings of the same kinds"
