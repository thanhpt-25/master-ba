"""Render a stored document into the project folder and commit it (spec 02 section 3)."""

from pathlib import Path

from masterba.rendering.engine import render_document
from masterba.rendering.template import resolve_template
from masterba.rendering.xlsxio import workbook_bytes
from masterba.trace_store import ProjectStore, get_config, get_document
from masterba.trace_store.git import commit_paths


def render_to_project(
    store: ProjectStore, doc_id: str, templates_root: Path, version: int | None = None
) -> Path:
    """Write `xlsx/<type>/<DOC_ID>.v<n>.xlsx` as one commit; nothing is written on failure."""
    doc, content = get_document(store, doc_id, version)
    template = resolve_template(templates_root, get_config(store).company_id, doc.type)
    data = workbook_bytes(render_document(doc, content, template))
    path = store.path / "xlsx" / doc.type.value.lower() / f"{doc.id}.v{doc.version}.xlsx"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    commit_paths(store.root, [path], f"render({store.project_id}): xlsx {doc.id} v{doc.version}")
    return path
