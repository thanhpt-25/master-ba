# Feature: local-rag, Property 5: Status follows the precedence rule
import datetime as dt
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from hypothesis import given
from hypothesis import strategies as st

from masterba.knowledge.indexer import IndexIdentity
from masterba.knowledge.paths import KbPaths
from masterba.knowledge.store import source_status
from masterba.models import KbSource, ReindexRecord, SourceIndexState

_SHA = hashlib.sha256(b"content").hexdigest()
_OTHER = "f" * 64
EXPECTED = IndexIdentity(1001, "m")


@given(
    present=st.booleans(),
    file_matches=st.booleans(),
    has_record=st.booleans(),
    has_entry=st.booleans(),
    entry_sha_matches=st.booleans(),
    format_matches=st.booleans(),
    embedder_matches=st.booleans(),
    result=st.sampled_from(["indexed", "failed"]),
)
def test_status_precedence(
    present: bool,
    file_matches: bool,
    has_record: bool,
    has_entry: bool,
    entry_sha_matches: bool,
    format_matches: bool,
    embedder_matches: bool,
    result: Literal["indexed", "failed"],
) -> None:
    entry = KbSource(
        id="KB-0001",
        file_name="a.md",
        suffix=".md",
        sha256=_SHA,
        added_by="u",
        added_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )
    reason = "no text found" if result == "failed" else None
    state = SourceIndexState(
        sha256=_SHA if entry_sha_matches else _OTHER,
        status=result,
        reason=reason,
        chunks=1,
    )
    record = (
        ReindexRecord(
            format_version=1001 if format_matches else 1002,
            embedder="m" if embedder_matches else None,
            built_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            sources={"KB-0001": state} if has_entry else {},
        )
        if has_record
        else None
    )
    with TemporaryDirectory() as tmp:
        paths = KbPaths(Path(tmp))
        if present:
            paths.sources.mkdir()
            paths.source_file("KB-0001", ".md").write_bytes(b"content" if file_matches else b"x")
        view = source_status(paths, entry, record, EXPECTED)
    if not present:
        assert view.status == "missing"
    elif not (
        file_matches
        and has_record
        and has_entry
        and entry_sha_matches
        and format_matches
        and embedder_matches
    ):
        assert view.status == "stale"
    else:
        assert (view.status, view.reason) == (result, reason)
