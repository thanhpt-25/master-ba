"""KB_Store and indexer unit tests (Requirements 1, 3 and 5)."""

import subprocess
from pathlib import Path

import pytest

from kbhelpers import MemoryVectors, hash_backend, head, keyword_backend, last_commit, md
from masterba.knowledge import store as kb
from masterba.knowledge.errors import (
    IndexBuildError,
    KbCommitError,
    KbError,
    UnknownSourceError,
    UploadRefusedError,
)
from masterba.knowledge.indexer import current_generation, open_index, reindex
from masterba.knowledge.store import IncomingFile, add_sources, list_sources
from masterba.trace_store import NotFoundError, ProjectStore

MANIFEST = "projects/PRJ-001/knowledge/manifest.json"


def _status(store: ProjectStore) -> list[tuple[str, str]]:
    return [(v.source.id, v.status) for v in list_sources(store, backend=keyword_backend())]


def test_add_commits_only_the_manifest(store: ProjectStore) -> None:
    report = add_sources(
        store,
        [md("a.md", "# 用語\n受注とは注文。"), md("b.txt", "出荷")],
        "tanaka",
        backend=keyword_backend(),
    )
    assert [s.id for s in report.added] == ["KB-0001", "KB-0002"]
    assert report.keyword_only and report.notice
    assert {s.status for s in report.statuses.values()} == {"indexed"}
    subject, files = last_commit(store.root)
    assert subject == "kb(PRJ-001): add KB-0001, KB-0002"
    assert files == [MANIFEST]
    for rel in ("sources/KB-0001.md", "index/CURRENT", ".lock"):
        ignored = subprocess.run(
            ["git", "check-ignore", "-q", str(store.path / "knowledge" / rel)],
            cwd=store.root,
            check=False,
        )
        assert ignored.returncode == 0, rel
    assert _status(store) == [("KB-0001", "indexed"), ("KB-0002", "indexed")]


def test_duplicates_refusals_and_no_commit(store: ProjectStore) -> None:
    add_sources(store, [md("a.md", "x")], "u", backend=keyword_backend())
    before = head(store.root)
    report = add_sources(
        store,
        [md("again.md", "x"), md("c.csv", "y"), md("n1.md", "z"), md("n2.md", "z")],
        "u",
        backend=keyword_backend(),
    )
    assert report.skipped == (("again.md", "KB-0001"), ("n2.md", "n1.md"))
    assert [name for name, _ in report.refused] == ["c.csv"]
    assert [s.id for s in report.added] == ["KB-0002"]
    head_after = head(store.root)
    report = add_sources(store, [md("dup.md", "z")], "u", backend=keyword_backend())
    assert report.added == () and head(store.root) == head_after != before


def test_whole_command_rejections(store: ProjectStore, projects_root: Path) -> None:
    with pytest.raises(KbError, match="too many files"):
        add_sources(store, [md(f"{i}.md", str(i)) for i in range(101)], "u")
    missing = ProjectStore(projects_root, "PRJ-999")
    with pytest.raises(NotFoundError):
        add_sources(missing, [md("a.md", "a")], "u")
    with pytest.raises(NotFoundError):
        reindex(missing)
    assert not (missing.path / "knowledge").exists()
    manifest = store.path / "knowledge" / "manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        '{"format": 1, "sources": [{"id": "KB-9999", "file_name": "z.md", "suffix": ".md",'
        ' "sha256": "' + "0" * 64 + '", "added_by": "u", "added_at": "2026-01-01T00:00:00Z"}]}'
    )
    with pytest.raises(KbError, match="KB-9999"):
        add_sources(store, [md("a.md", "a")], "u", backend=keyword_backend())


def test_commit_failure_rolls_back(store: ProjectStore, monkeypatch: pytest.MonkeyPatch) -> None:
    add_sources(store, [md("a.md", "a")], "u", backend=keyword_backend())
    paths = kb.kb_paths(store)
    manifest = paths.manifest.read_bytes()
    generation = current_generation(paths)

    def fail(*args: object) -> bool:
        raise RuntimeError("disk full")

    monkeypatch.setattr(kb, "commit_paths", fail)
    with pytest.raises(KbCommitError, match="disk full"):
        add_sources(store, [md("b.md", "b")], "u", backend=keyword_backend())
    assert paths.manifest.read_bytes() == manifest
    assert sorted(p.name for p in paths.sources.iterdir()) == ["KB-0001.md"]
    assert current_generation(paths) == generation
    assert sorted(p.name for p in paths.index.iterdir()) == ["CURRENT", generation]


