"""Company templates: upload a sample, review, confirm (spec 09 section 7).

Access follows the template library (spec 29 section 6.1): reading needs the set to be
visible, a new set needs approver or above and belongs to its uploader, everything else needs
the owner of the set or an admin.
"""

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from masterba import calibration
from masterba.api.auth import RANK, User
from masterba.api.deps import current_user, state_of
from masterba.api.routes_library import managed_set, visible_set
from masterba.api.schemas import SetColumnBody
from masterba.calibration.profile import MAX_BYTES
from masterba.calibration.store import paths_for
from masterba.models.enums import DocType

router = APIRouter(prefix="/api/templates")
Signed = Depends(current_user)


def _doc_type(value: str) -> DocType:
    try:
        return DocType(value)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="no such document type") from exc


def _summary(root: Path, company: str, doc_type: DocType) -> dict[str, Any]:
    draft = calibration.load_draft(root, company, doc_type)
    return {
        "company": company,
        "doc_type": doc_type.value,
        "state": calibration.state_of(root, company, doc_type),
        "mapping": draft.model_dump(mode="json"),
        "problems": calibration.check(root, company, doc_type),
    }


@router.get("")
def list_templates(request: Request, user: User = Signed) -> list[dict[str, str]]:
    app = state_of(request)
    rows = calibration.list_templates(app.settings.root)
    return [r for r in rows if app.templates.sees(r["company"], user)]


@router.post("/{company}/{doc_type}/calibrate", status_code=201)
async def calibrate(
    request: Request,
    company: str,
    doc_type: str,
    file: UploadFile,
    replace: bool = False,
    user: User = Signed,
) -> dict[str, Any]:
    kind = _doc_type(doc_type)
    app = state_of(request)
    root = app.settings.root
    if RANK[user.role] < RANK["approver"]:
        raise HTTPException(status_code=403, detail="your role may not do this")
    new_set = company not in app.templates.existing()
    if not new_set:
        managed_set(app, company, user)
    raw = await file.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise HTTPException(status_code=400, detail="the sample is larger than 5 MB")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".xlsx":
        raise HTTPException(status_code=400, detail="upload an .xlsx workbook")
    with tempfile.TemporaryDirectory() as scratch:
        sample = Path(scratch) / "sample.xlsx"
        sample.write_bytes(raw)
        result = calibration.calibrate(root, company, kind, sample, replace=replace)
    if new_set:
        app.templates.create(company, user.name)
    return {**_summary(root, company, kind), "messages": list(result.messages)}


@router.get("/{company}/{doc_type}")
def read_template(
    request: Request, company: str, doc_type: str, user: User = Signed
) -> dict[str, Any]:
    app = state_of(request)
    visible_set(app, company, user)
    return _summary(app.settings.root, company, _doc_type(doc_type))


@router.put("/{company}/{doc_type}/mapping")
def set_column(
    request: Request, company: str, doc_type: str, body: SetColumnBody, user: User = Signed
) -> dict[str, Any]:
    managed_set(state_of(request), company, user)
    root = state_of(request).settings.root
    kind = _doc_type(doc_type)
    calibration.set_column(root, company, kind, body.sheet, body.col, body.field)
    return _summary(root, company, kind)


@router.post("/{company}/{doc_type}/preview")
def preview(request: Request, company: str, doc_type: str, user: User = Signed) -> dict[str, Any]:
    managed_set(state_of(request), company, user)
    shown = calibration.preview(state_of(request).settings.root, company, _doc_type(doc_type))
    return {"differences": list(shown.differences)}


@router.get("/{company}/{doc_type}/preview.xlsx")
def preview_file(
    request: Request, company: str, doc_type: str, user: User = Signed
) -> FileResponse:
    managed_set(state_of(request), company, user)
    kind = _doc_type(doc_type)
    root = state_of(request).settings.root
    path = paths_for(root, company, kind).preview
    if not path.exists():
        raise HTTPException(status_code=404, detail="render a preview first")
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/{company}/{doc_type}/confirm")
def confirm(request: Request, company: str, doc_type: str, user: User = Signed) -> dict[str, Any]:
    managed_set(state_of(request), company, user)
    root = state_of(request).settings.root
    kind = _doc_type(doc_type)
    calibration.confirm(root, company, kind, user.name)
    return _summary(root, company, kind)


@router.post("/{company}/{doc_type}/unconfirm")
def unconfirm(request: Request, company: str, doc_type: str, user: User = Signed) -> dict[str, Any]:
    managed_set(state_of(request), company, user)
    root = state_of(request).settings.root
    kind = _doc_type(doc_type)
    calibration.unconfirm(root, company, kind)
    return _summary(root, company, kind)
