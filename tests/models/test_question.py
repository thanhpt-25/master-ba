import datetime as dt
from typing import Any

import pytest
from pydantic import ValidationError

from masterba.models import Question
from masterba.models.enums import DocType, QuestionOrigin, QuestionStatus

OPEN: dict[str, Any] = {
    "id": "Q-0001",
    "origin": QuestionOrigin.AGENT,
    "stage": DocType.SRS,
    "run_id": "RUN-0002",
    "refs": ["REQ-0001"],
    "text": "Does the limit count business days?",
    "status": QuestionStatus.OPEN,
    "asked_on": dt.date(2026, 11, 1),
}
ANSWERED: dict[str, Any] = {
    **OPEN,
    "status": QuestionStatus.ANSWERED,
    "answer": "Business days.",
    "answered_by": "alice",
    "answered_on": dt.date(2026, 11, 2),
    "dr_id": "DR-0001",
}


def test_an_open_question_has_no_answer_fields() -> None:
    question = Question.model_validate(OPEN)
    assert (question.answer, question.answered_by, question.dr_id, question.source) == (None,) * 4


def test_an_answered_question_needs_all_four_answer_fields() -> None:
    assert Question.model_validate(ANSWERED).dr_id == "DR-0001"
    for missing in ("answer", "answered_by", "answered_on", "dr_id"):
        data = {k: v for k, v in ANSWERED.items() if k != missing}
        with pytest.raises(ValidationError, match="answered"):
            Question.model_validate(data)


@pytest.mark.parametrize("status", [QuestionStatus.OPEN, QuestionStatus.WITHDRAWN])
def test_answer_fields_are_refused_unless_the_question_is_answered(status: QuestionStatus) -> None:
    with pytest.raises(ValidationError, match="answered"):
        Question.model_validate({**ANSWERED, "status": status})


def test_a_source_is_only_allowed_on_an_answered_question() -> None:
    assert Question.model_validate({**ANSWERED, "source": "Tanaka, meeting"}).source
    with pytest.raises(ValidationError, match="source"):
        Question.model_validate({**OPEN, "source": "Tanaka"})


@pytest.mark.parametrize("bad", ["Q-1", "Q-00001", "q-0001", "DR-0001"])
def test_the_id_pattern(bad: str) -> None:
    with pytest.raises(ValidationError):
        Question.model_validate({**OPEN, "id": bad})


def test_the_text_is_required_and_the_model_is_frozen() -> None:
    with pytest.raises(ValidationError):
        Question.model_validate({**OPEN, "text": ""})
    with pytest.raises(ValidationError):
        Question.model_validate(OPEN).text = "changed"
