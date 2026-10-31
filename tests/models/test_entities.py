import datetime as dt
from typing import Any

import pytest
from pydantic import ValidationError

from factories import make_config, make_document, make_requirement
from masterba.models import DecisionRecord, Document, ProjectConfig, RequirementItem, TraceLink
from masterba.models.enums import (
    DocLanguage,
    DocStatus,
    DocType,
    DrStatus,
    DrTrigger,
    LinkType,
    PropagationMode,
)


def test_unknown_field_is_rejected() -> None:
    data = {**make_document(DocType.BRD).model_dump(), "extra": 1}
    with pytest.raises(ValidationError):
        Document.model_validate(data)


def test_models_are_frozen() -> None:
    req = make_requirement()
    with pytest.raises(ValidationError):
        req.text = "changed"


def test_document_type_must_match_id() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        Document(
            id="DOC-SRS-0001",
            type=DocType.BRD,
            version=1,
            status=DocStatus.DRAFT,
            template_id="default/v1",
            content_ref="json/srs/DOC-SRS-0001.v1.json",
            project_id="PRJ-001",
        )


def test_document_content_ref_must_match_version() -> None:
    data = {**make_document(DocType.BRD, version=2).model_dump(), "content_ref": "x.v1.json"}
    with pytest.raises(ValidationError, match="content_ref"):
        Document.model_validate(data)


def test_requirement_cannot_be_its_own_parent() -> None:
    data = {**make_requirement().model_dump(), "parent_id": "REQ-0001"}
    with pytest.raises(ValidationError, match="parent_id"):
        RequirementItem.model_validate(data)


def test_trace_link_ends_must_differ() -> None:
    with pytest.raises(ValidationError):
        TraceLink(from_id="REQ-0001", to_id="REQ-0001", link_type=LinkType.REALIZES)


def test_trace_link_rejects_non_traceable_ids() -> None:
    with pytest.raises(ValidationError):
        TraceLink(from_id="DR-0001", to_id="REQ-0001", link_type=LinkType.REALIZES)


def _dr(**overrides: Any) -> DecisionRecord:
    base: dict[str, Any] = {
        "id": "DR-0007",
        "date": dt.date(2026, 10, 31),
        "trigger": DrTrigger.REQUIREMENT_CHANGE,
        "description": "Customer adds SSO.",
        "impacted_items": ["REQ-0001"],
        "affected_documents": ["DOC-SRS-0001"],
        "status": DrStatus.PROPOSED,
    }
    return DecisionRecord.model_validate({**base, **overrides})


def test_proposed_dr_needs_no_approver() -> None:
    assert _dr().approver is None


@pytest.mark.parametrize("status", [DrStatus.APPROVED, DrStatus.PROPAGATED, DrStatus.CLOSED])
def test_dr_past_proposed_requires_approver_and_decision(status: DrStatus) -> None:
    with pytest.raises(ValidationError, match="approver and decision"):
        _dr(status=status)
    ok = _dr(status=status, approver="pm@example.com", decision="Accepted")
    assert ok.status is status


def test_project_config_defaults() -> None:
    cfg = make_config()
    assert cfg.propagation_mode is PropagationMode.MANUAL_GATE
    assert cfg.team_max_rounds == 3
    assert cfg.team_token_budget is None


def test_project_config_rejects_zero_rounds() -> None:
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(
            {"project_id": "PRJ-001", "company_id": "default", "team_max_rounds": 0}
        )


def test_project_config_without_language_loads_as_japanese() -> None:
    data = make_config().model_dump(mode="json")
    del data["document_language"]
    assert ProjectConfig.model_validate(data).document_language is DocLanguage.JA


def test_a_stage_round_limit_overrides_the_default() -> None:
    cfg = ProjectConfig.model_validate(
        {
            "project_id": "PRJ-001",
            "company_id": "default",
            "team_max_rounds_by_stage": {"BASIC_DESIGN": 6},
        }
    )
    assert cfg.max_rounds_for(DocType.BASIC_DESIGN) == 6
    assert cfg.max_rounds_for(DocType.SRS) == 3
    with pytest.raises(ValidationError):
        ProjectConfig.model_validate(
            {"project_id": "PRJ-001", "company_id": "d", "team_max_rounds_by_stage": {"SRS": 0}}
        )
