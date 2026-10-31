from dataclasses import replace
from io import BytesIO
from pathlib import Path

import pytest
from openpyxl import Workbook, load_workbook
from openpyxl.worksheet.worksheet import Worksheet

from factories import (
    doc_id,
    make_basic,
    make_basic_item,
    make_brd,
    make_brd_item,
    make_document,
    make_srs,
    make_srs_item,
    make_test_item,
    make_test_spec,
)
from masterba.models import DetailDesignContent, DetailDesignItem, Payload
from masterba.models.enums import (
    DetailDesignKind,
    DocType,
    ItemStatus,
    Level,
    Scope,
    SrsKind,
)
from masterba.rendering import (
    InvalidTemplateError,
    RenderValidationError,
    ResolvedTemplate,
    render_document,
    resolve_template,
    workbook_bytes,
)
from masterba.rendering.bindings import MaxCellLength, NonEmptyTable

TEMPLATES = Path(__file__).parents[2] / "templates"
BRD = doc_id(DocType.BRD)
SRS = doc_id(DocType.SRS)
BASIC = doc_id(DocType.BASIC_DESIGN)
DETAIL = doc_id(DocType.DETAIL_DESIGN)
LONG_DESCRIPTION = "The system lets registered users sign in with email."


def template_for(doc_type: DocType) -> ResolvedTemplate:
    return resolve_template(TEMPLATES, "default", doc_type)


def render(doc_type: DocType, content: Payload) -> Workbook:
    return render_document(make_document(doc_type), content, template_for(doc_type))


def table_rows(ws: Worksheet, width: int) -> list[tuple[object, ...]]:
    rows = ws.iter_rows(min_row=8, max_col=width, values_only=True)
    return [row for row in rows if any(v is not None for v in row)]


def detail_content() -> DetailDesignContent:
    def item(i: int, kind: DetailDesignKind, name: str) -> DetailDesignItem:
        return DetailDesignItem(
            item_id=f"{DETAIL}#item.{i}",
            kind=kind,
            name=name,
            spec=f"{name} spec",
            refines=[f"{BASIC}#item.1"] if i == 1 else [],
        )

    return DetailDesignContent(
        items=[
            item(1, DetailDesignKind.MODULE, "AuthService"),
            item(2, DetailDesignKind.PROCESSING_STEP, "Validate password"),
            item(3, DetailDesignKind.DB_TABLE, "users"),
            item(4, DetailDesignKind.API, "POST /login"),
        ]
    )


def test_brd_golden_values_header_and_scope_split() -> None:
    out_item = make_brd_item(BRD, 2, req="REQ-0002").model_copy(update={"scope": Scope.OUT})
    wb = render(DocType.BRD, make_brd(make_brd_item(BRD, 1), out_item))
    assert wb.sheetnames == ["背景・目的", "業務要件", "システム化の範囲", "対象外", "制約事項"]
    ws = wb["業務要件"]
    assert [ws[f"B{r}"].value for r in range(2, 6)] == [BRD, 1, "PRJ-001", "draft"]
    assert table_rows(ws, 7) == [
        (
            1,
            "REQ-0001",
            f"{BRD}#item.1",
            "Requirement 1",
            LONG_DESCRIPTION,
            "対象",
            "intake/mail-1.txt",
        ),
        (
            2,
            "REQ-0002",
            f"{BRD}#item.2",
            "Requirement 2",
            LONG_DESCRIPTION,
            "対象外",
            "intake/mail-1.txt",
        ),
    ]
    assert [r[2] for r in table_rows(wb["システム化の範囲"], 7)] == [f"{BRD}#item.1"]
    assert [r[2] for r in table_rows(wb["対象外"], 7)] == [f"{BRD}#item.2"]


def test_srs_functional_and_non_functional_sheets() -> None:
    nfr = make_srs_item(SRS, 2, req="REQ-0002").model_copy(update={"kind": SrsKind.NON_FUNCTIONAL})
    wb = render(DocType.SRS, make_srs(make_srs_item(SRS, 1), nfr))
    statement = "The system shall authenticate users by email and password."
    assert table_rows(wb["機能要件"], 6) == [
        (1, "REQ-0001", f"{SRS}#item.1", statement, None, "REQ-0001")
    ]
    assert [r[2] for r in table_rows(wb["非機能要件"], 6)] == [f"{SRS}#item.2"]


def test_basic_design_screen_sheet_and_empty_sheets() -> None:
    wb = render(DocType.BASIC_DESIGN, make_basic(make_basic_item(BASIC, 1)))
    description = "Email and password form with a submit button."
    assert table_rows(wb["画面一覧表"], 5) == [
        (1, f"{BASIC}#item.1", "Login screen", description, None)
    ]
    assert table_rows(wb["機能一覧表"], 5) == []
    assert wb["構成図・フロー図・ER図"]["A7"].value == "（図は別途添付）"


