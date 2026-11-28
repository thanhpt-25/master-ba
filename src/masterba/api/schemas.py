"""Request bodies and shared patterns of the API (spec 08 section 3)."""

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from masterba.models import ReviewComment
from masterba.models.enums import DocLanguage, DrTrigger, PropagationMode
from masterba.models.ids import (
    COMPANY_ID_PATTERN,
    DOC_ID_PATTERN,
    DR_ID_PATTERN,
    PROJECT_ID_PATTERN,
    QUESTION_ID_PATTERN,
    RUN_ID_PATTERN,
    SOURCE_ID_PATTERN,
)

INTAKE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.(txt|md)$")
PROJECT_ID = re.compile(PROJECT_ID_PATTERN)
DOC_ID = re.compile(DOC_ID_PATTERN)
DR_ID = re.compile(DR_ID_PATTERN)
QUESTION_ID = re.compile(QUESTION_ID_PATTERN)
RUN_ID = re.compile(RUN_ID_PATTERN)
SOURCE_ID = re.compile(SOURCE_ID_PATTERN)
STAGES = ("brd", "srs", "basic", "detail")


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginBody(Body):
    name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class CreateProjectBody(Body):
    project_id: str = Field(pattern=PROJECT_ID_PATTERN)
    company_id: str = Field(default="default", pattern=COMPANY_ID_PATTERN)
    document_language: DocLanguage = DocLanguage.JA
    team_max_rounds: int = Field(default=3, ge=1, le=20)
    team_token_budget: int | None = Field(default=100_000, ge=1)
    review_gates: bool = True  # spec 15: on for new projects
    propagation_mode: PropagationMode = PropagationMode.MANUAL_GATE


class RejectBody(Body):
    comments: list[ReviewComment] = Field(min_length=1, max_length=50)


class RunStageBody(Body):
    intake: str | None = None
    reuse_intake: bool = False
    resume: str | None = Field(default=None, pattern=r"^RUN-\d{4}$")
    rounds: int | None = Field(default=None, ge=1, le=20)


class PropagationModeBody(Body):
    propagation_mode: PropagationMode


class GuardSettingsBody(Body):
    """Spec 30 section 2.3."""

    pii_masking: bool
    masking_terms: list[str] = Field(default_factory=list, max_length=200)


class ProjectBudgetBody(Body):
    team_token_budget: int | None = Field(ge=1)


class NewDrBody(Body):
    trigger: DrTrigger
    description: str = Field(min_length=1, max_length=5000)
    items: list[str] = Field(default_factory=list, max_length=100)


class FromRunBody(Body):
    run_id: str = Field(pattern=RUN_ID_PATTERN)


class DecisionBody(Body):
    decision: str = Field(min_length=1, max_length=5000)
    rationale: str | None = Field(default=None, max_length=5000)


class BatchPropagateBody(Body):
    """DRs to propagate in one job; empty means every approved DR (spec 07 section 5.2)."""

    dr_ids: list[str] = Field(default_factory=list, max_length=200)


class AnswerBody(Body):
    answer: str = Field(min_length=1, max_length=2000)
    source: str | None = Field(default=None, max_length=500)
    waive: bool = False


class SetColumnBody(Body):
    sheet: str = Field(min_length=1, max_length=64)
    col: str = Field(pattern=r"^[A-Z]{1,3}$")
    field: str | None = Field(default=None, max_length=40)


class LimitsBody(Body):
    """Token limits per usage window; null means no limit (spec 23 section 6)."""

    session: int | None = Field(default=None, ge=0)
    weekly: int | None = Field(default=None, ge=0)


class NewUserBody(Body):
    name: str = Field(min_length=1, max_length=40)
    role: str = Field(pattern=r"^(viewer|approver|admin)$")
    password: str = Field(min_length=1, max_length=200)


class UserChangeBody(Body):
    role: str | None = Field(default=None, pattern=r"^(viewer|approver|admin)$")
    password: str | None = Field(default=None, min_length=1, max_length=200)
    limits: LimitsBody | None = None  # sent as null: return to the default limits


class MemberBody(Body):
    name: str = Field(min_length=1, max_length=40)
    role: str = Field(pattern=r"^(viewer|approver)$")


class OwnerBody(Body):
    name: str = Field(min_length=1, max_length=40)


class PriceBody(Body):
    input: float = Field(ge=0, le=10_000)
    output: float = Field(ge=0, le=10_000)


class PricesBody(Body):
    """Prices per million tokens by model id (spec 24 section 4)."""

    currency: str = Field(default="USD", pattern=r"^[A-Z]{3}$")
    models: dict[str, PriceBody] = Field(default_factory=dict, max_length=50)


class VisibilityBody(Body):
    """Who may use a template set (spec 29 section 1.2)."""

    visibility: Literal["private", "shared", "public"]
    shared_with: list[str] = Field(default_factory=list, max_length=100)


class TitleBody(Body):
    title: str | None = Field(default=None, max_length=80)


class CloneBody(Body):
    target: str = Field(pattern=COMPANY_ID_PATTERN)


class ProjectTemplateBody(Body):
    set: str = Field(pattern=COMPANY_ID_PATTERN)
    accept_gaps: bool = False
