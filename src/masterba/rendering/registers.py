"""変更管理台帳 and QA管理表: the change and Q&A registers of a project (spec 27 section 4).

Printed from the Decision Records and the question ledger, with no model and no write: the
data is already committed, so the registers are exported on demand and are byte-deterministic.
"""

from collections.abc import Sequence
from typing import Literal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from masterba.models import DecisionRecord, Question, payload_items
from masterba.models.enums import DrStatus, QuestionOrigin
from masterba.rendering.catalog import VALUE_MAPS
from masterba.rendering.codes import display_code
from masterba.rendering.context import DOC_TITLES
from masterba.rendering.engine import CREATOR, FIXED_TIME
from masterba.rendering.finish import finish_workbook, print_setup
from masterba.rendering.history import TRIGGER_LABELS
from masterba.rendering.xlsxio import workbook_bytes
from masterba.trace_store import (
    ProjectStore,
    get_dr_extra,
    latest_documents,
    list_decision_records,
    list_questions,
)

Register = Literal["changes", "questions"]
REGISTER_NAMES: dict[Register, str] = {"changes": "変更管理台帳", "questions": "QA管理表"}

FONT = "Meiryo"
_SIDE = Side(style="thin", color="999999")
_BORDER = Border(left=_SIDE, right=_SIDE, top=_SIDE, bottom=_SIDE)
_HEAD_FILL = PatternFill("solid", start_color="DDE6F0")
_LABEL_FILL = PatternFill("solid", start_color="F2F2F2")
HEADER_ROW = 4
FIRST_ROW = 5

DR_STATUS_LABELS: dict[DrStatus, str] = {
    DrStatus.PROPOSED: "起票",
    DrStatus.APPROVED: "承認",
    DrStatus.PROPAGATED: "反映済",
    DrStatus.CLOSED: "完了",
}
REJECTED = "却下"
ORIGIN_LABELS: dict[QuestionOrigin, str] = {
    QuestionOrigin.AGENT: "作成担当",
    QuestionOrigin.QA_BLOCKER: "QAレビュー指摘",
}
FORM_STAMPS = ("承認", "確認", "起票")
HAND_ENTRY = "（手入力）"

CHANGE_COLUMNS: tuple[tuple[str, int], ...] = (
    ("No.", 6),
    ("変更管理番号", 14),
    ("起票日", 12),
    ("変更区分", 16),
    ("件名", 50),
    ("状態", 10),
    ("承認者", 14),
    ("反映先文書", 40),
)
QUESTION_COLUMNS: tuple[tuple[str, int], ...] = (
    ("No.", 6),
    ("QA番号", 10),
    ("工程", 18),
    ("起票日", 12),
    ("起票元", 14),
    ("質問内容", 50),
    ("参照箇所", 28),
    ("回答", 40),
    ("回答者", 12),
    ("回答日", 12),
    ("状態", 10),
    ("関連変更管理番号", 16),
)


def _date(value: object) -> str | None:
    return value.strftime("%Y/%m/%d") if hasattr(value, "strftime") else None


def _status(store: ProjectStore, dr: DecisionRecord) -> str:
    """A closed DR without an impact analysis was rejected (spec 13 section 4)."""
    if dr.status is DrStatus.CLOSED and get_dr_extra(store, dr.id, "impact") is None:
        return REJECTED
    return DR_STATUS_LABELS[dr.status]


def _reflected(store: ProjectStore, dr: DecisionRecord) -> list[str]:
    """`DOC-... v2` per document the DR's propagation revised, else the affected documents."""
    progress = get_dr_extra(store, dr.id, "propagation") or {}
    documents = progress.get("documents", {})
    out: list[str] = []
    for doc_id in dr.affected_documents:
        entry = documents.get(doc_id) or {}
        version = entry.get("version") if entry.get("outcome") == "revised" else None
        out.append(f"{doc_id} v{version}" if version else doc_id)
    return out


def _codes(store: ProjectStore) -> dict[str, str]:
    codes: dict[str, str] = {}
    for _, content in latest_documents(store):
        for item in payload_items(content):
            codes[item.item_id] = display_code(item)
    return codes


def _impact(dr: DecisionRecord, codes: dict[str, str]) -> str:
    lines = []
    for ref in dr.impacted_items:
        code = codes.get(ref)
        lines.append(f"{code}（{ref}）" if code and code != ref else ref)
    return "\n".join(lines)


def _cell(ws: Worksheet, row: int, col: int, value: str | int | None, **font: object) -> None:
    cell = ws.cell(row=row, column=col)
    cell.value = value
    if isinstance(value, str):
        cell.data_type = "s"  # never a formula
    cell.font = Font(name=FONT, size=10, **font)  # type: ignore[arg-type]
    cell.border = _BORDER
    cell.alignment = Alignment(wrap_text=True, vertical="top")