def test_replace_and_remove(store: ProjectStore) -> None:
    vectors = MemoryVectors()
    backend = hash_backend(vectors)
    add_sources(store, [md("a.md", "受注"), md("b.md", "出荷")], "u", backend=backend)
    report = kb.replace_source(store, "KB-0001", md("a2.txt", "請求"), "sato", backend=backend)
    assert report.after.id == "KB-0001" and report.after.suffix == ".txt"
    assert last_commit(store.root) == (
        "kb(PRJ-001): replace KB-0001",
        [MANIFEST],
    )
    paths = kb.kb_paths(store)
    assert not paths.source_file("KB-0001", ".md").exists()
    index = open_index(paths, backend)
    assert index.keyword.search("請求", 5, None) == ["KB-0001#chunk.1"]
    assert index.keyword.search("受注", 5, None) == []
    assert index.vectors is not None
    assert index.vectors.refs() == set(index.keyword.chunk_refs())
    index.close()
    with pytest.raises(UploadRefusedError, match="KB-0002"):
        kb.replace_source(store, "KB-0001", md("c.md", "出荷"), "u", backend=backend)
    removed = kb.remove_source(store, "KB-0002", backend=backend)
    assert removed.removed and removed.removed_at is not None
    assert last_commit(store.root)[0] == "kb(PRJ-001): remove KB-0002"
    assert not paths.source_file("KB-0002", ".md").exists()
    before = head(store.root)
    for call in (
        lambda: kb.remove_source(store, "KB-0002", backend=backend),
        lambda: kb.remove_source(store, "KB-0042", backend=backend),
        lambda: kb.replace_source(store, "KB-0002", md("x.md", "x"), "u", backend=backend),
    ):
        with pytest.raises(UnknownSourceError):
            call()
    assert head(store.root) == before
    added = add_sources(store, [md("b.md", "出荷")], "u", backend=backend)
    assert [s.id for s in added.added] == ["KB-0003"]  # ids are never reused


