import json
import shutil
from pathlib import Path

import pytest

from kbhelpers import keyword_backend, md
from masterba.cli import main
from masterba.knowledge.errors import UploadRefusedError
from masterba.knowledge.store import add_sources, replace_source
from masterba.questions.answer import QuestionError, check_answer
from masterba.trace_store import ProjectStore, get_config

AWS = "AKIAIOSFODNN7EXAMPLE"


def test_the_knowledge_base_refuses_a_file_with_a_secret(store: ProjectStore) -> None:
    report = add_sources(
        store,
        [md("ok.md", "# 用語\n担当 taro@example.com"), md("bad.md", f"key {AWS}")],
        "u",
        backend=keyword_backend(),
    )
    assert [s.id for s in report.added] == ["KB-0001"]
    assert report.refused == (
        ("bad.md", "the file contains a secret (aws_key, line 1); remove it and upload again"),
    )
    with pytest.raises(UploadRefusedError, match="aws_key"):
        replace_source(store, "KB-0001", md("ok.md", f"x\n{AWS}"), "u", backend=keyword_backend())


def test_an_answer_with_a_secret_is_refused() -> None:
    assert check_answer("Mail taro@example.com") == "Mail taro@example.com"
    with pytest.raises(QuestionError, match=r"secret \(credential, line 1\)"):
        check_answer("The password=Passw0rd123 is shared")


def cli(root: Path, *args: str) -> int:
    return main(["--root", str(root), *args])


def test_guard_commands(store: ProjectStore, capsys: pytest.CaptureFixture[str]) -> None:
    root = store.root.parent
    (store.path / "intake").mkdir(exist_ok=True)
    (store.path / "intake" / "a.md").write_text(f"mail taro@example.com\nkey {AWS}\n")

    assert cli(root, "guard", "scan", "--project", "PRJ-001") == 1
    out = capsys.readouterr().out.splitlines()
    assert "projects/PRJ-001/intake/a.md:2: secret aws_key [aws_key]" in out
    assert out[-1] == "PRJ-001: 1 pii, 1 secret"
    assert AWS not in "\n".join(out)

    (store.path / "intake" / "a.md").write_text("mail taro@example.com\n")
    assert cli(root, "guard", "scan", "--project", "PRJ-001", "--json", "--history") == 0
    data = json.loads(capsys.readouterr().out)
    assert data["counts"] == {"pii": 1}

    assert cli(root, "guard", "settings", "--project", "PRJ-001", "--term", "ACME") == 0
    assert json.loads(capsys.readouterr().out) == {"pii_masking": True, "masking_terms": ["ACME"]}
    assert (
        cli(root, "guard", "settings", "--project", "PRJ-001", "--pii", "off", "--clear-terms") == 0
    )
    capsys.readouterr()
    config = get_config(store)
    assert (config.pii_masking, config.masking_terms) == (False, [])

    assert cli(root, "guard", "prune", "--days", "30") == 0
    assert json.loads(capsys.readouterr().out) == {"removed": 0, "days": 30}
    assert cli(root, "audit", "--action", "guard.scan") == 0
    events = json.loads(capsys.readouterr().out)["events"]
    assert [e["actor"] for e in events] == ["cli", "cli"]


def test_doctor_warns_about_a_stored_secret(
    store: ProjectStore, capsys: pytest.CaptureFixture[str]
) -> None:
    root = store.root.parent
    shutil.copytree(
        Path(__file__).parents[2] / "templates" / "default", root / "templates" / "default"
    )
    (store.path / "intake").mkdir(exist_ok=True)
    (store.path / "intake" / "a.md").write_text(f"key {AWS}\n")
    cli(root, "doctor")
    out = capsys.readouterr().out
    assert "warn guard: secrets stored in PRJ-001 (1)" in out
