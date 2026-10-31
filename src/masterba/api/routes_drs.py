"""Decision Records: list, create, approve, reject, propagate, close, diff (spec 08 section 3)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from masterba.api.auth import User
from masterba.api.deps import checked, project_store, require_role, state_of
from masterba.api.jobs import JobBusyError
from masterba.api.schemas import DecisionBody, FromRunBody, NewDrBody
from masterba.change import (
    approve_dr,
    close_dr,
    dr_diff,
    dr_from_run,
    new_dr,
    propagate_dr,
    reject_dr,
    rows,
)
from masterba.trace_store import (
    ProjectStore,
    get_decision_record,
    get_dr_extra,
    list_decision_records,
)

router = APIRouter(prefix="/api/projects/{pid}/drs")
Store = Annotated[ProjectStore, Depends(project_store)]
Viewer = Depends(require_role("viewer"))
Approver = Depends(require_role("approver"))
Signed = Annotated[User, Depends(require_role("approver"))]


@router.get("", dependencies=[Viewer])
def list_drs(store: Store) -> list[dict[str, Any]]:
    return [d.model_dump(mode="json") for d in list_decision_records(store)]


@router.post("", status_code=201, dependencies=[Approver])
def create_dr(store: Store, body: NewDrBody) -> dict[str, Any]:
    return new_dr(store, body.trigger, body.description, body.items).model_dump(mode="json")


@router.post("/from-run", status_code=201, dependencies=[Approver])
def create_dr_from_run(store: Store, body: FromRunBody) -> dict[str, Any]:
    return dr_from_run(store, body.run_id).model_dump(mode="json")


@router.get("/{dr_id}", dependencies=[Viewer])
def read_dr(store: Store, dr_id: str) -> dict[str, Any]:
    checked("dr", dr_id)
    dr = get_decision_record(store, dr_id)
    return {
        "dr": dr.model_dump(mode="json"),
        "impact": get_dr_extra(store, dr_id, "impact"),
        "propagation": get_dr_extra(store, dr_id, "propagation"),
    }


@router.post("/{dr_id}/approve")
def approve(store: Store, dr_id: str, body: DecisionBody, user: Signed) -> dict[str, Any]:
    checked("dr", dr_id)
    dr, impact = approve_dr(store, dr_id, user.name, body.decision, body.rationale)
    return {"dr": dr.model_dump(mode="json"), "impact": impact.to_json()}


@router.post("/{dr_id}/reject")
def reject(store: Store, dr_id: str, body: DecisionBody, user: Signed) -> dict[str, Any]:
    checked("dr", dr_id)
    return reject_dr(store, dr_id, user.name, body.decision, body.rationale).model_dump(mode="json")


@router.post("/{dr_id}/close", dependencies=[Approver])
def close(store: Store, dr_id: str) -> dict[str, Any]:
    checked("dr", dr_id)
    return close_dr(store, dr_id).model_dump(mode="json")


@router.post("/{dr_id}/propagate", status_code=202, dependencies=[Approver])
def propagate(request: Request, store: Store, dr_id: str) -> dict[str, Any]:
    checked("dr", dr_id)
    get_decision_record(store, dr_id)
    app = state_of(request)
    settings = app.settings

    def work() -> dict[str, Any]:
        reviser = settings.llm_factory(settings.model)
        qa = settings.llm_factory(settings.qa_model) if settings.qa_model else None
        result = propagate_dr(store, settings.templates, dr_id, reviser, qa_llm=qa)
        payload = result.to_json()
        payload["dr_status"] = payload["status"]
        payload["status"] = "escalated" if result.escalated else "done"
        return payload

    try:
        job = app.jobs.submit(store.project_id, f"propagate:{dr_id}", work)
    except JobBusyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.to_json()


@router.get("/{dr_id}/diff", dependencies=[Viewer])
def diff(store: Store, dr_id: str, structural_only: bool = False) -> dict[str, Any]:
    checked("dr", dr_id)
    get_decision_record(store, dr_id)
    return {
        "documents": [
            {
                "doc_id": d.doc_id,
                "old_version": d.old_version,
                "new_version": d.new_version,
                "rows": rows(d),
            }
            for d in dr_diff(store, dr_id, structural_only)
        ]
    }
