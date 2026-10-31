"""Company templates: upload a sample, review, confirm (spec 09 section 7). Admin only."""

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from masterba import calibration
from masterba.api.auth import User
from masterba.api.deps import require_role, state_of
from masterba.api.schemas import SetColumnBody
from masterba.calibration.profile import MAX_BYTES
from masterba.calibration.store import paths_for
from masterba.models.enums import DocType

router = APIRouter(prefix="/api/templates", dependencies=[Depends(require_role("admin"))])
Admin = Depends(require_role("admin"))


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
def list_templates(request: Request) -> list[dict[str, str]]:
    return calibration.list_templates(state_of(request).settings.root)


@router.post("/{company}/{doc_type}/calibrate", status_code=201)
async def calibrate(
    request: Request, company: str, doc_type: str, file: UploadFile, replace: bool = False
) -> dict[str, Any]:
    kind = _doc_type(doc_type)
    root = state_of(request).settings.root
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
    return {**_summary(root, company, kind), "messages": list(result.messages)}


@router.get("/{company}/{doc_type}")
def read_template(request: Request, company: str, doc_type: str) -> dict[str, Any]:
    return _summary(state_of(request).settings.root, company, _doc_type(doc_type))


@router.put("/{company}/{doc_type}/mapping")
def set_column(
    request: Request, company: str, doc_type: str, body: SetColumnBody
) -> dict[str, Any]:
    root = state_of(request).settings.root
    kind = _doc_type(doc_type)
    calibration.set_column(root, company, kind, body.sheet, body.col, body.field)
    return _summary(root, company, kind)


@router.post("/{company}/{doc_type}/preview")
def preview(request: Request, company: str, doc_type: str) -> dict[str, Any]:
    shown = calibration.preview(state_of(request).settings.root, company, _doc_type(doc_type))
    return {"differences": list(shown.differences)}


@router.get("/{company}/{doc_type}/preview.xlsx")
def preview_file(request: Request, company: str, doc_type: str) -> FileResponse:
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
def confirm(request: Request, company: str, doc_type: str, user: User = Admin) -> dict[str, Any]:
    root = state_of(request).settings.root
    kind = _doc_type(doc_type)
    calibration.confirm(root, company, kind, user.name)
    return _summary(root, company, kind)


@router.post("/{company}/{doc_type}/unconfirm")
def unconfirm(request: Request, company: str, doc_type: str) -> dict[str, Any]:
    root = state_of(request).settings.root
    kind = _doc_type(doc_type)
    calibration.unconfirm(root, company, kind)
    return _summary(root, company, kind)
