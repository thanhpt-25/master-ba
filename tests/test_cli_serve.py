import io
import json
from pathlib import Path
from typing import Any

import pytest

from masterba.api import Settings, settings_from_env
from masterba.cli import main


def run(root: Path, *args: str) -> int:
    return main(["--root", str(root), *args])


def test_users_are_managed_from_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("a long enough password\n"))
    assert run(tmp_path, "user", "add", "alice", "--role", "approver", "--password-stdin") == 0
    assert json.loads(capsys.readouterr().out) == {"name": "alice", "role": "approver"}
    assert run(tmp_path, "user", "list") == 0
    assert json.loads(capsys.readouterr().out) == {"users": [{"name": "alice", "role": "approver"}]}
    users_file = tmp_path / ".masterba" / "users.json"
    assert "a long enough password" not in users_file.read_text("utf-8")
    assert run(tmp_path, "user", "remove", "alice") == 0
    assert json.loads(capsys.readouterr().out) == {"removed": "alice"}
    assert run(tmp_path, "user", "list") == 0
    assert json.loads(capsys.readouterr().out) == {"users": []}


def test_user_errors_exit_with_1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("short\n"))
    assert run(tmp_path, "user", "add", "bob", "--role", "viewer", "--password-stdin") == 1
    assert "at least 8 characters" in capsys.readouterr().err
    assert run(tmp_path, "user", "remove", "ghost") == 1
    assert "does not exist" in capsys.readouterr().err
    with pytest.raises(SystemExit) as caught:
        run(tmp_path, "user", "add", "bob", "--role", "owner")
    assert caught.value.code == 2


def test_serve_starts_the_app_on_the_requested_address(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, Any]] = []

    def fake_run(app: object, **kwargs: Any) -> None:
        calls.append({"app": app, **kwargs})

    monkeypatch.setattr("uvicorn.run", fake_run)
    assert run(git_repo, "serve", "--host", "127.0.0.1", "--port", "9123") == 0
    assert (calls[0]["host"], calls[0]["port"]) == ("127.0.0.1", 9123)
    assert calls[0]["app"].title == "MasterBA"


def test_serve_defaults_to_loopback_and_needs_a_git_work_tree(
    tmp_path_factory: pytest.TempPathFactory,
    git_repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[dict[str, Any]] = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kw: calls.append(kw))
    assert run(git_repo, "serve") == 0
    assert (calls[0]["host"], calls[0]["port"]) == ("127.0.0.1", 8000)
    assert run(tmp_path_factory.mktemp("no-git"), "serve") == 1
    assert "not inside a git work tree" in capsys.readouterr().err


def test_models_come_from_the_server_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MASTERBA_MODEL", "m1")
    monkeypatch.setenv("MASTERBA_QA_MODEL", "m2")
    monkeypatch.setenv("MASTERBA_TEST_MODEL", "m3")
    settings = settings_from_env(tmp_path)
    assert (settings.model, settings.qa_model, settings.test_model) == ("m1", "m2", "m3")
    monkeypatch.delenv("MASTERBA_QA_MODEL")
    monkeypatch.delenv("MASTERBA_TEST_MODEL")
    bare = settings_from_env(tmp_path)
    assert (bare.qa_model, bare.test_model) == (None, None)
    assert isinstance(bare, Settings)
    assert bare.projects == tmp_path / "projects"
    assert bare.uploads_dir == tmp_path / ".masterba" / "uploads"
