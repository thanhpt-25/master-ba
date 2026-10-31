import shutil
import subprocess
from pathlib import Path

import pytest
from openpyxl import load_workbook

from calibration_samples import brd_sample, srs_sample, unreadable_sample
from factories import make_config
from masterba import calibration
from masterba.calibration import CalibrationError
from masterba.models.enums import DocType
from masterba.rendering import resolve_template
from masterba.trace_store import create_project

REPO = Path(__file__).parents[2]
COMPANY = "acme"


@pytest.fixture
def root(git_repo: Path) -> Path:
    shutil.copytree(
        REPO / "templates", git_repo / "templates", ignore=shutil.ignore_patterns("companies")
    )
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "templates"], cwd=git_repo, check=True)
    return git_repo


def subjects(root: Path) -> list[str]:
    out = subprocess.run(
        ["git", "log", "--format=%s"], cwd=root, capture_output=True, text=True, check=True
    )
    return out.stdout.splitlines()


def test_a_brd_sample_is_mapped_by_meaning_not_by_position(root: Path, tmp_path: Path) -> None:
    sample = brd_sample(tmp_path / "s" / "brd.xlsx")

    result = calibration.calibrate(root, COMPANY, DocType.BRD, sample)

    table = result.draft.tables[0]
    assert (table.sheet, table.header_row, table.first_row, table.numbering) == (
        "要件一覧", 4, 5, "A",
    )  # fmt: skip
    fields = {c.col: c.field for c in table.columns}
    assert fields["B"] == "requirement_id"
    assert fields["C"] == "title"
    assert fields["D"] == "description"
    assert fields["E"] == "scope"
    assert fields.get("F") is None
    assert any("備考" in u for u in result.draft.unmapped)
    assert subjects(root)[0] == f"template({COMPANY}): calibrate BRD"


def test_a_draft_is_ignored_by_the_renderer_until_confirmed(root: Path, tmp_path: Path) -> None:
    calibration.calibrate(root, COMPANY, DocType.BRD, brd_sample(tmp_path / "brd.xlsx"))

    before = resolve_template(root / "templates", COMPANY, DocType.BRD)
    calibration.confirm(root, COMPANY, DocType.BRD, "alice")
    after = resolve_template(root / "templates", COMPANY, DocType.BRD)

    assert before.definition.company_id == "default"
    assert after.definition.company_id == COMPANY
    assert subjects(root)[0] == f"template({COMPANY}): confirm BRD"


def test_the_rendered_preview_keeps_the_layout_of_the_sample(root: Path, tmp_path: Path) -> None:
    calibration.calibrate(root, COMPANY, DocType.BRD, brd_sample(tmp_path / "brd.xlsx"))

    shown = calibration.preview(root, COMPANY, DocType.BRD)

    ws = load_workbook(shown.path)["要件一覧"]
    assert [c.value for c in ws[4]][:5] == ["No.", "要件ID", "要件名", "要件内容", "対象範囲"]
    assert ws["C5"].value == "Sample requirement 1"
    assert ws["A5"].value == 1
    assert ws.column_dimensions["D"].width == 60
    assert shown.differences == ()


def test_the_document_info_block_is_filled(root: Path, tmp_path: Path) -> None:
    calibration.calibrate(root, COMPANY, DocType.BRD, brd_sample(tmp_path / "brd.xlsx"))

    ws = load_workbook(calibration.preview(root, COMPANY, DocType.BRD).path)["要件一覧"]

    assert ws["B2"].value == "DOC-BRD-0001"
    assert ws["B3"].value == 1


def test_sample_data_rows_are_not_left_in_the_shell(root: Path, tmp_path: Path) -> None:
    calibration.calibrate(root, COMPANY, DocType.BRD, brd_sample(tmp_path / "brd.xlsx"))
    shell = root / "templates" / "companies" / COMPANY / "BRD.xlsx"

    assert load_workbook(shell)["要件一覧"]["C5"].value is None


def test_other_document_types_are_calibrated_the_same_way(root: Path, tmp_path: Path) -> None:
    result = calibration.calibrate(root, COMPANY, DocType.SRS, srs_sample(tmp_path / "srs.xlsx"))

    fields = {c.field for c in result.draft.tables[0].columns}
    assert {"requirement_id", "kind", "statement", "derives_from", "acceptance_hint"} <= fields


def test_a_sample_without_a_table_is_refused(root: Path, tmp_path: Path) -> None:
    with pytest.raises(CalibrationError):
        calibration.calibrate(root, COMPANY, DocType.BRD, unreadable_sample(tmp_path / "x.xlsx"))

    assert not (root / "templates" / "companies" / COMPANY).exists()


@pytest.mark.parametrize("name", ["macro.xlsm", "old.xls", "notes.txt"])
def test_only_xlsx_files_are_read(root: Path, tmp_path: Path, name: str) -> None:
    bad = tmp_path / name
    bad.write_bytes(b"not a workbook")

    with pytest.raises(CalibrationError):
        calibration.calibrate(root, COMPANY, DocType.BRD, bad)


