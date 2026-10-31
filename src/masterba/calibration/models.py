"""Models of the calibration flow (spec 09 sections 2 and 3); none is a stored document."""

from pydantic import Field

from masterba.models.base import FrozenModel
from masterba.models.enums import DocType

COLUMN = r"^[A-Z]{1,3}$"
CELL = r"^[A-Z]{1,3}[1-9][0-9]*$"


class ColumnMap(FrozenModel):
    col: str = Field(pattern=COLUMN)
    header: str = ""
    field: str | None = None
    value_map: str | None = None


class TableMap(FrozenModel):
    sheet: str = Field(min_length=1)
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,20}$")
    header_row: int = Field(ge=1)
    first_row: int = Field(ge=1)
    numbering: str | None = Field(default=None, pattern=COLUMN)
    columns: list[ColumnMap] = Field(min_length=1)
    where: dict[str, str] = Field(default_factory=dict)


class HeaderCell(FrozenModel):
    sheet: str = Field(min_length=1)
    cell: str = Field(pattern=CELL)
    source: str


class MappingDraft(FrozenModel):
    doc_type: DocType
    tables: list[TableMap] = Field(default_factory=list)
    headers: list[HeaderCell] = Field(default_factory=list)
    unmapped: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class SheetProfile(FrozenModel):
    name: str
    max_row: int
    max_col: int
    merged: list[str] = Field(default_factory=list)
    widths: dict[str, float] = Field(default_factory=dict)
    rows: list[list[str]] = Field(default_factory=list)
    header_row: int | None = None
    recognised: int = 0
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_table(self) -> bool:
        return self.header_row is not None and self.recognised >= 2


class WorkbookProfile(FrozenModel):
    sheets: list[SheetProfile]
    warnings: list[str] = Field(default_factory=list)
