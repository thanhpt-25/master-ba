"""Answering a question: the answer becomes an approved clarification Decision Record."""

import datetime as dt
import re
import unicodedata

from masterba.change.lifecycle import LifecycleError, approve_dr, new_dr
from masterba.models import Question
from masterba.models.enums import DrStatus, DrTrigger, QuestionStatus
from masterba.questions.ledger import Clock
from masterba.trace_store import (
    ProjectStore,
    get_question,
    known_nodes,
    list_decision_records,
    save_question,
)

MAX_ANSWER = 2000
_CLOSING_TAG = re.compile(r"<\s*/\s*confirmed", re.IGNORECASE)
_TRACE_REF = re.compile(r"^(REQ-\d{4}|DOC-[A-Z_]+-\d{4}#item\.\d+)$")


class QuestionError(LifecycleError):
    """A question cannot be answered or withdrawn as asked."""


def check_answer(text: str) -> str:
    """The answer as it will be stored; it must be safe to put into a prompt (spec 13 section 5)."""
    answer = text.strip()
    if not answer:
        raise QuestionError("an answer is required")
    if len(answer) > MAX_ANSWER:
        raise QuestionError(f"an answer has at most {MAX_ANSWER} characters")
    if any(unicodedata.category(c) == "Cc" and c not in "\n\t" for c in answer):
        raise QuestionError("an answer may not contain control characters")
    if _CLOSING_TAG.search(answer):
        raise QuestionError("an answer may not contain the closing tag of the confirmed block")
    return answer


def _open(store: ProjectStore, question_id: str, action: str) -> Question:
    question = get_question(store, question_id)
    if question.status is not QuestionStatus.OPEN:
        raise QuestionError(
            f"{question_id} is {question.status.value}; only an open question can be {action}"
        )
    return question


def answer_question(
    store: ProjectStore,
    question_id: str,
    answer: str,
    by: str,
    source: str | None = None,
    today: Clock = dt.date.today,
) -> Question:
    """Create and approve the clarification DR, then save the question as answered."""
    question = _open(store, question_id, "answered")
    if not by.strip():
        raise QuestionError("by must name the person who records the answer")
    text = check_answer(answer)
    note = (source or "").strip() or None
    dr = next(
        (
            d
            for d in list_decision_records(store)
            if d.trigger is DrTrigger.CLARIFICATION
            and d.description.startswith(f"{question_id}:")
            and d.status in (DrStatus.PROPOSED, DrStatus.APPROVED)
        ),
        None,
    )
    if dr is None:
        nodes = known_nodes(store)
        items = [r for r in question.refs if _TRACE_REF.match(r) and r in nodes]
        dr = new_dr(store, DrTrigger.CLARIFICATION, f"{question_id}: {question.text}", items, today)
    if dr.status is DrStatus.PROPOSED:
        dr, _ = approve_dr(store, dr.id, by.strip(), text, note)
    answered = question.model_copy(
        update={
            "status": QuestionStatus.ANSWERED,
            "answer": dr.decision,
            "answered_by": dr.approver,
            "answered_on": today(),
            "dr_id": dr.id,
            "source": note,
        }
    )
    save_question(store, answered, "answer")
    return answered


def withdraw_question(store: ProjectStore, question_id: str) -> Question:
    """Close an open question that no longer applies; no Decision Record is made."""
    withdrawn = _open(store, question_id, "withdrawn").model_copy(
        update={"status": QuestionStatus.WITHDRAWN}
    )
    save_question(store, withdrawn, "withdraw")
    return withdrawn
