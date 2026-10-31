from collections.abc import Callable
from pathlib import Path

import pytest
from openpyxl import load_workbook

from factories import doc_id, make_brd, make_brd_item, make_document
from masterba.models.enums import DocType
from masterba.rendering import RenderValidationError, render_to_project
from masterba.trace_store import ProjectStore, add_document

TEMPLATES = Path(__file__).parents[2] / "templates"
BRD = doc_id(DocType.BRD)


@pytest.fixture
def stored(store: ProjectStore) -> ProjectStore:
    add_document(store, make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)))
    return store


def test_render_writes_xlsx_in_one_commit_and_keeps_json_untouched(
    stored: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    json_path = stored.path / "json" / "brd" / f"{BRD}.v1.json"
    before_json = json_path.read_bytes()
    before = len(commit_log())
    path = render_to_project(stored, BRD, TEMPLATES)
    assert path == stored.path / "xlsx" / "brd" / f"{BRD}.v1.xlsx"
    assert commit_log()[0] == f"render(PRJ-001): xlsx {BRD} v1"
    assert len(commit_log()) == before + 1
    assert json_path.read_bytes() == before_json
    assert load_workbook(path)["業務要件"]["B8"].value == "REQ-0001"


def test_rendering_unchanged_content_again_creates_no_commit(
    stored: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    render_to_project(stored, BRD, TEMPLATES)
    count = len(commit_log())
    render_to_project(stored, BRD, TEMPLATES)
    assert len(commit_log()) == count


def test_an_older_version_can_be_rendered_and_other_versions_stay(stored: ProjectStore) -> None:
    items = (make_brd_item(BRD, 1), make_brd_item(BRD, 2))
    add_document(stored, make_document(DocType.BRD, version=2), make_brd(*items))
    v2 = render_to_project(stored, BRD, TEMPLATES)
    v1 = render_to_project(stored, BRD, TEMPLATES, version=1)
    assert (v1.name, v2.name) == (f"{BRD}.v1.xlsx", f"{BRD}.v2.xlsx")
    assert v1.exists()
    assert v2.exists()
    assert (
        len(list(load_workbook(v1)["業務要件"].iter_rows(min_row=8, max_col=2, values_only=True)))
        == 1
    )


def test_failed_render_writes_no_file_and_no_commit(
    store: ProjectStore, commit_log: Callable[[], list[str]]
) -> None:
    huge = make_brd_item(BRD, 1, description="x" * 40000)
    add_document(store, make_document(DocType.BRD), make_brd(huge))
    count = len(commit_log())
    with pytest.raises(RenderValidationError):
        render_to_project(store, BRD, TEMPLATES)
    assert not (store.path / "xlsx").exists()
    assert len(commit_log()) == count
