"""Core entities (specs/01-data-contracts.md section 2)."""

import datetime as dt
from typing import Annotated, Any, Self

from pydantic import Field, model_validator

from masterba.models.base import FrozenModel
from masterba.models.enums import (
    DocLanguage,
    DocStatus,
    DocType,
    DrStatus,
    DrTrigger,
    ItemStatus,
    LinkType,
    PropagationMode,
    ReqCategory,
    Role,
    TeamRunStatus,
    TemplateSource,
)
from masterba.models.ids import (
    DocId,
    DrId,
    NodeId,
    ProjectId,
    ReqId,
    ReqOrItemRef,
    RunId,
    TeamTrigger,
    doc_type_of,
)


class RequirementItem(FrozenModel):
    id: ReqId
    source_ref: str = Field(min_length=1)
    text: str = Field(min_length=1)
    category: ReqCategory
    parent_id: ReqId | None = None
    status: ItemStatus = ItemStatus.ACTIVE

    @model_validator(mode="after")
    def _no_self_parent(self) -> Self:
        if self.parent_id == self.id:
            raise ValueError("parent_id must differ from id")
        return self


class Document(FrozenModel):
    id: DocId
    type: DocType
    version: int = Field(ge=1)
    status: DocStatus
    template_id: str = Field(min_length=1)
    content_ref: str
    render_ref: str | None = None
    project_id: ProjectId

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if doc_type_of(self.id) != self.type.value:
            raise ValueError(f"type {self.type.value} does not match id {self.id}")
        if not self.content_ref.endswith(f"{self.id}.v{self.version}.json"):
            raise ValueError("content_ref must end with <DOC_ID>.v<version>.json")
        return self


class TraceLink(FrozenModel):
    """Directed from the upstream artifact to the downstream one."""

    from_id: NodeId
    to_id: NodeId
    link_type: LinkType

    @model_validator(mode="after")
    def _distinct_ends(self) -> Self:
        if self.from_id == self.to_id:
            raise ValueError("from_id and to_id must differ")
        return self


class DecisionRecord(FrozenModel):
    id: DrId
    date: dt.date
    trigger: DrTrigger
    description: str = Field(min_length=1)
    decision: str | None = None
    rationale: str | None = None
    impacted_items: list[ReqOrItemRef]
    affected_documents: list[DocId]
    status: DrStatus
    approver: str | None = None

    @model_validator(mode="after")
    def _approval_fields(self) -> Self:
        if self.status is not DrStatus.PROPOSED and not (self.approver and self.decision):
            raise ValueError("approver and decision are required once a DR leaves 'proposed'")
        return self


class TemplateDefinition(FrozenModel):
    company_id: str = Field(min_length=1)
    doc_type: DocType
    source: TemplateSource
    sheet_map: dict[str, Any]
    cell_bindings: dict[str, Any]
    validation_rules: list[dict[str, Any]]


class ProjectConfig(FrozenModel):
    project_id: ProjectId
    company_id: str = Field(min_length=1)
    document_language: DocLanguage = DocLanguage.JA
    propagation_mode: PropagationMode = PropagationMode.MANUAL_GATE
    team_max_rounds: int = Field(default=3, ge=1)
    team_max_rounds_by_stage: dict[DocType, Annotated[int, Field(ge=1)]] = Field(
        default_factory=dict
    )
    team_token_budget: int | None = Field(default=None, ge=1)
    dashboard_roles: list[Role] = Field(
        default_factory=lambda: [Role.ADMIN, Role.APPROVER, Role.VIEWER]
    )

    def max_rounds_for(self, stage: DocType) -> int:
        """The round limit of one stage: its own entry, else `team_max_rounds` (spec 11 2.1)."""
        return self.team_max_rounds_by_stage.get(stage, self.team_max_rounds)


class TeamRun(FrozenModel):
    run_id: RunId
    stage: DocType
    trigger: TeamTrigger
    status: TeamRunStatus
    rounds: int = Field(ge=0)
    issues_raised: int = Field(ge=0)
    issues_resolved: int = Field(ge=0)
    escalations: list[str] = Field(default_factory=list)
    tokens_used: int | None = Field(default=None, ge=0)
    customer_questions: list[str] = Field(default_factory=list)
    resumed: int = Field(default=0, ge=0)