def _title(ws: Worksheet, title: str, project_id: str) -> None:
    ws["A1"] = title
    ws["A1"].font = Font(name=FONT, size=14, bold=True)
    ws["A2"] = "プロジェクト"
    ws["A2"].font = Font(name=FONT, size=9, bold=True)
    ws["A2"].fill = _LABEL_FILL
    ws["A2"].border = _BORDER
    ws["A2"].alignment = Alignment(shrink_to_fit=True, vertical="center")  # column A is No.
    ws["B2"].value = project_id
    ws["B2"].data_type = "s"
    ws["B2"].font = Font(name=FONT, size=9)
    ws["B2"].border = _BORDER


def _table(
    ws: Worksheet,
    columns: tuple[tuple[str, int], ...],
    rows: Sequence[Sequence[str | int | None]],
) -> None:
    for index, (header, width) in enumerate(columns, start=1):
        ws.column_dimensions[get_column_letter(index)].width = width
        _cell(ws, HEADER_ROW, index, header, bold=True)
        ws.cell(row=HEADER_ROW, column=index).fill = _HEAD_FILL
    for offset, row in enumerate(rows):
        for index, value in enumerate(row, start=1):
            _cell(ws, FIRST_ROW + offset, index, value)
    ws.freeze_panes = f"A{FIRST_ROW}"
    ws.print_title_rows = f"{HEADER_ROW}:{HEADER_ROW}"


def _print_setup(ws: Worksheet) -> None:
    print_setup(ws)


def _form(ws: Worksheet, store: ProjectStore, dr: DecisionRecord, codes: dict[str, str]) -> None:
    """変更管理票: one DR as a label/value form with a stamp box."""
    _title(ws, "変更管理票", store.project_id)
    fields: tuple[tuple[str, str | None], ...] = (
        ("変更管理番号", dr.id),
        ("起票日", _date(dr.date)),
        ("変更区分", TRIGGER_LABELS[dr.trigger]),
        ("状態", _status(store, dr)),
        ("変更内容", dr.description),
        ("判断", dr.decision),
        ("理由", dr.rationale),
        ("影響範囲", _impact(dr, codes)),
        ("反映結果", "\n".join(_reflected(store, dr))),
        ("工数・納期への影響", HAND_ENTRY),
        ("承認者", dr.approver),
    )
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 80
    for offset, (label, value) in enumerate(fields):
        row = HEADER_ROW + offset
        _cell(ws, row, 1, label, bold=True)
        ws.cell(row=row, column=1).fill = _LABEL_FILL
        _cell(ws, row, 2, value)
    for index, stamp in enumerate(FORM_STAMPS, start=4):
        ws.column_dimensions[get_column_letter(index)].width = 10
        _cell(ws, HEADER_ROW, index, stamp, bold=True)
        ws.cell(row=HEADER_ROW, column=index).fill = _HEAD_FILL
        for row in range(HEADER_ROW + 1, HEADER_ROW + 4):
            _cell(ws, row, index, None)
    _print_setup(ws)


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else text


def changes_workbook(store: ProjectStore) -> Workbook:
    """変更管理台帳: the list of every DR, then one 変更管理票 sheet per DR."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = REGISTER_NAMES["changes"]
    _title(ws, REGISTER_NAMES["changes"], store.project_id)
    records = sorted(list_decision_records(store), key=lambda d: d.id)
    rows = [
        (
            n,
            dr.id,
            _date(dr.date),
            TRIGGER_LABELS[dr.trigger],
            _first_line(dr.description),
            _status(store, dr),
            dr.approver,
            "\n".join(_reflected(store, dr)) or None,
        )
        for n, dr in enumerate(records, start=1)
    ]
    _table(ws, CHANGE_COLUMNS, rows)
    _print_setup(ws)
    codes = _codes(store)
    for dr in records:
        _form(wb.create_sheet(dr.id), store, dr, codes)
    return _fixed(wb)


def _question_row(n: int, q: Question) -> tuple[str | int | None, ...]:
    return (
        n,
        q.id,
        DOC_TITLES[q.stage],
        _date(q.asked_on),
        ORIGIN_LABELS[q.origin],
        q.text,
        "\n".join(q.refs) or None,
        q.answer,
        q.answered_by,
        _date(q.answered_on),
        VALUE_MAPS["question_status"][q.status.value],
        q.dr_id,
    )


def questions_workbook(store: ProjectStore) -> Workbook:
    """QA管理表: every customer question of the ledger, by id."""
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.title = REGISTER_NAMES["questions"]
    _title(ws, REGISTER_NAMES["questions"], store.project_id)
    questions = sorted(list_questions(store), key=lambda q: q.id)
    _table(ws, QUESTION_COLUMNS, [_question_row(n, q) for n, q in enumerate(questions, start=1)])
    _print_setup(ws)
    return _fixed(wb)


def _fixed(wb: Workbook) -> Workbook:
    wb.properties.creator = CREATOR
    wb.properties.lastModifiedBy = CREATOR
    wb.properties.created = FIXED_TIME
    wb.properties.modified = FIXED_TIME
    return finish_workbook(wb)


def register_bytes(store: ProjectStore, register: Register) -> bytes:
    build = changes_workbook if register == "changes" else questions_workbook
    return workbook_bytes(build(store))


def register_filename(store: ProjectStore, register: Register) -> str:
    return f"{store.project_id}_{REGISTER_NAMES[register]}.xlsx"
