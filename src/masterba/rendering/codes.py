"""Display codes of items (spec 27 section 2), derived only from the item ref and kind."""

from enum import Enum

from masterba.models import PayloadItem
from masterba.models.payloads import BrdItem, SrsItem, TestCaseItem

CODE_PREFIXES: dict[str, str] = {
    "function": "FN",
    "screen": "SCR",
    "interface": "IF",
    "data_entity": "TBL",
    "module": "MOD",
    "processing_step": "PRC",
    "db_table": "DBT",
    "api": "API",
}


def item_number(item_ref: str) -> int:
    """`DOC-BASIC_DESIGN-0001#item.12` is 12."""
    return int(item_ref.rsplit(".", 1)[1])


def display_code(item: PayloadItem) -> str:
    """REQ id, test case id, or `<prefix>-<item number>` for a design item."""
    if isinstance(item, BrdItem | SrsItem):
        return item.requirement_id
    if isinstance(item, TestCaseItem):
        return item.test_id
    kind = getattr(item, "kind", None)
    prefix = CODE_PREFIXES.get(kind.value if isinstance(kind, Enum) else str(kind))
    return f"{prefix}-{item_number(item.item_id):04d}" if prefix else item.item_id
