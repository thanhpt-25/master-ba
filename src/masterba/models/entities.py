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
    QuestionOrigin,
    QuestionStatus,
    ReqCategory,
    Role,
    TeamRunStatus,
    TemplateSource,
)
from masterba.models.ids import (
    COMPANY_ID_PATTERN,
    DocId,
    DrId,
    NodeId,
    ProjectId,
    QuestionId,
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


class QuestionDraft(FrozenModel):
    """A question an agent raised, before it is recorded in the ledger (spec 13 section 3)."""

    origin: QuestionOrigin = QuestionOrigin.AGENT
    refs: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)


class Question(FrozenModel):
    """A point only the customer can settle (specs/13-customer-questions.md section 2)."""

    id: QuestionId
    origin: QuestionOrigin
    stage: DocType
    run_id: RunId
    refs: list[str] = Field(default_factory=list)
    text: str = Field(min_length=1)
    status: QuestionStatus
    asked_on: dt.date
    answer: str | None = None
    answered_by: str | None = None
    answered_on: dt.date | None = None
    dr_id: DrId | None = None
    source: str | None = None

    @model_validator(mode="after")
    def _answer_fields(self) -> Self:
        given = [self.answer, self.answered_by, self.answered_on, self.dr_id]
        answered = self.status is QuestionStatus.ANSWERED
        if answered and not all(given):
            raise ValueError("an answered question needs answer, answered_by, answered_on, dr_id")
        if not answered and any(given):
            raise ValueError("only an answered question has answer fields")
        if self.source and not answered:
            raise ValueError("only an answered question has a source")
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
    company_id: str = Field(pattern=COMPANY_ID_PATTERN)
    document_language: DocLanguage = DocLanguage.JA
    propagation_mode: PropagationMode = PropagationMode.MANUAL_GATE
    team_max_rounds: int = Field(default=3, ge=1)
    team_max_rounds_by_stage: dict[DocType, Annotated[int, Field(ge=1)]] = Field(
        default_factory=dict
    )
    team_token_budget: int | None = Field(default=100_000, ge=1)
    dashboard_roles: list[Role] = Field(
        default_factory=lambda: [Role.ADMIN, Role.APPROVER, Role.VIEWER]
    )
    # Spec 15: false for project.json files written before review gates, so they run as before;
    # init-project and the dashboard write true unless asked not to.
    review_gates: bool = False

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
    token_budget: int | None = Field(default=None, ge=1)
    customer_questions: list[str] = Field(default_factory=list)
    resumed: int = Field(default=0, ge=0)
