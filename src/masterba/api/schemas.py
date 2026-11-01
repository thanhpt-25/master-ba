"""Request bodies and shared patterns of the API (spec 08 section 3)."""

import re

from pydantic import BaseModel, ConfigDict, Field

from masterba.models.enums import DocLanguage, DrTrigger
from masterba.models.ids import (
    DOC_ID_PATTERN,
    DR_ID_PATTERN,
    PROJECT_ID_PATTERN,
    QUESTION_ID_PATTERN,
    RUN_ID_PATTERN,
)

INTAKE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}\.(txt|md)$")
PROJECT_ID = re.compile(PROJECT_ID_PATTERN)
DOC_ID = re.compile(DOC_ID_PATTERN)
DR_ID = re.compile(DR_ID_PATTERN)
QUESTION_ID = re.compile(QUESTION_ID_PATTERN)
RUN_ID = re.compile(RUN_ID_PATTERN)
STAGES = ("brd", "srs", "basic", "detail")


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class LoginBody(Body):
    name: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=1, max_length=200)


class CreateProjectBody(Body):
    project_id: str = Field(pattern=PROJECT_ID_PATTERN)
    company_id: str = Field(default="default", min_length=1, max_length=40)
    document_language: DocLanguage = DocLanguage.JA
    team_max_rounds: int = Field(default=3, ge=1, le=20)
    team_token_budget: int | None = Field(default=None, ge=1)


class RunStageBody(Body):
    intake: str | None = None
    reuse_intake: bool = False
    resume: str | None = Field(default=None, pattern=r"^RUN-\d{4}$")
    rounds: int | None = Field(default=None, ge=1, le=20)


class NewDrBody(Body):
    trigger: DrTrigger
    description: str = Field(min_length=1, max_length=5000)
    items: list[str] = Field(default_factory=list, max_length=100)


class FromRunBody(Body):
    run_id: str = Field(pattern=RUN_ID_PATTERN)


class DecisionBody(Body):
    decision: str = Field(min_length=1, max_length=5000)
    rationale: str | None = Field(default=None, max_length=5000)


class AnswerBody(Body):
    answer: str = Field(min_length=1, max_length=2000)
    source: str | None = Field(default=None, max_length=500)


class SetColumnBody(Body):
    sheet: str = Field(min_length=1, max_length=64)
    col: str = Field(pattern=r"^[A-Z]{1,3}$")
    field: str | None = Field(default=None, max_length=40)
