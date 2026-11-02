# Feature: local-rag, Property 25: Knowledge models round-trip through JSON
import datetime as dt

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import BaseModel, ValidationError

from masterba.models import (
    KbCitation,
    KbManifest,
    KbSource,
    Passage,
    ReindexRecord,
    SourceIndexState,
)

_ids = st.integers(1, 9999).map(lambda n: f"KB-{n:04d}")
_refs = st.builds(lambda s, n: f"{s}#chunk.{n}", _ids, st.integers(1, 10_000))
_times = st.datetimes(
    min_value=dt.datetime(2000, 1, 1), max_value=dt.datetime(2100, 1, 1), timezones=st.just(dt.UTC)
)
_sha = st.text("0123456789abcdef", min_size=64, max_size=64)
_text = st.text(max_size=40)


@st.composite
def _manifests(draw: st.DrawFn) -> KbManifest:
    ids = sorted(draw(st.sets(_ids, max_size=5)))
    sources = [
        KbSource(
            id=i,
            file_name=draw(st.text(min_size=1, max_size=20)),
            suffix=draw(st.sampled_from([".md", ".txt", ".xlsx", ".docx", ".pdf"])),
            sha256=draw(_sha),
            added_by=draw(st.text(min_size=1, max_size=10)),
            added_at=draw(_times),
            removed=draw(st.booleans()),
            removed_at=draw(st.none() | _times),
        )
        for i in ids
    ]
    return KbManifest(sources=sources)


_states = st.builds(
    SourceIndexState,
    sha256=_sha,
    status=st.sampled_from(["indexed", "failed"]),
    reason=st.none() | _text,
    chunks=st.integers(0, 1000),
)
_records = st.builds(
    ReindexRecord,
    format_version=st.integers(0, 10_000),
    embedder=st.none() | _text,
    built_at=_times,
    sources=st.dictionaries(_ids, _states, max_size=4),
)
_passages = st.builds(
    Passage,
    chunk_ref=_refs,
    text=_text,
    heading_path=st.lists(_text, max_size=3),
    sheet=st.none() | _text,
    rows=st.none() | st.tuples(st.integers(1, 100), st.integers(1, 100)),
    page=st.none() | st.integers(1, 100),
    score=st.floats(allow_nan=False, allow_infinity=False),
)
_citations = st.builds(
    KbCitation, chunk_ref=st.text(min_size=1, max_size=30), quote=st.none() | _text
)


@given(st.one_of(_manifests(), _records, _passages, _citations))
def test_knowledge_models_round_trip_and_are_frozen(model: BaseModel) -> None:
    again = type(model).model_validate(model.model_dump(mode="json"))
    assert again == model
    name = next(iter(type(model).model_fields))
    with pytest.raises(ValidationError):
        setattr(model, name, getattr(model, name))
