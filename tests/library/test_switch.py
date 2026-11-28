"""Spec 29 sections 2 to 5: coverage, switching a project, re-issue, built-in sync."""

import shutil
import subprocess
from pathlib import Path

import pytest

from masterba import library
from masterba.calibration.profile import CalibrationError
from masterba.models.enums import DocStatus, DocType
from masterba.rendering.project import xlsx_path
from masterba.trace_store import (
    ProjectStore,
    document_versions,
    get_config,
    get_document,
    latest_documents,
    list_decision_records,
    set_document_status,
)

REPO = Path(__file__).parents[2]


@pytest.fixture
def templates(chain: ProjectStore) -> Path:
    target = chain.root.parent / "templates"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(REPO / "templates", target)
    return target


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=True
    ).stdout


def test_the_builtin_set_drops_nothing_and_the_sample_drops_what_it_lacks(
    chain: ProjectStore, templates: Path
) -> None:
    assert library.project_coverage(chain, templates, "default").gaps == 0

    report = library.project_coverage(chain, templates, "sample-sier")
    brd = next(t for t in report.types if t.doc_type is DocType.BRD)
    assert brd.state == "calibrated"
    assert "list:$trace" in brd.dropped  # the SIer sample has no traceability sheet
    assert "header:$document.author" not in brd.dropped  # its cover prints 作成者
    assert report.gaps == sum(len(t.dropped) for t in report.types) > 0
    assert {t.doc_type for t in report.types} == {doc.type for doc, _ in latest_documents(chain)}


def test_a_type_the_set_does_not_calibrate_falls_back_to_the_builtin_one(
    chain: ProjectStore, templates: Path
) -> None:
    folder = templates / "companies" / "brd-only"
    folder.mkdir()
    for name in ("BRD.template.json", "BRD.xlsx", "BRD.confirmed"):
        shutil.copyfile(templates / "companies" / "sample-sier" / name, folder / name)

    report = library.project_coverage(chain, templates, "brd-only")
    srs = next(t for t in report.types if t.doc_type is DocType.SRS)
    assert srs.state == "fallback" and srs.dropped == []


def test_switching_with_gaps_needs_consent(chain: ProjectStore, templates: Path) -> None:
    before = _git(chain.root, "rev-parse", "HEAD")

    with pytest.raises(library.CoverageGapError) as refused:
        library.switch_template(chain, templates, "sample-sier")

    assert refused.value.report.gaps > 0
    assert _git(chain.root, "rev-parse", "HEAD") == before
    assert get_config(chain).company_id == "default"
    with pytest.raises(library.UnknownSetError):
        library.switch_template(chain, templates, "ghost")


def test_switching_renders_drafts_once_and_keeps_issued_files(
    chain: ProjectStore, templates: Path
) -> None:
    approved, _ = get_document(chain, "DOC-BRD-0001")
    set_document_status(chain, approved.id, approved.version, DocStatus.APPROVED, "test: approve")
    issued = xlsx_path(chain, approved).read_bytes()
    drafts = [d for d, _ in latest_documents(chain) if d.id != approved.id]
    before = {d.id: xlsx_path(chain, d).read_bytes() for d in drafts}
    versions = {d.id: document_versions(chain, d.id) for d in drafts}
    head = _git(chain.root, "rev-parse", "HEAD").strip()

    result = library.switch_template(chain, templates, "sample-sier", accept_gaps=True)

    assert get_config(chain).company_id == "sample-sier"
    assert result.kept == (f"{approved.id} v{approved.version}",)
    assert sorted(result.rendered) == sorted(f"{d.id} v{d.version}" for d in drafts)
    assert xlsx_path(chain, approved).read_bytes() == issued
    assert all(xlsx_path(chain, d).read_bytes() != before[d.id] for d in drafts)
    assert {d.id: document_versions(chain, d.id) for d in drafts} == versions
    assert list_decision_records(chain) == []
    log = _git(chain.root, "log", "--format=%s", f"{head}..HEAD").splitlines()
    assert log == ["project(PRJ-001): template sample-sier"]

    path = library.reissue(chain, templates, approved.id)
    assert path.read_bytes() != issued
    assert _git(chain.root, "log", "-1", "--format=%s").strip() == (
        f"render(PRJ-001): reissue {approved.id} v{approved.version} (sample-sier)"
    )


def test_switching_back_to_the_set_in_use_changes_nothing(
    chain: ProjectStore, templates: Path
) -> None:
    library.switch_template(chain, templates, "default")  # brings old files up to date
    head = _git(chain.root, "rev-parse", "HEAD")

    result = library.switch_template(chain, templates, "default")

    assert result.coverage.gaps == 0
    assert _git(chain.root, "rev-parse", "HEAD") == head


def test_a_clone_is_a_new_set_with_its_own_company_id(chain: ProjectStore, templates: Path) -> None:
    written = library.clone(chain.root.parent, "sample-sier", "my-sier")

    assert {p.name for p in written} >= {"BRD.template.json", "BRD.xlsx", "BRD.confirmed"}
    assert '"company_id": "my-sier"' in (written[0].parent / "BRD.template.json").read_text()
    assert library.set_types(chain.root.parent, "my-sier") == library.set_types(
        chain.root.parent, "sample-sier"
    )
    assert _git(chain.root, "log", "-1", "--format=%s").strip() == (
        "template(my-sier): clone of sample-sier"
    )
    with pytest.raises(CalibrationError, match="already exists"):
        library.clone(chain.root.parent, "sample-sier", "my-sier")
    with pytest.raises(CalibrationError, match="built-in"):
        library.clone(chain.root.parent, "default", "x")
    with pytest.raises(CalibrationError, match="no template set"):
        library.clone(chain.root.parent, "ghost", "x")


def test_the_builtin_set_follows_the_app_bundle(tmp_path: Path) -> None:
    root = tmp_path / "work"
    shutil.copytree(REPO / "templates" / "default", root / "templates" / "default")
    stale = root / "templates" / "default" / "BRD.template.json"
    stale.write_text("{}", encoding="utf-8")

    assert library.sync_builtin(root) == ["BRD.template.json"]
    assert stale.read_bytes() == (REPO / "templates" / "default" / "BRD.template.json").read_bytes()
    assert library.sync_builtin(root) == []
    assert library.sync_builtin(REPO) == []
