"""The sample company's workbooks: the script that makes them and the confirmed templates."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from masterba import calibration
from masterba.models.enums import DocType, TemplateSource
from masterba.rendering import resolve_template

REPO = Path(__file__).parents[2]
SCRIPT = REPO / "scripts" / "make_sier_samples.py"
COMPANY = "sample-sier"
TYPES = [t for t in DocType if t is not DocType.TEST_UAT]


@pytest.fixture
def root(git_repo: Path) -> Path:
    shutil.copytree(REPO / "templates" / "default", git_repo / "templates" / "default")
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "templates"], cwd=git_repo, check=True)
    return git_repo


def test_every_sample_maps_all_its_columns_but_the_remarks(root: Path, tmp_path: Path) -> None:
    subprocess.run([sys.executable, str(SCRIPT), str(tmp_path)], check=True, capture_output=True)

    for doc_type in TYPES:
        draft = calibration.calibrate(root, "acme", doc_type, tmp_path / f"{doc_type}.xlsx").draft

        assert draft.warnings == [], doc_type
        assert [u.split(": ")[1] for u in draft.unmapped] == ["備考"], doc_type


def test_the_committed_sample_company_templates_are_confirmed_and_used() -> None:
    for doc_type in TYPES:
        template = resolve_template(REPO / "templates", COMPANY, doc_type)

        assert template.definition.company_id == COMPANY, doc_type
        assert template.definition.source is TemplateSource.CALIBRATED_FROM_SAMPLE, doc_type
