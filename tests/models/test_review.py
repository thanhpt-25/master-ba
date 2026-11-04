"""Review records (spec 15 section 4)."""

import datetime as dt
from typing import Any

import pytest
from pydantic import ValidationError

from masterba.models import ProjectConfig, Review, ReviewComment
from masterba.models.enums import ReviewDecision, ReviewStage

AT = dt.datetime(2026, 11, 4, 3, 14, 29, tzinfo=dt.UTC)


def review(**overrides: Any) -> Review:
    fields: dict[str, Any] = {
        "id": "REV-0001",
        "stage": ReviewStage.SRS,
        "documents": [{"doc_id": "DOC-SRS-0001", "version": 1}],
        "decision": ReviewDecision.APPROVED,
        "by": "alice",
        "at": AT,
    }
    fields.update(overrides)
    return Review.model_validate(fields)


def test_an_approval_round_trips_with_a_utc_timestamp() -> None:
    approved = review(open_questions=["Q-0003"])
    assert '"at":"2026-11-04T03:14:29Z"' in approved.model_dump_json()
    assert Review.model_validate_json(approved.model_dump_json()) == approved


def test_a_rejection_needs_comments_and_an_approval_has_none() -> None:
    comment = {"ref": "DOC-SRS-0001#item.4", "text": "Split this obligation."}
    rejected = review(decision=ReviewDecision.REJECTED, comments=[comment], dr_id="DR-0002")
    assert rejected.comments[0].ref == "DOC-SRS-0001#item.4"
    with pytest.raises(ValidationError, match="needs comments"):
        review(decision=ReviewDecision.REJECTED)
    with pytest.raises(ValidationError, match="needs comments"):
        review(comments=[comment])
    with pytest.raises(ValidationError, match="no dr_id"):
        review(dr_id="DR-0002")


@pytest.mark.parametrize("text", ["", "   ", "x" * 2001, "bell\x07"])
def test_comment_text_is_checked(text: str) -> None:
    with pytest.raises(ValidationError):
        ReviewComment(text=text)


def test_bad_ids_are_refused() -> None:
    with pytest.raises(ValidationError):
        review(id="REV-1")
    with pytest.raises(ValidationError):
        review(documents=[])


def test_an_old_project_config_loads_with_gates_off() -> None:
    config = ProjectConfig.model_validate({"project_id": "PRJ-001", "company_id": "default"})
    assert config.review_gates is False
