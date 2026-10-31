"""Structural diff and change classification."""

from masterba.diff.changes import (
    SIMILARITY_THRESHOLD,
    ChangeType,
    Classification,
    ItemChange,
    classify_change,
    diff_documents,
)

__all__ = [
    "SIMILARITY_THRESHOLD",
    "ChangeType",
    "Classification",
    "ItemChange",
    "classify_change",
    "diff_documents",
]
