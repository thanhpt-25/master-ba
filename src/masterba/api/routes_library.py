"""Template sets: the register, sharing, clone, and a project's set (spec 29 section 6.1)."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from masterba import library
from masterba.api.auth import RANK, User
from masterba.api.deps import (
    AppState,
    audit,
    checked,
    current_user,
    project_role,
    project_store,
    require_role,
    state_of,
)
from masterba.api.schemas import CloneBody, ProjectTemplateBody, TitleBody, VisibilityBody
from masterba.library.switch import ISSUED
from masterba.rendering import render_bytes
from masterba.rendering.template import DEFAULT_COMPANY
from masterba.trace_store import ProjectStore, get_config, get_document, latest_documents

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
BUILTIN_TITLE = "MasterBA standard"

router = APIRouter(prefix="/api")
Me = Annotated[User, Depends(current_user)]
Store = Annotated[ProjectStore, Depends(project_store)]
ProjectViewer = Annotated[User, Depends(require_role("viewer"))]
ProjectApprover = Annotated[User, Depends(require_role("approver"))]
ProjectAdmin = Annotated[User, Depends(require_role("admin"))]


def set_json(app: AppState, set_id: str, user: User) -> dict[str, Any]:
    root = app.settings.root
    if set_id == DEFAULT_COMPANY:
        return {
            "id": set_id,
            "title": BUILTIN_TITLE,
            "owner": None,
            "visibility": "public",
            "builtin": True,
            "can_manage": False,
            "types": library.set_types(root, set_id),
        }
    entry = app.templates.entry(set_id) or {}
    manages = app.templates.manages(set_id, user)
    shown: dict[str, Any] = {
        "id": set_id,
        "title": entry.get("title"),
        "owner": entry.get("owner"),
        "visibility": entry.get("visibility", "private"),
        "builtin": False,
        "can_manage": manages,
        "types": library.set_types(root, set_id),
    }
    if manages:
        shown["shared_with"] = list(entry.get("shared_with", []))
    return shown


def visible_set(app: AppState, set_id: str, user: User) -> str:
    """The set id when `user` may see it, else 404 (an invisible set does not exist for them)."""
    if not app.templates.sees(set_id, user):
        raise HTTPException(status_code=404, detail="no such template set")
    return set_id


def managed_set(app: AppState, set_id: str, user: User) -> str:
    visible_set(app, set_id, user)
    if not app.templates.manages(set_id, user):
        raise HTTPException(status_code=403, detail="only the owner of the set may change this")
    return set_id


# -- the register ------------------------------------------------------------------


@router.get("/template-sets")
def list_sets(request: Request, user: Me) -> list[dict[str, Any]]:
    app = state_of(request)
    return [set_json(app, s, user) for s in app.templates.visible(user)]


@router.post("/template-sets/{set_id}/visibility")
def change_visibility(
    request: Request, set_id: str, body: VisibilityBody, user: Me
) -> dict[str, Any]:
    app = state_of(request)
    managed_set(app, set_id, user)
    app.templates.set_visibility(set_id, body.visibility, body.shared_with)
    audit(
        request,
        user.name,
        "template.visibility",
        target=set_id,
        visibility=body.visibility,
        shared_with=body.shared_with if body.visibility == "shared" else [],
    )
    return set_json(app, set_id, user)


@router.post("/template-sets/{set_id}/title")
def change_title(request: Request, set_id: str, body: TitleBody, user: Me) -> dict[str, Any]:
    app = state_of(request)
    managed_set(app, set_id, user)
    app.templates.set_title(set_id, body.title)
    return set_json(app, set_id, user)


@router.post("/template-sets/{set_id}/clone", status_code=201)
def clone_set(request: Request, set_id: str, body: CloneBody, user: Me) -> dict[str, Any]:
    app = state_of(request)
    visible_set(app, set_id, user)
    if RANK[user.role] < RANK["approver"]:
        raise HTTPException(status_code=403, detail="your role may not do this")
    if body.target == DEFAULT_COMPANY or body.target in app.templates.existing():
        raise HTTPException(status_code=400, detail=f"{body.target} is taken; choose another id")
    library.clone(app.settings.root, set_id, body.target)
    title = (app.templates.entry(set_id) or {}).get("title")
    app.templates.create(body.target, user.name, f"{title} (copy)" if title else None)
    audit(request, user.name, "template.clone", target=body.target, source=set_id)
    return set_json(app, body.target, user)


# -- a project's set -----------------------------------------------------------------


def _documents(store: ProjectStore) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for doc, _ in latest_documents(store):
        out.append(
            {
                "id": doc.id,
                "type": doc.type.value,
                "version": doc.version,
                "status": doc.status.value,
                "kept": doc.status in ISSUED,
            }
        )
    return out


@router.get("/projects/{pid}/template")
def project_template(
    request: Request, pid: str, store: Store, user: ProjectViewer
) -> dict[str, Any]:
    app = state_of(request)
    current = get_config(store).company_id
    options = [set_json(app, s, user) for s in app.templates.visible(user)]
    if current not in {o["id"] for o in options}:
        # A share was revoked: the project keeps the set, the picker shows it by name only.
        options.insert(0, {"id": current, "title": None, "builtin": False, "hidden": True})
    return {
        "current": current,
        "can_change": project_role(request, user, pid) == "admin",
        "sets": options,
        "documents": _documents(store),
    }


@router.get("/projects/{pid}/template/coverage")
def project_coverage(
    request: Request, store: Store, user: ProjectViewer, set: str
) -> dict[str, Any]:
    app = state_of(request)
    visible_set(app, set, user)
    return library.project_coverage(store, app.settings.templates, set).to_json()


@router.get("/projects/{pid}/template/preview/{doc_id}.xlsx")
def preview_document(
    request: Request, store: Store, doc_id: str, user: ProjectViewer, set: str
) -> Response:
    app = state_of(request)
    visible_set(app, set, user)
    checked("doc", doc_id)
    doc, _ = get_document(store, doc_id)
    data = render_bytes(store, doc_id, app.settings.templates, company_id=set)
    name = f"{doc_id}.v{doc.version}.{set}.preview.xlsx"
    return Response(
        data, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'}
    )


@router.put("/projects/{pid}/template", response_model=None)
def switch(
    request: Request, store: Store, body: ProjectTemplateBody, user: ProjectAdmin
) -> dict[str, Any] | JSONResponse:
    app = state_of(request)
    visible_set(app, body.set, user)
    try:
        result = library.switch_template(
            store, app.settings.templates, body.set, accept_gaps=body.accept_gaps
        )
    except library.CoverageGapError as exc:
        return JSONResponse({"detail": str(exc), "coverage": exc.report.to_json()}, status_code=409)
    audit(
        request,
        user.name,
        "project.template",
        project=store.project_id,
        target=body.set,
        rendered=list(result.rendered),
        gaps=result.coverage.gaps,
    )
    return result.to_json()


@router.post("/projects/{pid}/documents/{doc_id}/reissue")
def reissue_document(
    request: Request, store: Store, doc_id: str, user: ProjectApprover, version: int | None = None
) -> dict[str, Any]:
    app = state_of(request)
    checked("doc", doc_id)
    doc, _ = get_document(store, doc_id, version)
    if doc.status not in ISSUED:
        raise HTTPException(
            status_code=400, detail="only an approved version is re-issued; drafts render anyway"
        )
    path = library.reissue(store, app.settings.templates, doc_id, doc.version)
    audit(
        request,
        user.name,
        "document.reissue",
        project=store.project_id,
        target=f"{doc_id} v{doc.version}",
        set=get_config(store).company_id,
    )
    return {"id": doc_id, "version": doc.version, "file": path.name}
