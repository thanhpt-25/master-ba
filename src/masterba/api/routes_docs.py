"""Documents, versions, downloads, diffs, team runs and the audit log (spec 08 section 3)."""

import json
import subprocess
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response

from masterba.api.deps import checked, project_store, require_role, state_of
from masterba.change import rows
from masterba.change.diffview import diff_versions
from masterba.diff import Classification
from masterba.library.switch import ISSUED
from masterba.models import payload_items
from masterba.models.enums import QuestionOrigin, QuestionStatus
from masterba.rendering import RenderError, render_bytes
from masterba.rendering.history import build_context
from masterba.rendering.preview import preview_sheets
from masterba.rendering.registers import Register, register_bytes, register_filename
from masterba.trace_store import (
    InvalidDocumentError,
    NotFoundError,
    ProjectStore,
    document_versions,
    get_document,
    get_intake,
    latest_documents,
    list_intakes,
    list_questions,
)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

router = APIRouter(prefix="/api/projects/{pid}")
Store = Annotated[ProjectStore, Depends(project_store)]
Viewer = Depends(require_role("viewer"))


def run_summaries(store: ProjectStore, busy: bool = False) -> list[dict[str, Any]]:
    """Team run summaries, newest first.

    `busy`: the project has a running job. A resumed run keeps its old `escalated`
    summary until it finishes, so nothing is offered for resume meanwhile.
    """
    folder = store.path / "runs"
    if not folder.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("RUN-????/team-summary.json"), reverse=True):
        summary = json.loads(path.read_text("utf-8"))
        pending = [
            q
            for q in list_questions(store)
            if q.run_id == summary.get("run_id")
            and q.origin is QuestionOrigin.QA_BLOCKER
            and q.status is QuestionStatus.OPEN
        ]
        summary["waiting_questions"] = [{"id": q.id, "text": q.text} for q in pending]
        summary["resumable"] = (
            not busy
            and summary.get("status") in {"escalated", "waiting_for_input"}
            and not pending
            and (path.parent / "checkpoint.json").is_file()
        )
        out.append(summary)
    return out


@router.get("/documents", dependencies=[Viewer])
def list_documents(store: Store) -> list[dict[str, Any]]:
    return [
        {
            "document": doc.model_dump(mode="json"),
            "versions": document_versions(store, doc.id),
            "items": sum(1 for _ in payload_items(content)),
        }
        for doc, content in latest_documents(store)
    ]


def _version(store: ProjectStore, doc_id: str, version: int | None) -> int:
    versions = document_versions(store, doc_id)
    if not versions:
        raise HTTPException(status_code=404, detail="no such document")
    chosen = version if version is not None else versions[-1]
    if chosen not in versions:
        raise HTTPException(status_code=404, detail="no such version")
    return chosen


@router.get("/documents/{doc_id}", dependencies=[Viewer])
def read_document(store: Store, doc_id: str, version: int | None = None) -> dict[str, Any]:
    checked("doc", doc_id)
    chosen = _version(store, doc_id, version)
    doc, content = get_document(store, doc_id, chosen)
    return {
        "document": doc.model_dump(mode="json"),
        "versions": document_versions(store, doc_id),
        "content": content.model_dump(mode="json"),
    }


@router.get("/documents/{doc_id}/preview", dependencies=[Viewer])
def preview_document(store: Store, doc_id: str, version: int | None = None) -> dict[str, Any]:
    """The default workbook layout as JSON (spec 19 section 14); writes nothing."""
    checked("doc", doc_id)
    chosen = _version(store, doc_id, version)
    doc, content = get_document(store, doc_id, chosen)
    return {
        "document": doc.model_dump(mode="json"),
        "versions": document_versions(store, doc_id),
        "sheets": preview_sheets(doc, content, build_context(store, doc, content)),
    }


