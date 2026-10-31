"""Revision patches: change a document without regenerating it (spec 07 section 4).

`apply_patch` is a pure function; untouched items stay identical, ids are stable, and a removed
item's number is never reused.
"""

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import Field, ValidationError

from masterba.models import (
    PAYLOAD_BY_TYPE,
    BasicDesignItem,
    BrdItem,
    DetailDesignItem,
    Payload,
    PayloadItem,
    RequirementItem,
    SrsItem,
    TestCaseItem,
    payload_items,
)
from masterba.models.base import FrozenModel
from masterba.models.enums import DocType, ItemStatus, ReqCategory
from masterba.models.ids import ItemRef
from masterba.models.payloads import LEVEL_BY_TEST_TYPE
from masterba.rendering.bindings import item_class

IDENTITY_FIELDS = frozenset({"item_id", "status", "test_id", "level", "requirement_id"})
_ITEM_NUMBER = re.compile(r"#item\.(\d+)$")


class PatchOp(FrozenModel):
    op: Literal["update", "add", "remove"]
    item_id: ItemRef | None = None
    fields: dict[str, Any] = Field(default_factory=dict)
    reason: str = Field(min_length=1)


class RevisionPatch(FrozenModel):
    operations: list[PatchOp] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class PatchError(ValueError):
    """The patch cannot be applied; `errors` has one message per problem."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class PatchContext:
    doc_id: str
    doc_type: DocType
    dr_id: str
    active_nodes: frozenset[str]
    next_req_number: int


@dataclass(frozen=True)
class ChangedItem:
    item_id: str
    op: str
    reason: str
    before: PayloadItem | None
    after: PayloadItem | None


@dataclass(frozen=True)
class PatchResult:
    content: Payload
    changes: tuple[ChangedItem, ...]
    new_requirements: tuple[RequirementItem, ...]
    updated_requirements: tuple[RequirementItem, ...]


def item_number(item_id: str) -> int:
    found = _ITEM_NUMBER.search(item_id)
    return int(found[1]) if found else 0


def max_item_number(content: Payload) -> int:
    return max((item_number(i.item_id) for i in payload_items(content)), default=0)


def refs_of(item: PayloadItem) -> list[str]:
    """References an item makes to other nodes (only these are checked for existence)."""
    if isinstance(item, SrsItem):
        return [item.requirement_id, *item.derives_from]
    if isinstance(item, BasicDesignItem):
        return list(item.realizes)
    if isinstance(item, DetailDesignItem):
        return list(item.refines)
    if isinstance(item, TestCaseItem):
        return list(item.verifies)
    return []


def _next_test_number(items: list[PayloadItem]) -> int:
    numbers = [int(i.test_id.rsplit("-", 1)[1]) for i in items if isinstance(i, TestCaseItem)]
    return max(numbers, default=0) + 1


def apply_patch(
    content: Payload,
    patch: RevisionPatch,
    ctx: PatchContext,
    requirements: Mapping[str, RequirementItem],
) -> PatchResult:
    """Apply `patch` to `content`; raises `PatchError` listing every problem found."""
    cls = item_class(ctx.doc_type)
    allowed = set(cls.model_fields) - IDENTITY_FIELDS
    items: list[PayloadItem] = list(payload_items(content))
    index = {i.item_id: n for n, i in enumerate(items)}
    errors: list[str] = []
    changes: list[ChangedItem] = []
    new_reqs: list[RequirementItem] = []
    updated_reqs: dict[str, RequirementItem] = {}
    touched: set[str] = set()
    next_number = max_item_number(content) + 1
    next_req = ctx.next_req_number

    for n, op in enumerate(patch.operations, start=1):
        label = f"operation {n} ({op.op})"
        if op.op == "add":
            bad = sorted(set(op.fields) & {"item_id", "status", "test_id", "level"})
            if bad:
                errors.append(f"{label}: fields {bad} are assigned by the system")
                continue
            item_id = f"{ctx.doc_id}#item.{next_number}"
            data: dict[str, Any] = {k: v for k, v in op.fields.items() if k != "category"}
            data["item_id"] = item_id
            category = op.fields.get("category", ReqCategory.FUNCTIONAL.value)
            if ctx.doc_type is DocType.BRD:
                data["requirement_id"] = f"REQ-{next_req:04d}"
                data.setdefault("source_ref", ctx.dr_id)
            if ctx.doc_type in LEVEL_BY_TEST_TYPE:
                level = LEVEL_BY_TEST_TYPE[ctx.doc_type]
                data["level"] = level.value
                data["test_id"] = f"TC-{level.value}-{_next_test_number(items):04d}"
            try:
                created = cls.model_validate(data)
                if isinstance(created, BrdItem):
                    new_reqs.append(
                        RequirementItem(
                            id=created.requirement_id,
                            source_ref=created.source_ref,
                            text=created.description,
                            category=ReqCategory(category),
                        )
                    )
                    next_req += 1
            except (ValidationError, ValueError) as exc:
                errors.append(f"{label}: {exc}")
                continue
            items.append(created)
            index[item_id] = len(items) - 1
            next_number += 1
            changes.append(ChangedItem(item_id, "add", op.reason, None, created))
            touched.add(item_id)
            continue

        target = op.item_id
        if target is None or target not in index:
            errors.append(f"{label}: {target} is not an item of {ctx.doc_id}")
            continue
        if target in touched:
            errors.append(f"{label}: {target} is changed twice in one patch")
            continue
        before = items[index[target]]
        if before.status is not ItemStatus.ACTIVE:
            errors.append(f"{label}: {target} is not active")
            continue
        touched.add(target)
        if op.op == "remove":
            after = before.model_copy(update={"status": ItemStatus.REMOVED})
        else:
            unknown = sorted(set(op.fields) - allowed)
            if unknown or not op.fields:
                errors.append(
                    f"{label}: cannot change {unknown or 'nothing'}; allowed: {sorted(allowed)}"
                )
                continue
            try:
                after = cls.model_validate({**before.model_dump(mode="json"), **op.fields})
            except (ValidationError, ValueError) as exc:
                errors.append(f"{label}: {exc}")
                continue
        items[index[target]] = after
        changes.append(ChangedItem(target, op.op, op.reason, before, after))
        if isinstance(before, BrdItem) and isinstance(after, BrdItem):
            req = requirements.get(before.requirement_id)
            if req is not None:
                if op.op == "remove":
                    updated_reqs[req.id] = req.model_copy(update={"status": ItemStatus.REMOVED})
                elif after.description != before.description:
                    updated_reqs[req.id] = req.model_copy(update={"text": after.description})

    own = {c.item_id for c in changes if c.after is not None}
    for change in changes:
        final = change.after
        if final is None or final.status is not ItemStatus.ACTIVE:
            continue
        for ref in refs_of(final):
            if ref not in ctx.active_nodes and ref not in own:
                errors.append(f"{change.item_id}: reference {ref} is not an active node")
    if errors:
        raise PatchError(errors)
    new_content = content.model_copy(update={"items": items})
    assert isinstance(new_content, PAYLOAD_BY_TYPE[ctx.doc_type])
    return PatchResult(new_content, tuple(changes), tuple(new_reqs), tuple(updated_reqs.values()))


def validate_patch(
    content: Payload,
    patch: RevisionPatch,
    ctx: PatchContext,
    requirements: Mapping[str, RequirementItem],
) -> list[str]:
    """Deterministic gate: the problems that stop a patch from being applied (empty = fine)."""
    try:
        apply_patch(content, patch, ctx, requirements)
    except PatchError as exc:
        return exc.errors
    return []
