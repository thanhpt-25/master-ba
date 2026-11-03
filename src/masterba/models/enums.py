"""Enumerations shared across entities (specs/01-data-contracts.md section 2)."""

from enum import StrEnum


class DocType(StrEnum):
    BRD = "BRD"
    SRS = "SRS"
    BASIC_DESIGN = "BASIC_DESIGN"
    DETAIL_DESIGN = "DETAIL_DESIGN"
    TEST_IT = "TEST_IT"
    TEST_ST = "TEST_ST"
    TEST_UT = "TEST_UT"
    TEST_UAT = "TEST_UAT"


class Level(StrEnum):
    UT = "UT"
    IT = "IT"
    ST = "ST"
    UAT = "UAT"


class ItemStatus(StrEnum):
    ACTIVE = "active"
    REMOVED = "removed"


class ReqCategory(StrEnum):
    BUSINESS = "business"
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"


class DocStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class LinkType(StrEnum):
    REALIZES = "realizes"
    VERIFIES = "verifies"
    DERIVES_FROM = "derives_from"
    TESTS = "tests"
    IMPLEMENTS = "implements"


class DrTrigger(StrEnum):
    REQUIREMENT_CHANGE = "requirement_change"
    DESIGN_CHANGE = "design_change"
    DEFECT = "defect"
    CLARIFICATION = "clarification"
    KNOWLEDGE_CHANGE = "knowledge_change"


class DrStatus(StrEnum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    PROPAGATED = "propagated"
    CLOSED = "closed"


class TemplateSource(StrEnum):
    BASELINE = "baseline"
    CALIBRATED_FROM_SAMPLE = "calibrated_from_sample"


class DocLanguage(StrEnum):
    JA = "ja"
    EN = "en"


class PropagationMode(StrEnum):
    MANUAL_GATE = "manual_gate"
    AUTO_LOW_RISK = "auto_low_risk"


class Role(StrEnum):
    ADMIN = "admin"
    APPROVER = "approver"
    VIEWER = "viewer"


class TeamRunStatus(StrEnum):
    RUNNING = "running"
    DONE = "done"
    ESCALATED = "escalated"


class Scope(StrEnum):
    IN = "in"
    OUT = "out"


class SrsKind(StrEnum):
    FUNCTIONAL = "functional"
    NON_FUNCTIONAL = "non_functional"


class BasicDesignKind(StrEnum):
    FUNCTION = "function"
    SCREEN = "screen"
    INTERFACE = "interface"
    DATA_ENTITY = "data_entity"


class DetailDesignKind(StrEnum):
    MODULE = "module"
    PROCESSING_STEP = "processing_step"
    DB_TABLE = "db_table"
    API = "api"


class QuestionStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    WITHDRAWN = "withdrawn"


class QuestionOrigin(StrEnum):
    AGENT = "agent"
    QA_BLOCKER = "qa_blocker"