@router.get("/documents/{doc_id}/xlsx", dependencies=[Viewer])
def download_xlsx(
    request: Request, store: Store, doc_id: str, version: int | None = None
) -> Response:
    """The workbook as it renders now (current trace links, approvals, layout; spec 28 section 4).

    Nothing is written. An approved or superseded version is the issued file: its committed
    workbook is served, so a template switch never changes it (spec 29 section 5.1). The
    committed file is also the fallback when rendering fails.
    """
    checked("doc", doc_id)
    chosen = _version(store, doc_id, version)
    doc, _ = get_document(store, doc_id, chosen)
    path = store.path / "xlsx" / doc.type.value.lower() / f"{doc_id}.v{chosen}.xlsx"
    if doc.status in ISSUED and path.exists():
        data = path.read_bytes()
    else:
        try:
            data = render_bytes(store, doc_id, state_of(request).settings.templates, chosen)
        except RenderError:
            if not path.exists():
                raise HTTPException(
                    status_code=404, detail="this version was never rendered"
                ) from None
            data = path.read_bytes()
    return Response(
        data,
        media_type=XLSX,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


@router.get("/registers/{register}.xlsx", dependencies=[Viewer])
def download_register(store: Store, register: Register) -> Response:
    """変更管理台帳 or QA管理表, printed from the stored DRs and questions (spec 27)."""
    name = quote(register_filename(store, register))
    # An ASCII `filename` first as the RFC 6266 fallback for clients that skip `filename*`.
    plain = f"{store.project_id}_{register}.xlsx"
    return Response(
        register_bytes(store, register),
        media_type=XLSX,
        headers={
            "Content-Disposition": f"attachment; filename=\"{plain}\"; filename*=UTF-8''{name}"
        },
    )


@router.get("/documents/{doc_id}/diff", dependencies=[Viewer])
def diff_document(
    store: Store,
    doc_id: str,
    from_: Annotated[int, Query(alias="from")],
    to: int,
    structural_only: bool = False,
) -> dict[str, Any]:
    checked("doc", doc_id)
    old, new = _version(store, doc_id, from_), _version(store, doc_id, to)
    diff = diff_versions(store, doc_id, old, new)
    result = rows(diff)
    if structural_only:
        result = [r for r in result if r["classification"] != Classification.REWORDED_ONLY.value]
    return {"doc_id": doc_id, "from": old, "to": new, "rows": result}


@router.get("/intake", dependencies=[Viewer])
def list_intake_files(store: Store) -> list[dict[str, Any]]:
    """The project's intake files for the Documents tree (spec 26 section 6)."""
    out = []
    for name in list_intakes(store):
        text = get_intake(store, name)
        size = len(text.encode("utf-8"))
        out.append({"name": name, "size": size, "lines": len(text.splitlines())})
    return out


@router.get("/intake/{name}", dependencies=[Viewer])
def read_intake_file(store: Store, name: str) -> dict[str, str]:
    try:
        return {"name": name, "text": get_intake(store, name)}
    except (InvalidDocumentError, NotFoundError) as exc:
        raise HTTPException(status_code=404, detail="no such intake file") from exc


@router.get("/runs", dependencies=[Viewer])
def list_runs(request: Request, store: Store) -> list[dict[str, Any]]:
    busy = state_of(request).jobs.running(store.project_id) is not None
    return run_summaries(store, busy)


@router.get("/runs/{run_id}", dependencies=[Viewer])
def read_run(store: Store, run_id: str) -> dict[str, Any]:
    checked("run", run_id)
    folder = store.path / "runs" / run_id
    if not (folder / "team-summary.json").exists():
        raise HTTPException(status_code=404, detail="no such run")
    return {
        name: json.loads((folder / f"{file}.json").read_text("utf-8"))
        for name, file in (
            ("summary", "team-summary"),
            ("tasks", "team-tasks"),
            ("mailbox", "mailbox"),
        )
        if (folder / f"{file}.json").exists()
    }


@router.get("/activity", dependencies=[Viewer])
def activity(
    store: Store, limit: Annotated[int, Query(ge=1, le=500)] = 100
) -> list[dict[str, str]]:
    """The audit log: git commits that touched this project, newest first."""
    done = subprocess.run(
        [
            "git",
            "log",
            f"-n{limit}",
            "--format=%H%x1f%an%x1f%aI%x1f%s",
            "--",
            store.project_id,
        ],  # fmt: skip
        cwd=store.root,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        raise HTTPException(status_code=500, detail="the audit log is unavailable")
    entries = []
    for line in done.stdout.splitlines():
        sha, author, when, subject = line.split("\x1f", 3)
        entries.append({"commit": sha[:10], "author": author, "time": when, "subject": subject})
    return entries


__all__ = ["NotFoundError", "router", "run_summaries"]
