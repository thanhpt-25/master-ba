"""Cover, revision history, traceability and exclusions sheets (spec 19)."""

import datetime as dt
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from openpyxl import load_workbook

from factories import (
    doc_id,
    make_basic,
    make_basic_item,
    make_brd,
    make_brd_item,
    make_document,
    make_requirement,
    make_srs,
    make_srs_item,
    make_test_item,
    make_test_spec,
)
from masterba.models import DecisionRecord, Review, TestExclusion, TraceLink
from masterba.models.enums import (
    DocStatus,
    DocType,
    DrStatus,
    DrTrigger,
    ItemStatus,
    Level,
    LinkType,
    ReviewDecision,
    ReviewStage,
)
from masterba.models.review import ReviewedDocument
from masterba.rendering import (
    InvalidTemplateError,
    load_template,
    render_document,
    render_to_project,
    resolve_template,
)
from masterba.trace_store import (
    ProjectStore,
    add_decision_record,
    add_document,
    add_requirement,
    add_review,
    add_trace_link,
    write_dr_extra,
)

TEMPLATES = Path(__file__).parents[2] / "templates"
BRD = doc_id(DocType.BRD)
SRS = doc_id(DocType.SRS)
TEST_IT = doc_id(DocType.TEST_IT)
DATE = re.compile(r"^\d{4}/\d{2}/\d{2}$")


@pytest.mark.parametrize("doc_type", list(DocType))
def test_every_default_workbook_starts_with_cover_and_revision_history(doc_type: DocType) -> None:
    template = resolve_template(TEMPLATES, "default", doc_type)
    wb = load_workbook(template.shell_path)
    assert wb.sheetnames[:2] == ["表紙", "改訂履歴"]
    tail = "除外項目" if doc_type.value.startswith("TEST_") else "トレーサビリティ"
    assert wb.sheetnames[-1] == tail
    for ws in wb.worksheets:
        assert ws.page_setup.orientation == "landscape"
        footer: Any = ws.oddFooter
        assert footer.right.text == "ページ &P / &N"


def test_rendering_without_context_prints_the_title_and_japanese_status() -> None:
    template = resolve_template(TEMPLATES, "default", DocType.BRD)
    wb = render_document(make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)), template)
    cover = wb["表紙"]
    assert cover["B4"].value == "業務要件定義書"
    labels = {cover[f"B{r}"].value: cover[f"C{r}"].value for r in range(8, 18)}
    assert labels["文書ID"] == BRD
    assert labels["状態"] == "作成中"
    assert labels["承認者"] is None
    assert labels["作成者"] is None
    assert wb["業務要件"]["B5"].value == "作成中"
    assert wb["改訂履歴"]["B8"].value is None


def test_test_spec_prints_japanese_level_exclusions_and_a_judgement_list() -> None:
    template = resolve_template(TEMPLATES, "default", DocType.TEST_IT)
    content = make_test_spec(make_test_item(TEST_IT, 1, "TC-IT-0001", Level.IT)).model_copy(
        update={
            "exclusions": [
                TestExclusion(item_ref=f"{BRD}#item.9", reason="外部システム側で検証する")
            ]
        }
    )
    wb = render_document(make_document(DocType.TEST_IT), content, template)
    assert wb["テストケース"]["D8"].value == "結合テスト"
    assert [wb["除外項目"][f"{c}8"].value for c in "ABC"] == [
        1,
        f"{BRD}#item.9",
        "外部システム側で検証する",
    ]
    ranges = [str(dv.sqref) for dv in wb["テストケース"].data_validations.dataValidation]
    assert ranges == ["J8:J2000"]


def test_a_list_binding_to_an_unknown_field_fails_at_load(tmp_path: Path) -> None:
    shutil.copytree(TEMPLATES, tmp_path / "templates")
    path = tmp_path / "templates" / "default" / "SRS.template.json"
    data = json.loads(path.read_text("utf-8"))
    data["cell_bindings"]["lists"][0]["columns"][0]["field"] = "secret"
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(InvalidTemplateError, match="'secret' is not a \\$revisions field"):
        load_template(path)


def test_exclusions_are_refused_on_a_document_without_them(tmp_path: Path) -> None:
    shutil.copytree(TEMPLATES, tmp_path / "templates")
    path = tmp_path / "templates" / "default" / "SRS.template.json"
    data = json.loads(path.read_text("utf-8"))
    data["cell_bindings"]["lists"][0]["source"] = "$exclusions"
    data["cell_bindings"]["lists"][0]["columns"] = [{"col": "B", "field": "reason"}]
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(InvalidTemplateError, match="SRS has no exclusions"):
        load_template(path)


