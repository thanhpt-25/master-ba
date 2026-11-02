"""Knowledge base: list, upload, replace, remove, search (spec 12, Requirement 14)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile

from masterba.api.auth import User
from masterba.api.deps import checked, project_store, require_role
from masterba.knowledge import HybridRetriever, IncomingFile, add_sources, list_sources
from masterba.knowledge.proposal import remove_with_proposal, replace_with_proposal
from masterba.knowledge.retriever import DEFAULT_K
from masterba.knowledge.safety import MAX_FILE_BYTES
from masterba.knowledge.store import SourceView
from masterba.trace_store import ProjectStore

router = APIRouter(prefix="/api/projects/{pid}/knowledge")
Store = Annotated[ProjectStore, Depends(project_store)]
Viewer = Depends(require_role("viewer"))
Signed = Annotated[User, Depends(require_role("approver"))]


def _source(view: SourceView) -> dict[str, Any]:
    return {**view.source.model_dump(mode="json"), "status": view.status, "reason": view.reason}


async def _incoming(file: UploadFile) -> IncomingFile:
    # One byte past the limit is enough for check_upload to refuse an oversized file.
    return IncomingFile(file.filename or "", await file.read(MAX_FILE_BYTES + 1))


@router.get("", dependencies=[Viewer])
def list_all(store: Store) -> list[dict[str, Any]]:
    return [_source(v) for v in list_sources(store)]


@router.get("/search", dependencies=[Viewer])
def search(
    store: Store, q: Annotated[str, Query()], k: Annotated[int, Query()] = DEFAULT_K
) -> dict[str, Any]:
    retriever = HybridRetriever(store)
    passages = retriever.search(q, k)
    return {"mode": retriever.mode, "passages": [p.model_dump(mode="json") for p in passages]}


@router.post("", status_code=201)
async def upload(store: Store, file: UploadFile, user: Signed) -> dict[str, Any]:
    # `added_by` is always the signed-in user, never a field the client sends (Req. 14.7).
    report = add_sources(store, [await _incoming(file)], user.name)
    if report.refused:
        raise HTTPException(status_code=400, detail=report.refused[0][1])
    if report.skipped:
        name, match = report.skipped[0]
        raise HTTPException(status_code=400, detail=f"{name}: same content as {match}")
    source = report.added[0]
    state = report.statuses[source.id]
    return {
        **source.model_dump(mode="json"),
        "status": state.status,
        "reason": state.reason,
        "notice": report.notice,
    }


@router.put("/{source_id}")
async def replace(store: Store, source_id: str, file: UploadFile, user: Signed) -> dict[str, Any]:
    checked("source", source_id)
    report, dr = replace_with_proposal(store, source_id, await _incoming(file), user.name)
    return {
        **report.after.model_dump(mode="json"),
        "status": report.status.status,
        "reason": report.status.reason,
        "dr_id": dr.id if dr else None,
    }


@router.delete("/{source_id}")
def remove(store: Store, source_id: str, user: Signed) -> dict[str, Any]:
    checked("source", source_id)
    removed, dr = remove_with_proposal(store, source_id)
    return {**removed.model_dump(mode="json"), "dr_id": dr.id if dr else None}
