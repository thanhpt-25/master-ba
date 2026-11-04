"""Review store functions (spec 01 item 26)."""

import datetime as dt
import json
import subprocess
from pathlib import Path

import pytest

from factories import make_brd, make_brd_item, make_document
from masterba.models import Review
from masterba.models.enums import DocStatus, DocType, ReviewDecision, ReviewStage
from masterba.trace_store import (
    DuplicateIdError,
    NotFoundError,
    ProjectStore,
    add_document,
    add_review,
    get_document,
    get_review,
    list_reviews,
    save_review,
    set_document_status,
)

AT = dt.datetime(2026, 11, 4, 3, 14, 29, tzinfo=dt.UTC)
BRD = "DOC-BRD-0001"


def stored_brd(store: ProjectStore) -> Path:
    add_document(store, make_document(DocType.BRD), make_brd(make_brd_item(BRD, 1)))
    return store.path / "json" / "brd" / f"{BRD}.v1.json"


def approval(review_id: str = "REV-0001") -> Review:
    return Review(
        id=review_id,
        stage=ReviewStage.BRD,
        documents=[{"doc_id": BRD, "version": 1}],  # type: ignore[list-item]
        decision=ReviewDecision.APPROVED,
        by="alice",
        at=AT,
    )


def last_commit(repo: Path) -> tuple[str, list[str]]:
    out = subprocess.run(
        ["git", "show", "--name-only", "--format=%s", "HEAD"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    return out[0], sorted(line for line in out[1:] if line)


def test_add_review_sets_the_status_in_the_same_commit(store: ProjectStore) -> None:
    path = stored_brd(store)
    content_before = json.loads(path.read_text("utf-8"))["content"]
    add_review(store, approval(), DocStatus.APPROVED)
    assert get_document(store, BRD)[0].status is DocStatus.APPROVED
    assert json.loads(path.read_text("utf-8"))["content"] == content_before
    subject, files = last_commit(store.root)
    assert subject == f"review(PRJ-001): approve brd ({BRD} v1)"
    assert files == [
        "projects/PRJ-001/json/brd/DOC-BRD-0001.v1.json",
        "projects/PRJ-001/reviews/REV-0001.json",
    ]
    assert get_review(store, "REV-0001") == approval()
    assert [r.id for r in list_reviews(store)] == ["REV-0001"]


def test_reviews_are_unique_and_must_exist(store: ProjectStore) -> None:
    stored_brd(store)
    add_review(store, approval(), None)
    with pytest.raises(DuplicateIdError):
        add_review(store, approval(), None)
    with pytest.raises(NotFoundError):
        get_review(store, "REV-0099")
    with pytest.raises(NotFoundError):
        save_review(store, approval("REV-0099"), "update")
    assert list_reviews(store)[0].id == "REV-0001"


def test_set_document_status_changes_only_the_status(store: ProjectStore) -> None:
    path = stored_brd(store)
    before = json.loads(path.read_text("utf-8"))
    set_document_status(store, BRD, 1, DocStatus.IN_REVIEW, "review(PRJ-001): open brd")
    after = json.loads(path.read_text("utf-8"))
    assert after["content"] == before["content"]
    assert after["document"] == {**before["document"], "status": "in_review"}
    assert last_commit(store.root)[0] == "review(PRJ-001): open brd"
    with pytest.raises(NotFoundError):
        set_document_status(store, BRD, 2, DocStatus.APPROVED, "x")
