"""Phase reviews: list, approve, reject (spec 15 section 7)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from masterba.api.auth import User
from masterba.api.deps import project_store, require_role, state_of
from masterba.api.jobs import JobBusyError
from masterba.api.schemas import RejectBody
from masterba.models.enums import ReviewStage
from masterba.review import STAGE_DOCS, phase_state
from masterba.review.actions import approve_phase, check_rejection, reject_phase
from masterba.trace_store import ProjectStore, get_config, get_question, list_reviews

router = APIRouter(prefix="/api/projects/{pid}")
Store = Annotated[ProjectStore, Depends(project_store)]
Viewer = Depends(require_role("viewer"))
Signed = Annotated[User, Depends(require_role("approver"))]


def _stage(stage: str) -> ReviewStage:
    try:
        return ReviewStage(stage)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="no such stage") from exc


@router.get("/reviews", dependencies=[Viewer])
def reviews(store: Store) -> dict[str, Any]:
    return {
        "review_gates": get_config(store).review_gates,
        "phases": [
            {"stage": s.value, "state": phase_state(store, s), "documents": list(STAGE_DOCS[s])}
            for s in ReviewStage
        ],
        "reviews": [r.model_dump(mode="json") for r in list_reviews(store)],
    }


@router.post("/stages/{stage}/approve")
def approve(request: Request, store: Store, stage: str, user: Signed) -> dict[str, Any]:
    # `by` is the signed-in user, never a field the client sends.
    review = approve_phase(store, state_of(request).settings.templates, _stage(stage), user.name)
    return {
        "review": review.model_dump(mode="json"),
        "open_questions": [
            {"id": qid, "text": get_question(store, qid).text} for qid in review.open_questions
        ],
    }


@router.post("/stages/{stage}/reject", status_code=202)
def reject(
    request: Request, store: Store, stage: str, body: RejectBody, user: Signed
) -> dict[str, Any]:
    phase = _stage(stage)
    check_rejection(store, phase, body.comments)  # refuse before a job is queued
    app = state_of(request)
    settings = app.settings

    def work() -> dict[str, Any]:
        reviser = settings.llm_factory(settings.model)
        qa = settings.llm_factory(settings.qa_model) if settings.qa_model else None
        review, result = reject_phase(
            store, settings.templates, phase, user.name, body.comments, reviser, qa_llm=qa
        )
        return {
            "review": review.model_dump(mode="json"),
            "revision": result.to_json(),
            "status": "escalated" if result.escalated else "done",
        }

    try:
        job = app.jobs.submit(store.project_id, f"review:{phase.value}", work)
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.to_json()
