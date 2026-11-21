"""Baseline layout of the 8 default templates (spec 02 section 4, spec 19 section 3).

Single source for both the committed `.xlsx` shells and the `.template.json` bindings, so the
two cannot drift apart.
"""

from dataclasses import dataclass

from masterba.models.enums import DocType

NUMBER_COL = "A"
HEADER_ROW = 7
FIRST_ROW = 8
NOTE_ROW = 6

VALUE_MAPS: dict[str, dict[str, str]] = {
    "doc_status": {
        "draft": "作成中",
        "in_review": "レビュー中",
        "approved": "承認済",
        "superseded": "旧版",
    },
    "level": {"UT": "単体テスト", "IT": "結合テスト", "ST": "総合テスト", "UAT": "受入テスト"},
    "scope": {"in": "対象", "out": "対象外"},
}

# (label, header source, value map) printed at rows 2 to 5 of every sheet but the cover.
HEADER_BLOCK: tuple[tuple[str, str, str | None], ...] = (
    ("文書ID", "$document.id", None),
    ("版", "$document.version", None),
    ("プロジェクト", "$project.id", None),
    ("状態", "$document.status", "doc_status"),
)

# The cover (表紙): title cell, then label/value rows from COVER_FIRST_ROW in columns B and C.
COVER_TITLE_CELL = "B4"
COVER_FIRST_ROW = 8
COVER_ROWS: tuple[tuple[str, str, str | None], ...] = (
    ("プロジェクト", "$project.id", None),
    ("会社名", "$project.company", None),
    ("文書ID", "$document.id", None),
    ("版数", "$document.version", None),
    ("状態", "$document.status", "doc_status"),
    ("作成日", "$document.created_on", None),
    ("最終更新日", "$document.updated_on", None),
    ("作成者", "$document.author", None),
    ("承認者", "$document.approver", None),
    ("承認日", "$document.approved_on", None),
)
COVER_STAMPS = ("承認", "確認", "作成")
COVER_NOTE = (
    "本書は MasterBA が登録済みの要件・設計データから生成しています。"
    "版ごとの変更内容は改訂履歴を参照してください。"
)
JUDGEMENT_HEADER = "判定"
JUDGEMENT_CHOICES = ("OK", "NG", "保留", "対象外")

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
    source: str | None = None  # a `ListBinding` source; None means `content.items`
    is_cover: bool = False

    @property
    def is_placeholder(self) -> bool:
        return not self.columns and not self.is_cover


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
    Col("レベル", "level", 12, "level"),
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

_HISTORY_COLS = (
    Col("版", "version", 8),
    Col("改訂日", "date", 12),
    Col("改訂内容", "summary", 30),
    Col("改訂理由", "reason", 60),
    Col("作成者", "author", 14),
    Col("承認者", "approver", 14),
)
_TRACE_COLS = (
    Col("項目ID", "item", 24),
    Col("名称", "name", 48),
    Col("上流", "upstream", 28),
    Col("下流", "downstream", 28),
)
_EXCLUSION_COLS = (
    Col("対象項目", "item_ref", 28),
    Col("除外理由", "reason", 70),
)
TRACE_NOTE = "上流・下流はトレースリンクから自動作成しています。"

_ACTIVE = (("status", "active"),)

COVER = SheetSpec("cover", "表紙", is_cover=True)
HISTORY = SheetSpec("history", "改訂履歴", _HISTORY_COLS, source="$revisions")
TRACE = SheetSpec("trace", "トレーサビリティ", _TRACE_COLS, note=TRACE_NOTE, source="$trace")
EXCLUSIONS = SheetSpec("exclusions", "除外項目", _EXCLUSION_COLS, source="$exclusions")


def _doc(doc_type: DocType, *sheets: SheetSpec, tail: SheetSpec = TRACE) -> DocSpec:
    """Cover and revision history first, then the content sheets, then `tail`."""
    return DocSpec(doc_type, (COVER, HISTORY, *sheets, tail))


def _test_spec(doc_type: DocType) -> DocSpec:
    sheet = SheetSpec("cases", "テストケース", _TEST_COLS, _ACTIVE, EXECUTION_NOTE)
    return _doc(doc_type, sheet, tail=EXCLUSIONS)


CATALOG: tuple[DocSpec, ...] = (
    _doc(
        DocType.BRD,
        SheetSpec("background", "背景・目的", note=PENDING_NOTE),
        SheetSpec("requirements", "業務要件", _BRD_COLS, _ACTIVE),
        SheetSpec("scope", "システム化の範囲", _BRD_COLS, (*_ACTIVE, ("scope", "in"))),
        SheetSpec("out_of_scope", "対象外", _BRD_COLS, (*_ACTIVE, ("scope", "out"))),
        SheetSpec("constraints", "制約事項", note=PENDING_NOTE),
    ),
    _doc(
        DocType.SRS,
        SheetSpec("background", "背景・目的", note=PENDING_NOTE),
        SheetSpec("functional", "機能要件", _SRS_COLS, (*_ACTIVE, ("kind", "functional"))),
        SheetSpec("nonfunctional", "非機能要件", _SRS_COLS, (*_ACTIVE, ("kind", "non_functional"))),
        SheetSpec("constraints", "制約事項", note=PENDING_NOTE),
    ),
    _doc(
        DocType.BASIC_DESIGN,
        SheetSpec("functions", "機能一覧表", _BASIC_COLS, (*_ACTIVE, ("kind", "function"))),
        SheetSpec("screens", "画面一覧表", _BASIC_COLS, (*_ACTIVE, ("kind", "screen"))),
        SheetSpec("interfaces", "IF設計", _BASIC_COLS, (*_ACTIVE, ("kind", "interface"))),
        SheetSpec("tables", "テーブル定義書", _BASIC_COLS, (*_ACTIVE, ("kind", "data_entity"))),
        SheetSpec("diagrams", "構成図・フロー図・ER図", note=DIAGRAM_NOTE),
        SheetSpec("it_viewpoints", "結合テスト観点", note=PENDING_NOTE),
    ),
    _doc(
        DocType.DETAIL_DESIGN,
        SheetSpec("overview", "システム概要", note=PENDING_NOTE),
        SheetSpec("modules", "機能仕様", _DETAIL_COLS, (*_ACTIVE, ("kind", "module"))),
        SheetSpec("steps", "処理フロー", _DETAIL_COLS, (*_ACTIVE, ("kind", "processing_step"))),
        SheetSpec("db", "データベース設計", _DETAIL_COLS, (*_ACTIVE, ("kind", "db_table"))),
        SheetSpec("api", "インターフェース設計", _DETAIL_COLS, (*_ACTIVE, ("kind", "api"))),
    ),
    _test_spec(DocType.TEST_IT),
    _test_spec(DocType.TEST_ST),
    _test_spec(DocType.TEST_UT),
    _test_spec(DocType.TEST_UAT),
)
