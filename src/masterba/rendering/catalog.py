"""Baseline layout of the 8 default templates (spec 02 section 4, spec 19 section 3, spec 26).

Single source for both the committed `.xlsx` shells and the `.template.json` bindings, so the
two cannot drift apart.
"""

from dataclasses import dataclass

from masterba.models.enums import DocType, SectionKey
from masterba.rendering.bindings import CODE_FIELD, VERIFIES_NAME_FIELD

NUMBER_COL = "A"
TITLE_CELL = "A1"
NOTE_ROW = 5
HEADER_ROW = 7
FIRST_ROW = 8
LAST_ROW = 2000  # last row the hand-entry lists and the progress formulas cover

VALUE_MAPS: dict[str, dict[str, str]] = {
    "doc_status": {
        "draft": "作成中",
        "in_review": "レビュー中",
        "approved": "承認済",
        "superseded": "旧版",
    },
    "level": {"UT": "単体テスト", "IT": "結合テスト", "ST": "総合テスト", "UAT": "受入テスト"},
    "scope": {"in": "対象", "out": "対象外"},
    "question_status": {"open": "未回答", "answered": "回答済", "withdrawn": "取下げ"},
}


@dataclass(frozen=True)
class BandCell:
    """One label/value pair of the header band (spec 26 section 1)."""

    row: int
    label_col: str
    value_col: str
    label: str
    source: str | None  # None: the value is the sheet's own name, written into the shell
    value_map: str | None = None


# The header band at rows 2 and 3 of every sheet but the cover.
HEADER_BAND: tuple[BandCell, ...] = (
    BandCell(2, "A", "B", "システム名", "$project.name"),
    BandCell(2, "C", "D", "文書名", "$document.title"),
    BandCell(2, "E", "F", "文書番号", "$document.id"),
    BandCell(2, "G", "H", "版数", "$document.version_label"),
    BandCell(3, "A", "B", "シート名", None),
    BandCell(3, "C", "D", "作成日", "$document.created_on"),
    BandCell(3, "E", "F", "更新日", "$document.updated_on"),
    BandCell(3, "G", "H", "状態", "$document.status", "doc_status"),
)
BAND_COLUMNS = "ABCDEFGH"
BAND_MIN_WIDTH = 14