def _dr(store: ProjectStore) -> DecisionRecord:
    dr = DecisionRecord(
        id="DR-0001",
        date=dt.date(2026, 11, 20),
        trigger=DrTrigger.REQUIREMENT_CHANGE,
        description="承認フローに課長承認を追加する",
        decision="承認",
        impacted_items=[f"{BRD}#item.1"],
        affected_documents=[BRD],
        status=DrStatus.APPROVED,
        approver="tanaka",
    )
    add_decision_record(store, dr)
    return dr


def _store_v2(store: ProjectStore) -> None:
    add_document(store, make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)))
    v2 = make_brd(
        make_brd_item(BRD, 1, description="Changed description").model_copy(
            update={"status": ItemStatus.REMOVED}
        ),
        make_brd_item(BRD, 2),
        make_brd_item(BRD, 3),
    )
    add_document(store, make_document(DocType.BRD, version=2), v2)


def test_a_revised_version_names_its_dr_and_counts_changes(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    _store_v2(store)
    dr = _dr(store)
    path = render_to_project(store, BRD, TEMPLATES, revised_by=dr.id)
    history = load_workbook(path)["改訂履歴"]
    first = [history[f"{c}8"].value for c in "BDEF"]
    second = [history[f"{c}9"].value for c in "BDEF"]
    assert first == [1, "初版作成", "新規作成", "MasterBA"]
    assert second == [
        2,
        "追加 2件、削除 1件",
        "DR-0001（要件変更）: 承認フローに課長承認を追加する",
        "MasterBA",
    ]
    assert DATE.match(str(history["C8"].value))
    cover = load_workbook(path)["表紙"]
    assert DATE.match(str(cover["C13"].value))

    # Once propagation records the version, a later render finds the same DR: same bytes.
    write_dr_extra(
        store,
        dr.id,
        "propagation",
        {"documents": {BRD: {"outcome": "revised", "version": 2, "run_id": "RUN-0001"}}},
        "dr(PRJ-001): propagate DR-0001 DOC-BRD-0001",
    )
    count = len(commit_log())
    render_to_project(store, BRD, TEMPLATES)
    assert len(commit_log()) == count


def test_an_approval_fills_the_approver_on_the_cover_and_history(store: ProjectStore) -> None:
    add_document(store, make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)))
    review = Review(
        id="REV-0001",
        stage=ReviewStage.BRD,
        documents=[ReviewedDocument(doc_id=BRD, version=1)],
        decision=ReviewDecision.APPROVED,
        by="suzuki",
        at=dt.datetime(2026, 11, 21, 9, 30, tzinfo=dt.UTC),
    )
    add_review(store, review, DocStatus.APPROVED)
    wb = load_workbook(render_to_project(store, BRD, TEMPLATES))
    cover = wb["表紙"]
    labels = {cover[f"B{r}"].value: cover[f"C{r}"].value for r in range(8, 18)}
    assert labels["状態"] == "承認済"
    assert labels["承認者"] == "suzuki"
    assert labels["承認日"] == "2026/11/21"
    assert labels["作成者"] == "MasterBA"
    assert labels["会社名"] is None
    assert wb["改訂履歴"]["G8"].value == "suzuki"


def test_traceability_lists_upstream_and_downstream_of_each_active_item(
    store: ProjectStore,
) -> None:
    for n in (1, 2, 3):
        add_requirement(store, make_requirement(n))
    items = (
        make_srs_item(SRS, 1, req="REQ-0002"),
        make_srs_item(SRS, 2, req="REQ-0003", status=ItemStatus.REMOVED),
    )
    add_document(store, make_document(DocType.SRS), make_srs(*items))
    basic = doc_id(DocType.BASIC_DESIGN)
    add_document(store, make_document(DocType.BASIC_DESIGN), make_basic(make_basic_item(basic, 1)))
    test_st = doc_id(DocType.TEST_ST)
    add_document(
        store,
        make_document(DocType.TEST_ST),
        make_test_spec(make_test_item(test_st, 1, "TC-ST-0001", Level.ST)),
    )
    for link in (
        TraceLink(from_id="REQ-0001", to_id="REQ-0002", link_type=LinkType.DERIVES_FROM),
        TraceLink(from_id="REQ-0002", to_id=f"{basic}#item.1", link_type=LinkType.REALIZES),
        TraceLink(from_id="REQ-0002", to_id="TC-ST-0001", link_type=LinkType.TESTS),
    ):
        add_trace_link(store, link)
    ws = load_workbook(render_to_project(store, SRS, TEMPLATES))["トレーサビリティ"]
    assert [ws[f"{c}8"].value for c in "BDE"] == [
        "REQ-0002",
        "REQ-0001",
        f"{basic}#item.1\nTC-ST-0001",
    ]
    assert ws["B9"].value is None
