"""Switch a project's template set, re-issue an approved version (spec 29 sections 4 and 5)."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from masterba.library.coverage import Coverage, coverage
from masterba.models import Document, Payload
from masterba.models.enums import DocStatus, DocType
from masterba.rendering.engine import render_document
from masterba.rendering.history import build_context
from masterba.rendering.project import xlsx_path
from masterba.rendering.template import DEFAULT_COMPANY, resolve_template
from masterba.rendering.xlsxio import workbook_bytes
from masterba.trace_store import ProjectStore, get_config, get_document, latest_documents
from masterba.trace_store.git import commit_paths
from masterba.trace_store.store import write_config

ISSUED = frozenset({DocStatus.APPROVED, DocStatus.SUPERSEDED})


class UnknownSetError(ValueError):
    """No template set with this id."""


class CoverageGapError(ValueError):
    """The set drops data the built-in set prints, and the caller did not accept that."""

    def __init__(self, report: Coverage) -> None:
        super().__init__(f"{report.set_id} does not print {report.gaps} kind(s) of data")
        self.report = report


@dataclass(frozen=True)
class SwitchResult:
    set_id: str
    coverage: Coverage
    rendered: tuple[str, ...]
    kept: tuple[str, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "set": self.set_id,
            "coverage": self.coverage.to_json(),
            "rendered": list(self.rendered),
            "kept": list(self.kept),
        }


def set_exists(templates_root: Path, set_id: str) -> bool:
    if set_id == DEFAULT_COMPANY:
        return True
    if Path(set_id).name != set_id or set_id in {"", ".", ".."}:
        return False
    return (templates_root / "companies" / set_id).is_dir()


def project_types(store: ProjectStore) -> list[DocType]:
    """The document types of the project, or every type when it has none yet."""
    found = {doc.type for doc, _ in latest_documents(store)}
    return [t for t in DocType if t in found] or [t for t in DocType if t is not DocType.TEST_UAT]


def project_coverage(store: ProjectStore, templates_root: Path, set_id: str) -> Coverage:
    if not set_exists(templates_root, set_id):
        raise UnknownSetError(f"no template set {set_id}")
    return coverage(templates_root, set_id, project_types(store))


def _write(
    store: ProjectStore, templates_root: Path, set_id: str, doc: Document, content: Payload
) -> Path:
    """Render one version with `set_id` into its committed place (no commit)."""
    template = resolve_template(templates_root, set_id, doc.type)
    context = build_context(store, doc, content)
    path = xlsx_path(store, doc)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(workbook_bytes(render_document(doc, content, template, context)))
    return path


def switch_template(
    store: ProjectStore, templates_root: Path, set_id: str, *, accept_gaps: bool = False
) -> SwitchResult:
    """Use `set_id` from now on; draft and in-review documents render again, in one commit."""
    report = project_coverage(store, templates_root, set_id)
    if report.gaps and not accept_gaps:
        raise CoverageGapError(report)
    config = get_config(store).model_copy(update={"company_id": set_id})
    paths: list[Path] = [write_config(store, config)]
    rendered: list[str] = []
    kept: list[str] = []
    for doc, content in latest_documents(store):
        if doc.status in ISSUED:
            kept.append(f"{doc.id} v{doc.version}")
            continue
        paths.append(_write(store, templates_root, set_id, doc, content))
        rendered.append(f"{doc.id} v{doc.version}")
    commit_paths(store.root, paths, f"project({store.project_id}): template {set_id}")
    return SwitchResult(set_id, report, tuple(rendered), tuple(kept))


def reissue(
    store: ProjectStore, templates_root: Path, doc_id: str, version: int | None = None
) -> Path:
    """Render an issued version again with the project's current set and commit it."""
    doc, content = get_document(store, doc_id, version)
    set_id = get_config(store).company_id
    path = _write(store, templates_root, set_id, doc, content)
    commit_paths(
        store.root,
        [path],
        f"render({store.project_id}): reissue {doc.id} v{doc.version} ({set_id})",
    )
    return path