# The cover (表紙): title cell, then label/value rows from COVER_FIRST_ROW in columns B and C.
COVER_TITLE_CELL = "B4"
COVER_SYSTEM_CELL = "B6"
COVER_FIRST_ROW = 8
COVER_ROWS: tuple[tuple[str, str, str | None], ...] = (
    ("システム名", "$project.name", None),
    ("顧客名", "$project.company", None),
    ("文書番号", "$document.id", None),
    ("版数", "$document.version_label", None),
    ("状態", "$document.status", "doc_status"),
    ("機密区分", "$document.classification", None),
    ("発行元", "$document.publisher", None),
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
    summary: str  # the 記載内容 of this sheet on 目次
    columns: tuple[Col, ...] = ()
    where: tuple[tuple[str, str], ...] = ()
    note: str | None = None
    source: str | None = None  # a `ListBinding` source; None means `content.items`
    is_cover: bool = False
    is_toc: bool = False
    is_progress: bool = False
    section: SectionKey | None = None  # a prose section of the payload (spec 19 part 2)

    @property
    def is_placeholder(self) -> bool:
        return not (
            self.columns or self.is_cover or self.is_toc or self.is_progress or self.section
        )


@dataclass(frozen=True)
class DocSpec:
    doc_type: DocType
    sheets: tuple[SheetSpec, ...]

    def sheet(self, key: str) -> SheetSpec:
        return next(s for s in self.sheets if s.key == key)


_MANAGED_ID = Col("管理ID", "item_id", 26)
_REMARKS = Col("備考", None, 16)
_REQ_ID = Col("要件ID", "requirement_id", 12)

_BRD_COLS = (
    _REQ_ID,
    Col("要件名", "title", 28),
    Col("要件内容", "description", 60),
    Col("対象区分", "scope", 10, "scope"),
    Col("出典", "source_ref", 24),
    _MANAGED_ID,
    _REMARKS,
)
_SRS_COLS = (
    _REQ_ID,
    Col("要求内容", "statement", 60),
    Col("受入基準", "acceptance_hint", 36),
    Col("派生元業務要件", "derives_from", 16),
    _MANAGED_ID,
    _REMARKS,
)


def _design_cols(code: str, body: str, field: str, upstream: str, refs: str) -> tuple[Col, ...]:
    return (
        Col(code, CODE_FIELD, 14),
        Col("名称", "name", 28),
        Col(body, field, 60),
        Col(upstream, refs, 26),
        _MANAGED_ID,
        _REMARKS,
    )


def _basic_cols(code: str) -> tuple[Col, ...]:
    return _design_cols(code, "概要", "description", "実現要件", "realizes")


def _detail_cols(code: str) -> tuple[Col, ...]:
    return _design_cols(code, "仕様", "spec", "詳細化元", "refines")


JUDGEMENT_HEADER = "判定"
_TEST_COLS = (
    Col("テスト項番", "test_id", 16),
    Col("大項目", VERIFIES_NAME_FIELD, 24),
    Col("前提条件", "precondition", 30),
    Col("テストデータ", "input", 30),
    Col("確認手順", "steps", 40),
    Col("期待結果", "expected", 36),
    Col("確認対象", "verifies", 24),
    Col("実施予定日", None, 12),
    Col("実施日", None, 12),
    Col("実施者", None, 12),
    Col(JUDGEMENT_HEADER, None, 8),
    Col("不具合No.", None, 12),
    _MANAGED_ID,
    _REMARKS,
)

_HISTORY_COLS = (
    Col("版数", "version_label", 8),
    Col("改訂日", "date", 12),
    Col("改訂箇所", "changed_sheets", 28),
    Col("改訂内容", "summary", 28),
    Col("改訂理由", "reason", 50),
    Col("作成者", "author", 12),
    Col("承認者", "approver", 12),
)
_TRACE_COLS = (
    Col("項目ID", "code", 16),
    Col("名称", "name", 48),
    Col("上流", "upstream", 28),
    Col("下流", "downstream", 28),
    Col("管理ID", "item", 26),
)
_EXCLUSION_COLS = (
    Col("対象項目", "item_ref", 28),
    Col("除外理由", "reason", 70),
)
_QUESTION_COLS = (
    Col("QA番号", "id", 10),
    Col("内容", "text", 60),
    Col("参照箇所", "refs", 30),
    Col("起票日", "asked_on", 12),
    Col("状態", "status", 10, "question_status"),
)
TRACE_NOTE = "上流・下流はトレースリンクから自動作成しています。"
QUESTIONS_NOTE = "顧客への確認が必要な事項です。回答は QA管理表 と変更管理台帳 に記録されます。"
EXECUTION_NOTE = (
    "実施予定日・実施日・実施者・判定・不具合No.・備考は手入力欄です（再出力すると消えます）。"
)
DIAGRAM_NOTE = "（図は別途添付）"
SCREEN_FLOW_NOTE = "（画面遷移図は別途添付）"

# 消化状況: one row per judgement, counted by fixed formulas over the 判定 column.
JUDGEMENT_CHOICES = ("OK", "NG", "保留", "対象外")
NOT_RUN = "未実施"
TOTAL = "合計"
PROGRESS_HEADERS = ("No.", JUDGEMENT_HEADER, "件数", "比率")

SECTION_EMPTY = "（入力資料に記載がないため、本版では記載していません。）"
SECTION_BODY_HEADER = "記載内容"
SECTION_SOURCES_HEADER = "出典"
SECTION_BODY_CELL = "A8"
SECTION_SOURCES_HEADER_ROW = 10
SECTION_SOURCES_CELL = "A11"

_ACTIVE = (("status", "active"),)

COVER = SheetSpec("cover", "表紙", "文書名、版数、承認欄", is_cover=True)
HISTORY = SheetSpec(
    "history", "改訂履歴", "版ごとの改訂日、改訂箇所、改訂内容、改訂理由", _HISTORY_COLS,
    source="$revisions",
)  # fmt: skip
TOC = SheetSpec("toc", "目次", "本書の構成", is_toc=True)
TRACE = SheetSpec(
    "trace", "トレーサビリティ", "各項目の上流・下流のトレースリンク", _TRACE_COLS,
    note=TRACE_NOTE, source="$trace",
)  # fmt: skip
EXCLUSIONS = SheetSpec(
    "exclusions", "除外項目", "テスト対象外とした項目と理由", _EXCLUSION_COLS,
    source="$exclusions",
)  # fmt: skip
OPEN_QUESTIONS = SheetSpec(
    "open_questions", "未決事項", "顧客に確認中の事項", _QUESTION_COLS,
    note=QUESTIONS_NOTE, source="$questions",
)  # fmt: skip


def _doc(doc_type: DocType, *sheets: SheetSpec, tail: SheetSpec = TRACE) -> DocSpec:
    """Cover, revision history and contents first, then the content sheets, then `tail`."""
    return DocSpec(doc_type, (COVER, HISTORY, TOC, *sheets, tail))


def _where(**fields: str) -> tuple[tuple[str, str], ...]:
    return (*_ACTIVE, *fields.items())


def _test_spec(doc_type: DocType) -> DocSpec:
    cases = SheetSpec(
        "cases", "テスト項目表", "テストケースと実施結果の記入欄", _TEST_COLS, _ACTIVE,
        EXECUTION_NOTE,
    )  # fmt: skip
    progress = SheetSpec("progress", "消化状況", "判定別の件数と比率（自動集計）", is_progress=True)
    return _doc(doc_type, cases, progress, tail=EXCLUSIONS)


CATALOG: tuple[DocSpec, ...] = (
    _doc(
        DocType.BRD,
        SheetSpec(
            "background", "背景・目的", "業務の背景と本件の目的", section=SectionKey.BACKGROUND
        ),
        SheetSpec("requirements", "業務要件一覧", "業務要件の一覧", _BRD_COLS, _ACTIVE),
        SheetSpec(
            "scope",
            "システム化の範囲",
            "システム化の対象とする業務要件",
            _BRD_COLS,
            _where(scope="in"),
        ),
        SheetSpec(
            "out_of_scope",
            "対象外業務",
            "システム化の対象外とする業務要件",
            _BRD_COLS,
            _where(scope="out"),
        ),
        SheetSpec(
            "constraints",
            "前提条件・制約事項",
            "前提条件と制約事項",
            section=SectionKey.CONSTRAINTS,
        ),
        OPEN_QUESTIONS,
    ),
    _doc(
        DocType.SRS,
        SheetSpec(
            "background", "背景・目的", "システム化の背景と目的", section=SectionKey.BACKGROUND
        ),
        SheetSpec(
            "functional", "機能要件一覧", "機能要件の一覧", _SRS_COLS, _where(kind="functional")
        ),
        SheetSpec(
            "nonfunctional",
            "非機能要件一覧",
            "非機能要件の一覧",
            _SRS_COLS,
            _where(kind="non_functional"),
        ),
        SheetSpec(
            "constraints",
            "前提条件・制約事項",
            "前提条件と制約事項",
            section=SectionKey.CONSTRAINTS,
        ),
        OPEN_QUESTIONS,
    ),
    _doc(
        DocType.BASIC_DESIGN,
        SheetSpec(
            "functions", "機能一覧", "機能の一覧", _basic_cols("機能ID"), _where(kind="function")
        ),
        SheetSpec(
            "screens", "画面一覧", "画面の一覧", _basic_cols("画面ID"), _where(kind="screen")
        ),
        SheetSpec("screen_flow", "画面遷移図", "画面間の遷移", note=SCREEN_FLOW_NOTE),
        SheetSpec(
            "interfaces",
            "インタフェース一覧",
            "外部・内部インタフェースの一覧",
            _basic_cols("IF ID"),
            _where(kind="interface"),
        ),
        SheetSpec(
            "tables",
            "エンティティ一覧",
            "業務データ（エンティティ）の一覧",
            _basic_cols("エンティティID"),
            _where(kind="data_entity"),
        ),
        SheetSpec(
            "diagrams",
            "システム構成図・業務フロー",
            "システム構成図、業務フロー図、ER図",
            note=DIAGRAM_NOTE,
        ),
        SheetSpec(
            "it_viewpoints",
            "結合テスト観点",
            "結合テストで確認する観点",
            section=SectionKey.IT_VIEWPOINTS,
        ),
    ),
    _doc(
        DocType.DETAIL_DESIGN,
        SheetSpec(
            "overview", "概要", "システム概要と詳細設計の方針", section=SectionKey.SYSTEM_OVERVIEW
        ),
        SheetSpec(
            "modules",
            "モジュール一覧",
            "モジュールの一覧と仕様",
            _detail_cols("モジュールID"),
            _where(kind="module"),
        ),
        SheetSpec(
            "steps",
            "処理一覧",
            "処理と処理フロー",
            _detail_cols("処理ID"),
            _where(kind="processing_step"),
        ),
        SheetSpec(
            "db",
            "テーブル定義",
            "テーブルの定義",
            _detail_cols("テーブルID"),
            _where(kind="db_table"),
        ),
        SheetSpec(
            "api",
            "API定義",
            "API・インタフェースの定義",
            _detail_cols("API ID"),
            _where(kind="api"),
        ),
    ),
    _test_spec(DocType.TEST_IT),
    _test_spec(DocType.TEST_ST),
    _test_spec(DocType.TEST_UT),
    _test_spec(DocType.TEST_UAT),
)


def doc_spec(doc_type: DocType) -> DocSpec:
    return next(s for s in CATALOG if s.doc_type is doc_type)
