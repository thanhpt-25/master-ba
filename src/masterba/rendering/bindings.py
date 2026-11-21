"""Typed form of `TemplateDefinition.cell_bindings` / `validation_rules` (spec 02 section 2).

`TemplateDefinition` keeps plain dicts (spec 01); these models are parsed from them when a
template is loaded, so a malformed template fails there and not in the middle of a render.
"""

from collections.abc import Callable
from typing import Annotated, Literal, cast, get_args

from pydantic import Field, TypeAdapter, field_validator

from masterba.models import PAYLOAD_BY_TYPE, Document, PayloadItem, TestSpecContent
from masterba.models.base import FrozenModel
from masterba.models.enums import DocType
from masterba.models.payloads import TestExclusion
from masterba.rendering.context import (
    DOC_TITLES,
    REVISION_FIELDS,
    TRACE_FIELDS,
    RenderContext,
)
from masterba.rendering.errors import InvalidTemplateError

EXCEL_MAX_CELL_LENGTH = 32767


def _this_revision(d: Document, c: RenderContext, attr: str) -> str | None:
    revision = c.revision(d.version)
    return getattr(revision, attr) if revision else None


HEADER_SOURCES: dict[str, Callable[[Document, RenderContext], str | int | None]] = {
    "$document.id": lambda d, c: d.id,
    "$document.type": lambda d, c: d.type.value,
    "$document.title": lambda d, c: DOC_TITLES[d.type],
    "$document.version": lambda d, c: d.version,
    "$document.status": lambda d, c: d.status.value,
    "$document.template_id": lambda d, c: d.template_id,
    "$document.author": lambda d, c: c.author or None,
    "$document.created_on": lambda d, c: c.created_on,
    "$document.updated_on": lambda d, c: _this_revision(d, c, "date"),
    "$document.approver": lambda d, c: _this_revision(d, c, "approver"),
    "$document.approved_on": lambda d, c: _this_revision(d, c, "approved_on"),
    "$project.id": lambda d, c: d.project_id,
    "$project.company": lambda d, c: c.company,
}

ListSource = Literal["$revisions", "$trace", "$exclusions"]
LIST_FIELDS: dict[str, frozenset[str]] = {
    "$revisions": REVISION_FIELDS,
    "$trace": TRACE_FIELDS,
    "$exclusions": frozenset(TestExclusion.model_fields),
}

_CELL = r"^[A-Z]{1,3}[1-9][0-9]*$"
_COLUMN = r"^[A-Z]{1,3}$"


class HeaderBinding(FrozenModel):
    sheet: str = Field(min_length=1)
    cell: str = Field(pattern=_CELL)
    source: str
    value_map: str | None = None

    @field_validator("source")
    @classmethod
    def _known_source(cls, value: str) -> str:
        if value not in HEADER_SOURCES:
            raise ValueError(f"unknown header source {value}; allowed: {sorted(HEADER_SOURCES)}")
        return value


class NumberingBinding(FrozenModel):
    column: str = Field(pattern=_COLUMN)


class ColumnBinding(FrozenModel):
    col: str = Field(pattern=_COLUMN)
    field: str | None = None
    value_map: str | None = None


class TableBinding(FrozenModel):
    sheet: str = Field(min_length=1)
    start_row: int = Field(ge=1)
    items: Literal["$content.items"] = "$content.items"
    where: dict[str, str] = Field(default_factory=dict)
    numbering: NumberingBinding | None = None
    columns: list[ColumnBinding] = Field(min_length=1)


class ListBinding(FrozenModel):
    """A table filled from the render context or the exclusions, not from `content.items`."""

    sheet: str = Field(min_length=1)
    start_row: int = Field(ge=1)
    source: ListSource
    numbering: NumberingBinding | None = None
    columns: list[ColumnBinding] = Field(min_length=1)


class Bindings(FrozenModel):
    header: list[HeaderBinding] = Field(default_factory=list)
    tables: list[TableBinding] = Field(default_factory=list)
    lists: list[ListBinding] = Field(default_factory=list)
    value_maps: dict[str, dict[str, str]] = Field(default_factory=dict)


class MaxCellLength(FrozenModel):
    rule: Literal["max_cell_length"]
    limit: int = Field(ge=1, le=EXCEL_MAX_CELL_LENGTH)


class NonEmptyTable(FrozenModel):
    rule: Literal["non_empty_table"]
    table: str = Field(min_length=1)


Rule = Annotated[MaxCellLength | NonEmptyTable, Field(discriminator="rule")]
RULES_ADAPTER: TypeAdapter[list[Rule]] = TypeAdapter(list[Rule])


def item_class(doc_type: DocType) -> type[PayloadItem]:
    annotation = PAYLOAD_BY_TYPE[doc_type].model_fields["items"].annotation
    (cls,) = get_args(annotation)
    return cast(type[PayloadItem], cls)


def validate_bindings(bindings: Bindings, doc_type: DocType, sheet_map: dict[str, str]) -> None:
    """Fail with `InvalidTemplateError` unless every reference resolves."""
    fields = item_class(doc_type).model_fields
    problems: list[str] = []
    for head in bindings.header:
        if head.sheet not in sheet_map:
            problems.append(f"header sheet {head.sheet!r} is not in sheet_map")
        if head.value_map is not None and head.value_map not in bindings.value_maps:
            problems.append(f"value_map {head.value_map!r} is not defined")
    for table in bindings.tables:
        for key in table.where:
            if key not in fields:
                problems.append(f"where field {key!r} is not a {doc_type.value} item field")
        problems += _check_columns(table, bindings, set(fields), f"a {doc_type.value} item field")
    for listed in bindings.lists:
        if listed.source == "$exclusions" and PAYLOAD_BY_TYPE[doc_type] is not TestSpecContent:
            problems.append(f"{doc_type.value} has no exclusions")
        known = set(LIST_FIELDS[listed.source])
        problems += _check_columns(listed, bindings, known, f"a {listed.source} field")
    sheets = {t.sheet for t in bindings.tables} | {t.sheet for t in bindings.lists}
    for name in sorted(sheets - set(sheet_map)):
        problems.append(f"table sheet {name!r} is not in sheet_map")
    if problems:
        raise InvalidTemplateError("; ".join(problems))


def _check_columns(
    table: TableBinding | ListBinding, bindings: Bindings, known: set[str], what: str
) -> list[str]:
    problems: list[str] = []
    used = [c.col for c in table.columns]
    if table.numbering is not None:
        used.append(table.numbering.column)
    if len(used) != len(set(used)):
        problems.append(f"table {table.sheet!r} binds one column twice")
    for column in table.columns:
        if column.field is not None and column.field not in known:
            problems.append(f"field {column.field!r} is not {what}")
        if column.value_map is not None and column.value_map not in bindings.value_maps:
            problems.append(f"value_map {column.value_map!r} is not defined")
    return problems
