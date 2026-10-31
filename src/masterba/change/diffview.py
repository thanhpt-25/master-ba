"""Readable differences between document versions (spec 07 section 6)."""

from dataclasses import dataclass
from typing import Any

from masterba.diff import Classification, ItemChange, diff_documents
from masterba.trace_store import ProjectStore, get_document, get_dr_extra


@dataclass(frozen=True)
class DocumentDiff:
    doc_id: str
    old_version: int
    new_version: int
    changes: tuple[ItemChange, ...]


def diff_versions(store: ProjectStore, doc_id: str, old: int, new: int) -> DocumentDiff:
    _, before = get_document(store, doc_id, old)
    _, after = get_document(store, doc_id, new)
    return DocumentDiff(doc_id, old, new, tuple(diff_documents(before, after)))


def dr_diff(store: ProjectStore, dr_id: str, structural_only: bool = False) -> list[DocumentDiff]:
    """Diffs of every document the DR revised (`version - 1` against `version`)."""
    progress = get_dr_extra(store, dr_id, "propagation") or {"documents": {}}
    diffs: list[DocumentDiff] = []
    for doc_id, entry in progress["documents"].items():
        if entry["outcome"] != "revised":
            continue
        version = int(entry["version"])
        diff = diff_versions(store, doc_id, version - 1, version)
        if structural_only:
            kept = tuple(
                c for c in diff.changes if c.classification is not Classification.REWORDED_ONLY
            )
            diff = DocumentDiff(diff.doc_id, diff.old_version, diff.new_version, kept)
        diffs.append(diff)
    return diffs


def rows(diff: DocumentDiff) -> list[dict[str, Any]]:
    """The table `item id | field | old | new | classification` as plain dicts."""
    return [
        {
            "item_id": c.item_id,
            "change": c.change_type.value,
            "field": c.field,
            "old": c.old,
            "new": c.new,
            "classification": c.classification.value,
        }
        for c in diff.changes
    ]
