"""Customer questions: list, show, answer, withdraw (spec 13 section 6)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query

from masterba.api.auth import User
from masterba.api.deps import checked, project_store, require_role
from masterba.api.schemas import AnswerBody
from masterba.models import Question
from masterba.models.enums import QuestionStatus
from masterba.questions.answer import answer_question, withdraw_question
from masterba.trace_store import ProjectStore, get_decision_record, get_question, list_questions

router = APIRouter(prefix="/api/projects/{pid}/questions")
Store = Annotated[ProjectStore, Depends(project_store)]
Viewer = Depends(require_role("viewer"))
Approver = Depends(require_role("approver"))
Signed = Annotated[User, Depends(require_role("approver"))]


def _view(store: ProjectStore, question: Question) -> dict[str, Any]:
    dr = get_decision_record(store, question.dr_id) if question.dr_id else None
    return {
        "question": question.model_dump(mode="json"),
        "dr": dr.model_dump(mode="json") if dr else None,
    }


@router.get("", dependencies=[Viewer])
def list_all(store: Store, status: Annotated[QuestionStatus | None, Query()] = None) -> list[Any]:
    found = [q for q in list_questions(store) if status in (None, q.status)]
    return [q.model_dump(mode="json") for q in found]


@router.get("/{question_id}", dependencies=[Viewer])
def read(store: Store, question_id: str) -> dict[str, Any]:
    checked("question", question_id)
    return _view(store, get_question(store, question_id))


@router.post("/{question_id}/answer")
def answer(store: Store, question_id: str, body: AnswerBody, user: Signed) -> dict[str, Any]:
    checked("question", question_id)
    # The recorded name is the signed-in user, never a field the client sends.
    return _view(store, answer_question(store, question_id, body.answer, user.name, body.source))


@router.post("/{question_id}/withdraw", dependencies=[Approver])
def withdraw(store: Store, question_id: str) -> dict[str, Any]:
    checked("question", question_id)
    return _view(store, withdraw_question(store, question_id))
