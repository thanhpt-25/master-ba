import datetime as dt
from typing import Any

import pytest
from pydantic import ValidationError

from masterba.models import KbManifest, KbSource, ReindexRecord, SourceIndexState


def _source(source_id: str = "KB-0001", **overrides: Any) -> KbSource:
    fields: dict[str, Any] = {
        "id": source_id,
        "file_name": "用語集.xlsx",
        "suffix": ".xlsx",
        "sha256": "0" * 64,
        "added_by": "tanaka",
        "added_at": dt.datetime(2026, 11, 2, 9, 14, 5, tzinfo=dt.UTC),
    }
    fields.update(overrides)
    return KbSource(**fields)


def test_timestamps_are_utc_seconds_and_serialised_with_z() -> None:
    tokyo = dt.timezone(dt.timedelta(hours=9))
    source = _source(added_at=dt.datetime(2026, 11, 2, 18, 14, 5, 123456, tzinfo=tokyo))
    assert source.added_at == dt.datetime(2026, 11, 2, 9, 14, 5, tzinfo=dt.UTC)
    assert '"added_at":"2026-11-02T09:14:05Z"' in source.model_dump_json()
    assert KbSource.model_validate_json(source.model_dump_json()) == source


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="time zone"):
        _source(added_at=dt.datetime(2026, 11, 2, 9, 14, 5))


def test_manifest_requires_ascending_unique_ids() -> None:
    assert KbManifest(sources=[_source("KB-0001"), _source("KB-0002")]).format == 1
    with pytest.raises(ValidationError, match="unique"):
        KbManifest(sources=[_source("KB-0001"), _source("KB-0001")])
    with pytest.raises(ValidationError, match="ascending"):
        KbManifest(sources=[_source("KB-0002"), _source("KB-0001")])


def test_reindex_record_round_trips() -> None:
    record = ReindexRecord(
        format_version=1001,
        embedder=None,
        built_at=dt.datetime(2026, 11, 2, 9, 14, 5, tzinfo=dt.UTC),
        sources={"KB-0001": SourceIndexState(sha256="0" * 64, status="indexed", chunks=3)},
    )
    assert ReindexRecord.model_validate_json(record.model_dump_json()) == record
