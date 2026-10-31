"""Typed form of `TemplateDefinition.cell_bindings` / `validation_rules` (spec 02 section 2).

`TemplateDefinition` keeps plain dicts (spec 01); these models are parsed from them when a
template is loaded, so a malformed template fails there and not in the middle of a render.
"""

from collections.abc import Callable
from typing import Annotated, Literal, cast, get_args

from pydantic import Field, TypeAdapter, field_validator

from masterba.models import PAYLOAD_BY_TYPE, Document, PayloadItem
from masterba.models.base import FrozenModel
from masterba.models.enums import DocType
from masterba.rendering.errors import InvalidTemplateError

EXCEL_MAX_CELL_LENGTH = 32767

HEADER_SOURCES: dict[str, Callable[[Document], str | int]] = {
    "$document.id": lambda d: d.id,
    "$document.type": lambda d: d.type.value,
    "$document.version": lambda d: d.version,
    "$document.status": lambda d: d.status.value,
    "$document.template_id": lambda d: d.template_id,
    "$project.id": lambda d: d.project_id,
}

_CELL = r"^[A-Z]{1,3}[1-9][0-9]*$"
_COLUMN = r"^[A-Z]{1,3}$"


class HeaderBinding(FrozenModel):
    sheet: str = Field(min_length=1)
    cell: str = Field(pattern=_CELL)
    source: str

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


class Bindings(FrozenModel):
    header: list[HeaderBinding] = Field(default_factory=list)
    tables: list[TableBinding] = Field(default_factory=list)
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
    for table in bindings.tables:
        if table.sheet not in sheet_map:
            problems.append(f"table sheet {table.sheet!r} is not in sheet_map")
        for key in table.where:
            if key not in fields:
                problems.append(f"where field {key!r} is not a {doc_type.value} item field")
        used = [c.col for c in table.columns]
        if table.numbering is not None:
            used.append(table.numbering.column)
        if len(used) != len(set(used)):
            problems.append(f"table {table.sheet!r} binds one column twice")
        for column in table.columns:
            if column.field is not None and column.field not in fields:
                problems.append(f"field {column.field!r} is not a {doc_type.value} item field")
            if column.value_map is not None and column.value_map not in bindings.value_maps:
                problems.append(f"value_map {column.value_map!r} is not defined")
    if problems:
        raise InvalidTemplateError("; ".join(problems))
