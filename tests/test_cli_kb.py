"""`masterba kb ...` output and exit codes (spec 12, Requirements 1, 3, 5, 6, 7)."""

from pathlib import Path

import pytest

from masterba.cli import main
from masterba.knowledge import embedder, indexer


@pytest.fixture(autouse=True)
def keyword_only(monkeypatch: pytest.MonkeyPatch) -> None:
    # The suite must not depend on the rag extra or a cached model on this machine.
    monkeypatch.setattr(indexer, "rag_available", lambda: False)
    monkeypatch.setattr("masterba.cli_kb.rag_available", lambda: False)


@pytest.fixture
def root(git_repo: Path) -> Path:
    assert main(["--root", str(git_repo), "init-project", "--project", "PRJ-001"]) == 0
    return git_repo


def kb(root: Path, capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, str, str]:
    capsys.readouterr()
    code = main(["--root", str(root), "kb", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def write(tmp: Path, name: str, text: str) -> str:
    path = tmp / name
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_add_list_search_remove(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code, out, _ = kb(root, capsys, "list", "--project", "PRJ-001")
    assert (code, out) == (0, "the knowledge base is empty\n")
    glossary = write(tmp_path, "glossary.md", "# 用語\n受注とは注文を受けること。")
    code, out, _ = kb(root, capsys, "add", "--project", "PRJ-001", "--by", "tanaka", glossary)
    assert code == 0
    assert "added KB-0001 glossary.md: indexed" in out
    assert "notice: vector search is unavailable" in out
    code, out, _ = kb(root, capsys, "list", "--project", "PRJ-001")
    assert code == 0 and out.startswith("KB-0001\tglossary.md\ttanaka\t") and "\tindexed" in out
    code, out, _ = kb(root, capsys, "search", "--project", "PRJ-001", "受注", "-k", "3")
    assert code == 0
    assert out.splitlines() == [
        "notice: only keyword search was used",
        "1. KB-0001#chunk.1  用語",
        "   受注とは注文を受けること。",
    ]
    code, out, _ = kb(root, capsys, "search", "--project", "PRJ-001", "出荷")
    assert code == 0 and "no passages matched" in out
    code, out, _ = kb(root, capsys, "remove", "--project", "PRJ-001", "KB-0001")
    assert (code, out) == (0, "removed KB-0001 glossary.md\n")
    code, _, err = kb(root, capsys, "remove", "--project", "PRJ-001", "KB-0001")
    assert code == 1 and "KB-0001: already removed" in err
    code, _, err = kb(root, capsys, "remove", "--project", "PRJ-001", "KB-0042")
    assert code == 1 and "KB-0042: unknown" in err


def test_refused_and_skipped_files(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    a = write(tmp_path, "a.md", "受注")
    dup = write(tmp_path, "copy.md", "受注")
    csv = write(tmp_path, "data.csv", "x")
    code, out, _ = kb(
        root, capsys, "add", "--project", "PRJ-001", a, dup, csv, str(tmp_path / "missing.md")
    )
    assert code == 1
    assert "added KB-0001 a.md: indexed" in out
    assert "skipped copy.md: same content as a.md" in out
    assert "refused data.csv: the file type is not supported" in out
    assert "refused missing.md: the file does not exist" in out


def test_replace_and_reindex(
    root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    kb(root, capsys, "add", "--project", "PRJ-001", write(tmp_path, "a.md", "受注"))
    kb(root, capsys, "add", "--project", "PRJ-001", write(tmp_path, "b.pdf", "%PDF-1.4 x"))
    code, out, _ = kb(
        root, capsys, "replace", "--project", "PRJ-001", "KB-0001", write(tmp_path, "c.md", "出荷")
    )
    assert code == 0 and "replaced KB-0001 with c.md: indexed" in out
    assert "proposed" not in out  # an uncited source makes no DR
    code, out, _ = kb(root, capsys, "reindex", "--project", "PRJ-001")
    assert code == 0
    assert "sources indexed: 1" in out and "chunks indexed: 1" in out
    assert "failed KB-0002: " in out and "notice: vector search is unavailable" in out
    (root / "projects" / "PRJ-001" / "knowledge" / "sources" / "KB-0001.md").unlink()
    code, _, err = kb(root, capsys, "reindex", "--project", "PRJ-001")
    assert code == 1 and "KB-0001" in err


def test_errors(root: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _, err = kb(root, capsys, "list", "--project", "PRJ-404")
    assert code == 1 and "PRJ-404" in err
    code, _, err = kb(root, capsys, "search", "--project", "PRJ-001", "受注")
    assert code == 1 and "index is missing" in err
    code, _, err = kb(root, capsys, "search", "--project", "PRJ-001", "受注", "-k", "51")
    assert code == 1 and "invalid k" in err
    code, _, err = kb(root, capsys, "setup")
    assert code == 1 and "uv sync --extra rag" in err


def test_setup_with_the_extra(
    root: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("masterba.cli_kb.rag_available", lambda: True)
    monkeypatch.setattr(
        "masterba.cli_kb.setup_model",
        lambda name: embedder.SetupResult(name, Path("/models"), downloaded=True),
    )
    code, out, _ = kb(root, capsys, "setup", "--model", "org/m")
    assert (code, out) == (0, "model org/m: downloaded\ncache: /models\n")
