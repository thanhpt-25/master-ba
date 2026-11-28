import shutil
import subprocess
from pathlib import Path

import pytest
from openpyxl import load_workbook

from calibration_samples import brd_sample
from masterba import library
from masterba.calibration import CalibrationError
from masterba.calibration.store import calibrate, check, paths_for, preview, set_column
from masterba.models.enums import DocType

REPO = Path(__file__).parents[2]


@pytest.fixture
def root(git_repo: Path) -> Path:
    shutil.copytree(
        REPO / "templates", git_repo / "templates", ignore=shutil.ignore_patterns("companies")
    )
    return git_repo


def _tracked(root: Path) -> list[str]:
    done = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True)
    return done.stdout.splitlines()


def test_calibration_cleans_the_shell_and_keeps_the_sample_out_of_git(
    root: Path, tmp_path: Path
) -> None:
    sample = brd_sample(tmp_path / "brd.xlsx")
    wb = load_workbook(sample)
    wb["表紙"]["F9"] = "作成者 yamada@example.co.jp"
    wb.properties.subject = "ACME internal"
    wb.save(sample)

    result = calibrate(root, "acme", DocType.BRD, sample)
    assert "cleared 表紙!F9: it held personal data or a secret" in result.draft.warnings
    paths = paths_for(root, "acme", DocType.BRD)
    shell = load_workbook(paths.shell)
    assert shell["表紙"]["F9"].value is None
    assert shell["表紙"]["A1"].value == "業務要件定義書"
    assert shell.properties.subject is None
    assert paths.sample.is_file()
    tracked = _tracked(root)
    assert "templates/companies/acme/BRD.xlsx" in tracked
    assert "templates/companies/acme/BRD.sample.xlsx" not in tracked

    clone = library.clone(root, "acme", "acme-copy")
    assert all(not p.name.endswith(".sample.xlsx") for p in clone)
    assert check(root, "acme-copy", DocType.BRD) == []
    assert preview(root, "acme-copy", DocType.BRD).differences == ()
    with pytest.raises(CalibrationError, match="not on this server"):
        set_column(root, "acme-copy", DocType.BRD, "要件一覧", "C", None)