def test_an_xlsx_that_is_not_a_zip_or_is_too_large_is_refused(root: Path, tmp_path: Path) -> None:
    fake = tmp_path / "fake.xlsx"
    fake.write_bytes(b"plain text")
    big = tmp_path / "big.xlsx"
    big.write_bytes(b"PK" + b"0" * 5_100_000)

    for path in (fake, big):
        with pytest.raises(CalibrationError):
            calibration.calibrate(root, COMPANY, DocType.BRD, path)


@pytest.mark.parametrize("company", ["default", "../evil", "", "a b", "x" * 41])
def test_unsafe_or_reserved_company_ids_are_refused(
    root: Path, tmp_path: Path, company: str
) -> None:
    with pytest.raises(CalibrationError):
        calibration.calibrate(root, company, DocType.BRD, brd_sample(tmp_path / "b.xlsx"))


def test_editing_a_column_rebuilds_and_removes_the_confirmation(root: Path, tmp_path: Path) -> None:
    calibration.calibrate(root, COMPANY, DocType.BRD, brd_sample(tmp_path / "brd.xlsx"))
    calibration.confirm(root, COMPANY, DocType.BRD, "alice")

    changed = calibration.set_column(root, COMPANY, DocType.BRD, "要件一覧", "F", "source_ref")

    assert {c.col: c.field for c in changed.tables[0].columns}["F"] == "source_ref"
    assert calibration.state_of(root, COMPANY, DocType.BRD) == "draft"
    assert subjects(root)[0] == f"template({COMPANY}): edit BRD"


def test_an_edit_to_an_unknown_field_or_column_is_refused(root: Path, tmp_path: Path) -> None:
    calibration.calibrate(root, COMPANY, DocType.BRD, brd_sample(tmp_path / "brd.xlsx"))

    with pytest.raises(CalibrationError):
        calibration.set_column(root, COMPANY, DocType.BRD, "要件一覧", "F", "no_such_field")
    with pytest.raises(CalibrationError):
        calibration.set_column(root, COMPANY, DocType.BRD, "要件一覧", "Z", "title")


def test_a_confirmed_template_needs_replace_to_be_calibrated_again(
    root: Path, tmp_path: Path
) -> None:
    sample = brd_sample(tmp_path / "brd.xlsx")
    calibration.calibrate(root, COMPANY, DocType.BRD, sample)
    calibration.confirm(root, COMPANY, DocType.BRD, "alice")

    with pytest.raises(CalibrationError):
        calibration.calibrate(root, COMPANY, DocType.BRD, sample)
    calibration.calibrate(root, COMPANY, DocType.BRD, sample, replace=True)

    assert calibration.state_of(root, COMPANY, DocType.BRD) == "draft"


def test_confirm_needs_a_name_and_unconfirm_needs_a_confirmation(
    root: Path, tmp_path: Path
) -> None:
    calibration.calibrate(root, COMPANY, DocType.BRD, brd_sample(tmp_path / "brd.xlsx"))

    with pytest.raises(CalibrationError):
        calibration.confirm(root, COMPANY, DocType.BRD, "  ")
    with pytest.raises(CalibrationError):
        calibration.unconfirm(root, COMPANY, DocType.BRD)
    calibration.confirm(root, COMPANY, DocType.BRD, "alice")
    calibration.unconfirm(root, COMPANY, DocType.BRD)

    assert calibration.state_of(root, COMPANY, DocType.BRD) == "draft"


def test_check_reports_a_missing_template_and_a_good_one(root: Path, tmp_path: Path) -> None:
    assert calibration.check(root, COMPANY, DocType.BRD)
    calibration.calibrate(root, COMPANY, DocType.BRD, brd_sample(tmp_path / "brd.xlsx"))

    assert calibration.check(root, COMPANY, DocType.BRD) == []


def test_list_templates_shows_company_type_and_state(root: Path, tmp_path: Path) -> None:
    calibration.calibrate(root, COMPANY, DocType.BRD, brd_sample(tmp_path / "brd.xlsx"))
    calibration.calibrate(root, COMPANY, DocType.SRS, srs_sample(tmp_path / "srs.xlsx"))
    calibration.confirm(root, COMPANY, DocType.SRS, "alice")

    assert calibration.list_templates(root) == [
        {"company": COMPANY, "doc_type": "BRD", "state": "draft"},
        {"company": COMPANY, "doc_type": "SRS", "state": "confirmed"},
    ]


def test_preview_with_a_project_document_uses_its_content(root: Path, tmp_path: Path) -> None:
    from factories import build_chain

    store = create_project(root / "projects", make_config())
    build_chain(store, root / "templates")
    calibration.calibrate(root, COMPANY, DocType.BRD, brd_sample(tmp_path / "brd.xlsx"))

    shown = calibration.preview(root, COMPANY, DocType.BRD, store)

    assert load_workbook(shown.path)["要件一覧"]["B2"].value == "DOC-BRD-0001"