def test_detail_design_fills_one_sheet_per_kind() -> None:
    wb = render(DocType.DETAIL_DESIGN, detail_content())
    assert table_rows(wb["機能仕様"], 5) == [
        (1, f"{DETAIL}#item.1", "AuthService", "AuthService spec", f"{BASIC}#item.1")
    ]
    for sheet, name in [("処理フロー", "Validate password"), ("データベース設計", "users")]:
        assert [r[2] for r in table_rows(wb[sheet], 5)] == [name]
    assert [r[2] for r in table_rows(wb["インターフェース設計"], 5)] == ["POST /login"]


@pytest.mark.parametrize(
    ("doc_type", "level"),
    [
        (DocType.TEST_IT, Level.IT),
        (DocType.TEST_ST, Level.ST),
        (DocType.TEST_UT, Level.UT),
        (DocType.TEST_UAT, Level.UAT),
    ],
)
def test_every_test_level_renders_the_same_columns(doc_type: DocType, level: Level) -> None:
    did = doc_id(doc_type)
    case = make_test_item(did, 1, f"TC-{level.value}-0001", level)
    wb = render(doc_type, make_test_spec(case))
    assert table_rows(wb["テストケース"], 13) == [
        (
            1,
            f"TC-{level.value}-0001",
            f"{did}#item.1",
            level.value,
            "A registered user exists.",
            "valid email and password",
            "1. Open the login screen\n2. Submit the form",
            "The user lands on the dashboard.",
            None,
            None,
            None,
            None,
            None,
        )
    ]


def test_removed_items_are_hidden_unless_the_template_drops_the_filter() -> None:
    content = make_brd(make_brd_item(BRD, 1), make_brd_item(BRD, 2, status=ItemStatus.REMOVED))
    assert len(table_rows(render(DocType.BRD, content)["業務要件"], 7)) == 1
    template = template_for(DocType.BRD)
    open_bindings = template.bindings.model_copy(
        update={"tables": [t.model_copy(update={"where": {}}) for t in template.bindings.tables]}
    )
    shown = render_document(
        make_document(DocType.BRD), content, replace(template, bindings=open_bindings)
    )
    assert len(table_rows(shown["業務要件"], 7)) == 2


def test_text_that_looks_like_a_formula_stays_text_after_saving() -> None:
    formula = '=HYPERLINK("http://example.invalid","click")'
    content = make_brd(make_brd_item(BRD, 1, description=formula))
    reloaded = load_workbook(BytesIO(workbook_bytes(render(DocType.BRD, content))))
    cell = reloaded["業務要件"]["E8"]
    assert (cell.value, cell.data_type) == (formula, "s")


def test_data_rows_copy_the_shell_style() -> None:
    content = make_brd(make_brd_item(BRD, 1), make_brd_item(BRD, 2), make_brd_item(BRD, 3))
    ws = render(DocType.BRD, content)["業務要件"]
    for row in (8, 9, 10):
        assert ws[f"E{row}"].alignment.wrap_text is True
        assert ws[f"E{row}"].border.left.style == "thin"


def test_same_content_gives_byte_identical_files() -> None:
    content = make_brd(make_brd_item(BRD, 1))
    first = workbook_bytes(render(DocType.BRD, content))
    second = workbook_bytes(render(DocType.BRD, content))
    assert first == second


def test_max_cell_length_rule_rejects_oversized_text() -> None:
    template = replace(
        template_for(DocType.BRD), rules=(MaxCellLength(rule="max_cell_length", limit=10),)
    )
    with pytest.raises(RenderValidationError, match="limit is 10"):
        render_document(make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)), template)


def test_non_empty_table_rule_rejects_empty_sheet() -> None:
    rule = NonEmptyTable(rule="non_empty_table", table="requirements")
    template = replace(template_for(DocType.BRD), rules=(rule,))
    with pytest.raises(RenderValidationError, match="no rows"):
        render_document(make_document(DocType.BRD), make_brd(), template)


def test_character_excel_cannot_store_is_a_validation_error() -> None:
    content = make_brd(make_brd_item(BRD, 1, description="bad \x00 text"))
    with pytest.raises(RenderValidationError, match="cannot store"):
        render(DocType.BRD, content)


def test_template_for_another_document_type_is_rejected() -> None:
    with pytest.raises(InvalidTemplateError, match="not"):
        render_document(make_document(DocType.SRS), make_srs(), template_for(DocType.BRD))


def test_payload_of_another_type_is_rejected() -> None:
    with pytest.raises(RenderValidationError, match="does not fit"):
        render_document(make_document(DocType.BRD), make_srs(), template_for(DocType.BRD))


def test_shell_missing_a_mapped_sheet_is_rejected(tmp_path: Path) -> None:
    broken = tmp_path / "BRD.xlsx"
    Workbook().save(broken)
    template = replace(template_for(DocType.BRD), shell_path=broken)
    with pytest.raises(InvalidTemplateError, match="lacks sheets"):
        render_document(make_document(DocType.BRD), make_brd(), template)
