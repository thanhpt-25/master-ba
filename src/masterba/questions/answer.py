"""Answering a question: the answer becomes an approved clarification Decision Record."""

import datetime as dt
import re
import unicodedata

from masterba.change.lifecycle import LifecycleError, approve_dr, new_dr
from masterba.guard.detect import describe, has_secret
from masterba.models import Question
from masterba.models.enums import DrStatus, DrTrigger, ItemStatus, QuestionStatus
from masterba.questions.ledger import Clock
from masterba.team.workspace import objection_key
from masterba.trace_store import (
    ProjectStore,
    get_question,
    known_nodes,
    list_decision_records,
    list_requirements,
    save_question,
)

MAX_ANSWER = 2000
_CLOSING_TAG = re.compile(r"<\s*/\s*confirmed", re.IGNORECASE)
_TRACE_REF = re.compile(r"^(REQ-\d{4}|DOC-[A-Z_]+-\d{4}#item\.\d+)$")
_LINES = re.compile(r"^(intake/[^#/]+)#L(\d+)-L(\d+)$")


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
    secret = has_secret(answer)  # spec 30 section 3.2
    if secret is not None:
        raise QuestionError(f"an answer may not contain a secret ({describe(secret)})")
    return answer


def _lines(ref: str) -> tuple[str, int, int] | None:
    found = _LINES.match(ref)
    return (found[1], int(found[2]), int(found[3])) if found else None


def impact_items(store: ProjectStore, question: Question) -> list[str]:
    """The trace nodes an answer reaches: stored refs, and requirements citing the intake lines.

    A ref that names nothing stored (an unstored draft item) is dropped; the answer is then only a
    confirmed fact for later runs (spec 13 section 4).
    """
    nodes = known_nodes(store)
    items = [r for r in question.refs if _TRACE_REF.match(r) and r in nodes]
    asked = [a for ref in question.refs if (a := _lines(ref))]
    for requirement in list_requirements(store):
        cited = _lines(requirement.source_ref)
        if (
            requirement.status is ItemStatus.ACTIVE
            and cited
            and any(cited[0] == a[0] and cited[1] <= a[2] and a[1] <= cited[2] for a in asked)
        ):
            items.append(requirement.id)
    return list(dict.fromkeys(items))


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
    waive: bool = False,
) -> Question:
    """Create and approve the clarification DR, then save the question as answered.

    `waive`: the customer accepts the draft as it is, so QA may not block on this objection
    again when its run resumes (spec 13 section 6.1).
    """
    question = _open(store, question_id, "answered")
    if waive and objection_key(question.text) is None:
        raise QuestionError(f"{question_id} is not a QA objection; only those can be waived")
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
        items = impact_items(store, question)
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
            "waived": waive,
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
