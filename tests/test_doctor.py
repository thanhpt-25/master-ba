"""`masterba doctor` (spec 11 section 6)."""

import shutil
import subprocess
from pathlib import Path

import pytest

from masterba.api.auth import UserStore
from masterba.cli import main

REPO = Path(__file__).parents[1]


def doctor(root: Path, *extra: str) -> int:
    return main(["--root", str(root), "doctor", *extra])


@pytest.fixture
def isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No global git config; the author comes from the variables a container sets."""
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "no-gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for kind in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{kind}_NAME", "MasterBA")
        monkeypatch.setenv(f"GIT_{kind}_EMAIL", "masterba@localhost")


def test_a_prepared_root_passes_and_warns_only_about_the_key(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copytree(REPO / "templates" / "default", git_repo / "templates" / "default")
    UserStore(git_repo / ".masterba" / "users.json", 1000).add("admin", "admin", "pw-12345678")
    shutil.copy(REPO / ".gitignore", git_repo / ".gitignore")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert doctor(git_repo) == 0
    out = capsys.readouterr().out.splitlines()
    assert [line.split(":")[0] for line in out] == [
        "ok   git",
        "ok   work tree",
        "ok   templates",
        "ok   state",
        "ok   ignores",
        "warn model",
    ]


@pytest.mark.parametrize("gitignore", [None, ".masterba/\nprojects/*/knowledge/index/\n"])
def test_a_gitignore_without_the_knowledge_patterns_is_reported(
    git_repo: Path, gitignore: str | None, capsys: pytest.CaptureFixture[str]
) -> None:
    if gitignore is not None:
        (git_repo / ".gitignore").write_text(gitignore, encoding="utf-8")
    doctor(git_repo)
    line = next(x for x in capsys.readouterr().out.splitlines() if x.startswith("warn ignores"))
    assert "projects/*/knowledge/sources/" in line
    assert "projects/*/knowledge/.lock" in line
    assert ("projects/*/knowledge/index/" in line) is (gitignore is None)


def test_an_unreadable_gitignore_is_reported(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (git_repo / ".gitignore").write_bytes(b"\xff\xfe")
    doctor(git_repo)
    assert "warn ignores:" in capsys.readouterr().out


def test_missing_templates_fail_with_the_fix(
    git_repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert doctor(git_repo) == 1
    out = capsys.readouterr().out
    assert "FAIL templates: missing or invalid: BRD" in out
    assert "warn state: no dashboard user" in out


@pytest.mark.usefixtures("isolated_git")
def test_a_folder_outside_git_fails_and_init_prepares_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    folder = tmp_path / "work"
    folder.mkdir()
    assert doctor(folder) == 1
    assert "FAIL work tree" in capsys.readouterr().out
    assert doctor(folder, "--init") == 0
    out = capsys.readouterr().out
    assert "ok   templates" in out
    assert (folder / ".gitignore").read_text(encoding="utf-8") == (
        ".masterba/\n"
        "projects/*/knowledge/sources/\n"
        "projects/*/knowledge/index/\n"
        "projects/*/knowledge/.lock\n"
    )
    assert "ok   ignores" in out
    ignored = ["projects/PRJ-001/knowledge/sources/KB-0001.md", "projects/PRJ-001/knowledge/.lock"]
    for path in ignored:
        check = subprocess.run(["git", "check-ignore", "-q", path], cwd=folder, check=False)
        assert check.returncode == 0, path
    manifest = "projects/PRJ-001/knowledge/manifest.json"
    check = subprocess.run(["git", "check-ignore", "-q", manifest], cwd=folder, check=False)
    assert check.returncode == 1


def test_init_refuses_a_folder_that_is_not_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "notes.txt").write_text("keep me", encoding="utf-8")
    assert doctor(tmp_path, "--init") == 1
    assert "is not empty" in capsys.readouterr().err
    assert not (tmp_path / ".git").exists()
