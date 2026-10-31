"""Structural diff between two versions of a payload (no LLM involved)."""

import difflib
import re
from enum import StrEnum

from deepdiff import DeepDiff
from pydantic import JsonValue

from masterba.models import Payload, payload_items
from masterba.models.base import FrozenModel
from masterba.models.ids import ItemRef

SIMILARITY_THRESHOLD = 0.85
LONG_TEXT_MIN_LEN = 20
_NUMBER = re.compile(r"\d+(?:[.,]\d+)*")


class ChangeType(StrEnum):
    ADDED = "added"
    REMOVED = "removed"
    FIELD_CHANGED = "field_changed"


class Classification(StrEnum):
    REWORDED_ONLY = "reworded_only"
    STRUCTURAL_CHANGE = "structural_change"


class ItemChange(FrozenModel):
    item_id: ItemRef
    field: str | None = None
    old: JsonValue = None
    new: JsonValue = None
    change_type: ChangeType
    classification: Classification


def _normalise(text: str) -> str:
    return " ".join(text.lower().split())


def classify_change(
    old: JsonValue, new: JsonValue, threshold: float = SIMILARITY_THRESHOLD
) -> Classification:
    """Decide whether a changed value is a mere rewording.

    Only long text qualifies. Changed numbers always count as structural
    because a small edit such as 100 -> 1000 keeps the text almost identical.
    """
    if not (isinstance(old, str) and isinstance(new, str)):
        return Classification.STRUCTURAL_CHANGE
    if min(len(old), len(new)) < LONG_TEXT_MIN_LEN:
        return Classification.STRUCTURAL_CHANGE
    if _NUMBER.findall(old) != _NUMBER.findall(new):
        return Classification.STRUCTURAL_CHANGE
    ratio = difflib.SequenceMatcher(None, _normalise(old), _normalise(new)).ratio()
    if ratio >= threshold:
        return Classification.REWORDED_ONLY
    return Classification.STRUCTURAL_CHANGE


def diff_documents(old: Payload, new: Payload) -> list[ItemChange]:
    old_items = {i.item_id: i.model_dump(mode="json") for i in payload_items(old)}
    new_items = {i.item_id: i.model_dump(mode="json") for i in payload_items(new)}
    changes: list[ItemChange] = []
    for item_id in sorted(new_items.keys() - old_items.keys()):
        changes.append(
            ItemChange(
                item_id=item_id,
                change_type=ChangeType.ADDED,
                classification=Classification.STRUCTURAL_CHANGE,
            )
        )
    for item_id in sorted(old_items.keys() - new_items.keys()):
        changes.append(
            ItemChange(
                item_id=item_id,
                change_type=ChangeType.REMOVED,
                classification=Classification.STRUCTURAL_CHANGE,
            )
        )
    for item_id in sorted(old_items.keys() & new_items.keys()):
        delta = DeepDiff(old_items[item_id], new_items[item_id])
        for field in sorted(delta.affected_root_keys):
            before = old_items[item_id].get(field)
            after = new_items[item_id].get(field)
            changes.append(
                ItemChange(
                    item_id=item_id,
                    field=field,
                    old=before,
                    new=after,
                    change_type=ChangeType.FIELD_CHANGED,
                    classification=classify_change(before, after),
                )
            )
    return changes