def test_replace_failure_keeps_old_file(
    store: ProjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_sources(store, [md("a.md", "old")], "u", backend=keyword_backend())
    paths = kb.kb_paths(store)

    def fail(*args: object) -> bool:
        raise RuntimeError("no")

    monkeypatch.setattr(kb, "commit_paths", fail)
    with pytest.raises(KbCommitError):
        kb.replace_source(store, "KB-0001", md("a.txt", "new"), "u", backend=keyword_backend())
    assert sorted(p.name for p in paths.sources.iterdir()) == ["KB-0001.md"]
    assert paths.source_file("KB-0001", ".md").read_text() == "old"


def test_status_missing_stale_and_failed(store: ProjectStore) -> None:
    add_sources(
        store,
        [md("a.md", "a"), md("b.md", "b"), IncomingFile("c.pdf", b"%PDF-1.4 broken")],
        "u",
        backend=keyword_backend(),
    )
    paths = kb.kb_paths(store)
    paths.source_file("KB-0001", ".md").unlink()
    paths.source_file("KB-0002", ".md").write_text("changed")
    views = list_sources(store, backend=keyword_backend())
    assert [(v.status, v.reason is not None) for v in views] == [
        ("missing", False),
        ("stale", False),
        ("failed", True),
    ]
    # A different embedder makes every source stale (Requirement 5.13).
    assert {v.status for v in list_sources(store, backend=hash_backend())} >= {"stale"}


def test_reindex_refuses_missing_and_rebuilds(store: ProjectStore) -> None:
    add_sources(store, [md("a.md", "受注\n\n出荷")], "u", backend=keyword_backend())
    paths = kb.kb_paths(store)
    paths.source_file("KB-0001", ".md").rename(paths.sources / "moved")
    snapshot = {p: p.read_bytes() for p in paths.index.rglob("*") if p.is_file()}
    with pytest.raises(KbError, match="KB-0001"):
        reindex(store, backend=keyword_backend())
    assert {p: p.read_bytes() for p in paths.index.rglob("*") if p.is_file()} == snapshot
    (paths.sources / "moved").rename(paths.source_file("KB-0001", ".md"))
    outcome = reindex(store, backend=hash_backend())
    assert outcome.chunk_count == 2 and outcome.record.embedder == "hash-embedder"
    assert {v.status for v in list_sources(store, backend=hash_backend())} == {"indexed"}


def test_build_failure_keeps_old_generation(
    store: ProjectStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_sources(store, [md("a.md", "受注")], "u", backend=keyword_backend())
    paths = kb.kb_paths(store)
    generation = current_generation(paths)
    from masterba.knowledge import indexer

    def crash(*args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(indexer, "_index_source", crash)
    with pytest.raises(IndexBuildError, match="disk full"):
        reindex(store, backend=keyword_backend())
    assert current_generation(paths) == generation
    index = open_index(paths, keyword_backend())
    assert index.keyword.search("受注", 5, None) == ["KB-0001#chunk.1"]
    index.close()


def test_empty_reindex_and_record(store: ProjectStore) -> None:
    outcome = reindex(store, backend=keyword_backend())
    assert outcome.chunk_count == 0 and outcome.record.sources == {}
    assert outcome.notice and outcome.keyword_only
    record = kb.kb_paths(store).index / outcome.generation / "record.json"
    assert '"format_version": 1001' in record.read_text()


def test_info_exclude_fallback(store: ProjectStore) -> None:
    # The test repository has no .gitignore, so the patterns go to info/exclude.
    exclude = store.root.parent / ".git" / "info" / "exclude"
    add_sources(store, [md("a.md", "a")], "u", backend=keyword_backend())
    assert "/projects/PRJ-001/knowledge/sources/" in exclude.read_text()
    assert last_commit(store.root)[1] == [MANIFEST]
    add_sources(store, [md("b.md", "b")], "u", backend=keyword_backend())
    assert exclude.read_text().count("/projects/PRJ-001/knowledge/sources/") == 1


def test_an_add_killed_before_its_commit_does_not_block_the_next_add(store: ProjectStore) -> None:
    # Review finding: a source copied by an interrupted add kept its id taken forever.
    paths = kb.kb_paths(store)
    paths.sources.mkdir(parents=True)
    paths.source_file("KB-0001", ".md").write_text("orphan from a killed add")
    report = add_sources(store, [md("a.md", "受注")], "u", backend=keyword_backend())
    assert [s.id for s in report.added] == ["KB-0001"]
    assert paths.source_file("KB-0001", ".md").read_text() == "受注"


def test_a_replace_killed_before_its_commit_gets_its_old_file_back(store: ProjectStore) -> None:
    # Review finding: the only copy of the old bytes was deleted by the next mutation.
    add_sources(store, [md("a.md", "old"), md("b.md", "other")], "u", backend=keyword_backend())
    paths = kb.kb_paths(store)
    old = paths.source_file("KB-0001", ".md")
    backup = paths.sources / ".staging-KB-0001.md.old"
    old.rename(backup)  # state of a replace killed after moving the old file aside
    paths.source_file("KB-0001", ".txt").write_text("new, never committed")
    add_sources(store, [md("c.md", "third")], "u", backend=keyword_backend())
    assert old.read_text() == "old" and not backup.exists()
    assert not paths.source_file("KB-0001", ".txt").exists()
    assert [v.status for v in list_sources(store, backend=keyword_backend())][0] != "missing"


def test_a_committed_replace_drops_its_backup(store: ProjectStore) -> None:
    add_sources(store, [md("a.md", "old")], "u", backend=keyword_backend())
    kb.replace_source(store, "KB-0001", md("a.md", "new"), "u", backend=keyword_backend())
    paths = kb.kb_paths(store)
    stale = paths.sources / ".staging-KB-0001.md.old"
    stale.write_text("old")  # left behind by a crash after the commit
    add_sources(store, [md("b.md", "b")], "u", backend=keyword_backend())
    assert not stale.exists()
    assert paths.source_file("KB-0001", ".md").read_text() == "new"
