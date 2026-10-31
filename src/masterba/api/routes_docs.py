"""Documents, versions, downloads, diffs, team runs and the audit log (spec 08 section 3)."""

import json
import subprocess
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from masterba.api.deps import checked, project_store, require_role
from masterba.change import rows
from masterba.change.diffview import diff_versions
from masterba.diff import Classification
from masterba.models import payload_items
from masterba.trace_store import (
    NotFoundError,
    ProjectStore,
    document_versions,
    get_document,
    latest_documents,
)

router = APIRouter(prefix="/api/projects/{pid}")
Store = Annotated[ProjectStore, Depends(project_store)]
Viewer = Depends(require_role("viewer"))


def run_summaries(store: ProjectStore) -> list[dict[str, Any]]:
    """Team run summaries, newest first."""
    folder = store.path / "runs"
    if not folder.exists():
        return []
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("RUN-????/team-summary.json"), reverse=True):
        summary = json.loads(path.read_text("utf-8"))
        summary["resumable"] = (
            summary.get("status") == "escalated" and (path.parent / "checkpoint.json").is_file()
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


@router.get("/documents/{doc_id}/xlsx", dependencies=[Viewer])
def download_xlsx(store: Store, doc_id: str, version: int | None = None) -> FileResponse:
    checked("doc", doc_id)
    chosen = _version(store, doc_id, version)
    doc, _ = get_document(store, doc_id, chosen)
    path = store.path / "xlsx" / doc.type.value.lower() / f"{doc_id}.v{chosen}.xlsx"
    if not path.exists():
        raise HTTPException(status_code=404, detail="this version was never rendered")
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
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


@router.get("/runs", dependencies=[Viewer])
def list_runs(store: Store) -> list[dict[str, Any]]:
    return run_summaries(store)


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
