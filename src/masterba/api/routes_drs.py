"""Decision Records: list, create, approve, reject, propagate, close, diff (spec 08 section 3)."""

import subprocess
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request

from masterba.api.auth import User
from masterba.api.deps import (
    checked,
    limit_detail,
    metered,
    project_store,
    require_quota,
    require_role,
    state_of,
)
from masterba.api.jobs import Job, JobBusyError
from masterba.api.schemas import DecisionBody, FromRunBody, NewDrBody
from masterba.change import (
    approve_dr,
    auto_propagates,
    close_dr,
    dr_diff,
    dr_from_run,
    new_dr,
    propagate_dr,
    reject_dr,
    rows,
)
from masterba.models import DecisionRecord
from masterba.models.enums import DrStatus
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


def _shown(store: ProjectStore, dr: DecisionRecord) -> dict[str, Any]:
    """The record plus `rejected`: closed without an impact analysis (as 却下 in 変更管理台帳)."""
    rejected = dr.status is DrStatus.CLOSED and get_dr_extra(store, dr.id, "impact") is None
    return {**dr.model_dump(mode="json"), "rejected": rejected}


@router.get("", dependencies=[Viewer])
def list_drs(store: Store) -> list[dict[str, Any]]:
    return [_shown(store, d) for d in list_decision_records(store)]


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
        "dr": _shown(store, dr),
        "impact": get_dr_extra(store, dr_id, "impact"),
        "propagation": get_dr_extra(store, dr_id, "propagation"),
    }


@router.post("/{dr_id}/approve")
def approve(
    request: Request, store: Store, dr_id: str, body: DecisionBody, user: Signed
) -> dict[str, Any]:
    checked("dr", dr_id)
    dr, impact = approve_dr(store, dr_id, user.name, body.decision, body.rationale)
    return {
        "dr": dr.model_dump(mode="json"),
        "impact": impact.to_json(),
        **auto_propagation(request, store, dr_id, user),
    }


@router.post("/{dr_id}/reject")
def reject(store: Store, dr_id: str, body: DecisionBody, user: Signed) -> dict[str, Any]:
    checked("dr", dr_id)
    return reject_dr(store, dr_id, user.name, body.decision, body.rationale).model_dump(mode="json")


@router.post("/{dr_id}/close", dependencies=[Approver])
def close(store: Store, dr_id: str) -> dict[str, Any]:
    checked("dr", dr_id)
    return close_dr(store, dr_id).model_dump(mode="json")


def submit_propagation(request: Request, store: ProjectStore, dr_id: str, user: User) -> Job:
    """Queue the `propagate:<dr>` job; raises JobBusyError when another job runs."""
    app = state_of(request)
    settings = app.settings
    kind = f"propagate:{dr_id}"
    llm_factory = metered(app, user, store.project_id, kind)

    def work() -> dict[str, Any]:
        reviser = llm_factory(settings.model)
        qa = llm_factory(settings.qa_model) if settings.qa_model else None
        result = propagate_dr(store, settings.templates, dr_id, reviser, qa_llm=qa)
        payload = result.to_json()
        payload["dr_status"] = payload["status"]
        payload["status"] = (
            "waiting_for_input" if result.waiting else "escalated" if result.escalated else "done"
        )
        return payload

    return app.jobs.submit(store.project_id, kind, work, user.name)


def auto_propagation(
    request: Request, store: ProjectStore, dr_id: str, user: User
) -> dict[str, Any]:
    """Extra response fields after an approval: the job, or why none was started (spec 07 5.1)."""
    if not auto_propagates(store, get_decision_record(store, dr_id)):
        return {}
    limit = limit_detail(state_of(request), user)
    if limit is not None:
        return {"propagation_note": f"{limit['message']}; press Propagate after the reset"}
    try:
        return {"job": submit_propagation(request, store, dr_id, user).to_json()}
    except JobBusyError as exc:
        return {"propagation_note": f"{exc}; press Propagate when it ends"}


@router.post("/{dr_id}/propagate", status_code=202)
def propagate(request: Request, store: Store, dr_id: str, user: Signed) -> dict[str, Any]:
    checked("dr", dr_id)
    get_decision_record(store, dr_id)
    require_quota(state_of(request), user)
    try:
        job = submit_propagation(request, store, dr_id, user)
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


@router.get("/{dr_id}/history", dependencies=[Viewer])
def history(store: Store, dr_id: str) -> list[dict[str, str]]:
    """The commits that touched the record and its derived files, oldest first (spec 26 s. 7)."""
    checked("dr", dr_id)
    get_decision_record(store, dr_id)
    folder = f"{store.project_id}/decision-records"
    done = subprocess.run(
        [
            "git",
            "log",
            "--reverse",
            "--format=%H%x1f%an%x1f%aI%x1f%s",
            "--",
            f"{folder}/{dr_id}.json",
            f"{folder}/{dr_id}.*.json",
        ],  # fmt: skip
        cwd=store.root,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise HTTPException(status_code=500, detail="the record history is unavailable")
    entries = []
    for line in done.stdout.splitlines():
        sha, author, when, subject = line.split("\x1f", 3)
        entries.append({"commit": sha[:10], "author": author, "time": when, "subject": subject})
    return entries
