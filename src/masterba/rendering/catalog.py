"""Baseline layout of the 8 default templates (spec 02 section 4).

Single source for both the committed `.xlsx` shells and the `.template.json` bindings, so the
two cannot drift apart.
"""

from dataclasses import dataclass

from masterba.models.enums import DocType

NUMBER_COL = "A"
HEADER_ROW = 7
FIRST_ROW = 8
NOTE_ROW = 6

VALUE_MAPS: dict[str, dict[str, str]] = {"scope": {"in": "対象", "out": "対象外"}}

HEADER_BLOCK: tuple[tuple[str, str], ...] = (
    ("文書ID", "$document.id"),
    ("版", "$document.version"),
    ("プロジェクト", "$project.id"),
    ("状態", "$document.status"),
)

EXECUTION_NOTE = "判定・実施日・実施者・不具合IDは手入力欄です（再出力すると消えます）。"
DIAGRAM_NOTE = "（図は別途添付）"
PENDING_NOTE = "（本版ではデータ未対応の項目です）"


@dataclass(frozen=True)
class Col:
    header: str
    field: str | None
    width: int
    value_map: str | None = None


@dataclass(frozen=True)
class SheetSpec:
    key: str
    name: str
    columns: tuple[Col, ...] = ()
    where: tuple[tuple[str, str], ...] = ()
    note: str | None = None

    @property
    def is_placeholder(self) -> bool:
        return not self.columns


@dataclass(frozen=True)
class DocSpec:
    doc_type: DocType
    sheets: tuple[SheetSpec, ...]


_ITEM_ID = Col("項目ID", "item_id", 24)
_REQ_ID = Col("要件ID", "requirement_id", 12)

_BRD_COLS = (
    _REQ_ID,
    _ITEM_ID,
    Col("タイトル", "title", 28),
    Col("内容", "description", 60),
    Col("範囲", "scope", 10, "scope"),
    Col("出典", "source_ref", 24),
)
_SRS_COLS = (
    _REQ_ID,
    _ITEM_ID,
    Col("要求記述", "statement", 60),
    Col("受入観点", "acceptance_hint", 36),
    Col("派生元", "derives_from", 16),
)
_BASIC_COLS = (
    _ITEM_ID,
    Col("名称", "name", 28),
    Col("説明", "description", 60),
    Col("実現対象", "realizes", 24),
)
_DETAIL_COLS = (
    _ITEM_ID,
    Col("名称", "name", 28),
    Col("仕様", "spec", 60),
    Col("詳細化対象", "refines", 24),
)
_TEST_COLS = (
    Col("テストケースID", "test_id", 16),
    _ITEM_ID,
    Col("レベル", "level", 8),
    Col("前提条件", "precondition", 30),
    Col("入力値", "input", 30),
    Col("操作手順", "steps", 40),
    Col("期待結果", "expected", 36),
    Col("紐付け対象", "verifies", 24),
    Col("判定", None, 8),
    Col("実施日", None, 12),
    Col("実施者", None, 12),
    Col("不具合ID", None, 14),
)

_ACTIVE = (("status", "active"),)


def _test_spec(doc_type: DocType) -> DocSpec:
    sheet = SheetSpec("cases", "テストケース", _TEST_COLS, _ACTIVE, EXECUTION_NOTE)
    return DocSpec(doc_type, (sheet,))


CATALOG: tuple[DocSpec, ...] = (
    DocSpec(
        DocType.BRD,
        (
            SheetSpec("background", "背景・目的", note=PENDING_NOTE),
            SheetSpec("requirements", "業務要件", _BRD_COLS, _ACTIVE),
            SheetSpec("scope", "システム化の範囲", _BRD_COLS, (*_ACTIVE, ("scope", "in"))),
            SheetSpec("out_of_scope", "対象外", _BRD_COLS, (*_ACTIVE, ("scope", "out"))),
            SheetSpec("constraints", "制約事項", note=PENDING_NOTE),
        ),
    ),
    DocSpec(
        DocType.SRS,
        (
            SheetSpec("background", "背景・目的", note=PENDING_NOTE),
            SheetSpec("functional", "機能要件", _SRS_COLS, (*_ACTIVE, ("kind", "functional"))),
            SheetSpec(
                "nonfunctional", "非機能要件", _SRS_COLS, (*_ACTIVE, ("kind", "non_functional"))
            ),
            SheetSpec("constraints", "制約事項", note=PENDING_NOTE),
        ),
    ),
    DocSpec(
        DocType.BASIC_DESIGN,
        (
            SheetSpec("functions", "機能一覧表", _BASIC_COLS, (*_ACTIVE, ("kind", "function"))),
            SheetSpec("screens", "画面一覧表", _BASIC_COLS, (*_ACTIVE, ("kind", "screen"))),
            SheetSpec("interfaces", "IF設計", _BASIC_COLS, (*_ACTIVE, ("kind", "interface"))),
            SheetSpec("tables", "テーブル定義書", _BASIC_COLS, (*_ACTIVE, ("kind", "data_entity"))),
            SheetSpec("diagrams", "構成図・フロー図・ER図", note=DIAGRAM_NOTE),
            SheetSpec("it_viewpoints", "結合テスト観点", note=PENDING_NOTE),
        ),
    ),
    DocSpec(
        DocType.DETAIL_DESIGN,
        (
            SheetSpec("overview", "システム概要", note=PENDING_NOTE),
            SheetSpec("modules", "機能仕様", _DETAIL_COLS, (*_ACTIVE, ("kind", "module"))),
            SheetSpec("steps", "処理フロー", _DETAIL_COLS, (*_ACTIVE, ("kind", "processing_step"))),
            SheetSpec("db", "データベース設計", _DETAIL_COLS, (*_ACTIVE, ("kind", "db_table"))),
            SheetSpec("api", "インターフェース設計", _DETAIL_COLS, (*_ACTIVE, ("kind", "api"))),
        ),
    ),
    _test_spec(DocType.TEST_IT),
    _test_spec(DocType.TEST_ST),
    _test_spec(DocType.TEST_UT),
    _test_spec(DocType.TEST_UAT),
)
