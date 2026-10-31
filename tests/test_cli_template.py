import json
import shutil
from pathlib import Path

import pytest

from calibration_samples import brd_sample
from masterba.cli import main
from masterba.llm import FakeLLM, LLMError

REPO = Path(__file__).parents[1]
BASE = ("--company", "acme", "--type", "BRD")


@pytest.fixture
def root(git_repo: Path) -> Path:
    shutil.copytree(REPO / "templates", git_repo / "templates")
    return git_repo


def cli(root: Path, *args: str) -> int:
    return main(["--root", str(root), *args], llm_factory=lambda model: FakeLLM([]))


def out(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    data: dict[str, object] = json.loads(capsys.readouterr().out)
    return data


def test_the_whole_flow_from_the_command_line(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = brd_sample(tmp_path / "brd.xlsx")

    assert cli(root, "template", "calibrate", str(sample), *BASE) == 0
    assert out(capsys)["state"] == "draft"
    assert cli(root, "template", "show", *BASE) == 0
    assert out(capsys)["state"] == "draft"
    assert cli(root, "template", "set", *BASE, "--sheet", "要件一覧", "--col", "F",
               "--field", "source_ref") == 0  # fmt: skip
    capsys.readouterr()
    assert cli(root, "template", "check", *BASE) == 0
    assert out(capsys)["ok"] is True
    assert cli(root, "template", "preview", *BASE) == 0
    assert out(capsys)["differences"] == []
    assert cli(root, "template", "confirm", *BASE, "--by", "alice") == 0
    assert out(capsys)["by"] == "alice"
    assert cli(root, "template", "list") == 0
    assert out(capsys)["templates"] == [
        {"company": "acme", "doc_type": "BRD", "state": "confirmed"}
    ]
    assert cli(root, "template", "unconfirm", *BASE) == 0


def test_errors_are_reported_without_a_traceback(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.xlsm"
    bad.write_bytes(b"x")

    assert cli(root, "template", "calibrate", str(bad), *BASE) == 1
    assert "masterba: error" in capsys.readouterr().err
    assert cli(root, "template", "check", *BASE) == 1


def test_calibrate_with_a_failing_model_keeps_the_heuristic_draft(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    sample = brd_sample(tmp_path / "brd.xlsx")

    code = main(
        ["--root", str(root), "template", "calibrate", str(sample), *BASE, "--model", "m"],
        llm_factory=lambda model: FakeLLM([LLMError("down")]),
    )

    assert code == 0
    assert "could not be used" in str(out(capsys)["messages"])
