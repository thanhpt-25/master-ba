import io
import json
from pathlib import Path

import pytest

from masterba.cli import main


def run(root: Path, *args: str) -> int:
    return main(["--root", str(root), *args])


def out(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    data: dict[str, object] = json.loads(capsys.readouterr().out)
    return data


def add(root: Path, monkeypatch: pytest.MonkeyPatch, name: str, role: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO("a long enough password\n"))
    assert run(root, "user", "add", name, "--role", role, "--password-stdin") == 0


def test_roles_passwords_limits_and_usage_from_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    add(tmp_path, monkeypatch, "alice", "viewer")
    capsys.readouterr()
    assert run(tmp_path, "user", "role", "alice", "approver") == 0
    assert out(capsys) == {"name": "alice", "role": "approver"}
    monkeypatch.setattr("sys.stdin", io.StringIO("another long password\n"))
    assert run(tmp_path, "user", "password", "alice", "--password-stdin") == 0
    assert out(capsys) == {"name": "alice", "password": "changed"}
    assert run(tmp_path, "user", "limit", "--default", "--weekly", "9000") == 0
    assert out(capsys) == {"default": {"session": None, "weekly": 9000}}
    assert run(tmp_path, "user", "limit", "alice", "--session", "100") == 0
    assert out(capsys) == {"name": "alice", "limits": {"session": 100, "weekly": 9000}}
    assert run(tmp_path, "user", "limit", "alice", "--weekly", "none") == 0
    assert out(capsys) == {"name": "alice", "limits": {"session": 100, "weekly": None}}
    assert run(tmp_path, "user", "limit", "alice", "--clear") == 0
    assert out(capsys) == {"name": "alice", "limits": {"session": None, "weekly": 9000}}
    assert run(tmp_path, "user", "usage", "alice", "--reset") == 0
    usage = out(capsys)
    assert [w["used"] for w in usage["windows"]] == [0, 0]  # type: ignore[attr-defined]
    assert run(tmp_path, "user", "limit") == 1
    assert "--default" in capsys.readouterr().err
    assert run(tmp_path, "user", "usage", "ghost") == 1


def test_projects_are_handed_over_and_shared_from_the_command_line(
    git_repo: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(git_repo, "init-project", "--project", "PRJ-001") == 0
    add(git_repo, monkeypatch, "root", "admin")
    add(git_repo, monkeypatch, "alice", "approver")
    capsys.readouterr()
    assert run(git_repo, "access", "show", "PRJ-001") == 0
    # alice was added after the upgrade migration, so PRJ-001 is not shared with her.
    assert out(capsys) == {"project_id": "PRJ-001", "owner": "root", "members": {}}
    assert run(git_repo, "access", "share", "PRJ-001", "alice", "--role", "approver") == 0
    assert out(capsys)["members"] == {"alice": "approver"}
    assert run(git_repo, "access", "owner", "PRJ-001", "alice") == 0
    assert out(capsys) == {
        "project_id": "PRJ-001",
        "owner": "alice",
        "members": {"root": "approver"},
    }
    assert run(git_repo, "access", "unshare", "PRJ-001", "root") == 0
    assert out(capsys)["members"] == {}
    assert run(git_repo, "access", "show", "PRJ-404") == 1


def test_disable_enable_sign_out_and_the_audit_log_from_the_command_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    add(tmp_path, monkeypatch, "alice", "viewer")
    capsys.readouterr()
    assert run(tmp_path, "user", "disable", "alice") == 0
    assert out(capsys) == {"name": "alice", "role": "viewer", "disabled": True}
    assert run(tmp_path, "user", "enable", "alice") == 0
    assert out(capsys)["disabled"] is False
    assert run(tmp_path, "user", "signout", "alice") == 0
    capsys.readouterr()
    assert run(tmp_path, "user", "list") == 0
    assert out(capsys) == {"users": [{"name": "alice", "role": "viewer", "disabled": False}]}
    assert run(tmp_path, "user", "disable", "ghost") == 1
    capsys.readouterr()
    assert run(tmp_path, "audit", "--action", "user") == 0
    events = out(capsys)["events"]
    assert [e["action"] for e in events] == [  # type: ignore[attr-defined]
        "user.signout",
        "user.enable",
        "user.disable",
        "user.create",
    ]
    assert {e["actor"] for e in events} == {"cli"}  # type: ignore[attr-defined]
