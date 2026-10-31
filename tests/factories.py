"""Builders for contract objects used across tests."""

from pathlib import Path

from masterba.agents import BrdDraft, DraftRequirement, OpenQuestion
from masterba.models import (
    BasicDesignContent,
    BasicDesignItem,
    BrdContent,
    BrdItem,
    Document,
    ProjectConfig,
    RequirementItem,
    SrsContent,
    SrsItem,
    TestCaseItem,
    TestSpecContent,
)
from masterba.models.enums import (
    BasicDesignKind,
    DocLanguage,
    DocStatus,
    DocType,
    ItemStatus,
    Level,
    ReqCategory,
    Scope,
    SrsKind,
)

PROJECT = "PRJ-001"


def make_config(project_id: str = PROJECT, language: DocLanguage = DocLanguage.EN) -> ProjectConfig:
    return ProjectConfig(project_id=project_id, company_id="default", document_language=language)


def make_requirement(n: int = 1, text: str = "Users can log in") -> RequirementItem:
    return RequirementItem(
        id=f"REQ-{n:04d}",
        source_ref="intake/mail-1.txt",
        text=text,
        category=ReqCategory.FUNCTIONAL,
    )


def doc_id(doc_type: DocType, n: int = 1) -> str:
    return f"DOC-{doc_type.value}-{n:04d}"


def make_document(doc_type: DocType, n: int = 1, version: int = 1) -> Document:
    did = doc_id(doc_type, n)
    return Document(
        id=did,
        type=doc_type,
        version=version,
        status=DocStatus.DRAFT,
        template_id="default/v1",
        content_ref=f"json/{doc_type.value.lower()}/{did}.v{version}.json",
        project_id=PROJECT,
    )


def make_brd_item(
    doc: str,
    i: int,
    req: str = "REQ-0001",
    description: str = "The system lets registered users sign in with email.",
    status: ItemStatus = ItemStatus.ACTIVE,
) -> BrdItem:
    return BrdItem(
        item_id=f"{doc}#item.{i}",
        status=status,
        requirement_id=req,
        title=f"Requirement {i}",
        description=description,
        scope=Scope.IN,
        source_ref="intake/mail-1.txt",
    )


def make_brd(*items: BrdItem) -> BrdContent:
    return BrdContent(items=list(items))


def make_srs_item(
    doc: str,
    i: int,
    req: str = "REQ-0001",
    statement: str = "The system shall authenticate users by email and password.",
    status: ItemStatus = ItemStatus.ACTIVE,
) -> SrsItem:
    return SrsItem(
        item_id=f"{doc}#item.{i}",
        status=status,
        requirement_id=req,
        kind=SrsKind.FUNCTIONAL,
        statement=statement,
        derives_from=[req],
    )


def make_srs(*items: SrsItem) -> SrsContent:
    return SrsContent(items=list(items))


def make_basic_item(doc: str, i: int, name: str = "Login screen") -> BasicDesignItem:
    return BasicDesignItem(
        item_id=f"{doc}#item.{i}",
        kind=BasicDesignKind.SCREEN,
        name=name,
        description="Email and password form with a submit button.",
    )


def make_basic(*items: BasicDesignItem) -> BasicDesignContent:
    return BasicDesignContent(items=list(items))


def make_test_item(doc: str, i: int, tc: str, level: Level) -> TestCaseItem:
    return TestCaseItem(
        item_id=f"{doc}#item.{i}",
        test_id=tc,
        level=level,
        precondition="A registered user exists.",
        input="valid email and password",
        steps=["Open the login screen", "Submit the form"],
        expected="The user lands on the dashboard.",
    )


def make_test_spec(*items: TestCaseItem) -> TestSpecContent:
    return TestSpecContent(items=list(items))


INTAKE_DIR = Path(__file__).parent / "fixtures" / "intake"
FUNCTIONAL, NON_FUNCTIONAL, BUSINESS = (
    ReqCategory.FUNCTIONAL,
    ReqCategory.NON_FUNCTIONAL,
    ReqCategory.BUSINESS,
)


def intake_path(name: str) -> Path:
    return INTAKE_DIR / name


def draft_req(
    title: str,
    category: ReqCategory,
    line: int,
    quote: str,
    scope: Scope = Scope.IN,
    end: int | None = None,
    description: str | None = None,
) -> DraftRequirement:
    return DraftRequirement(
        title=title,
        description=description or f"{title}: {quote}",
        category=category,
        scope=scope,
        start_line=line,
        end_line=end or line,
        evidence_quote=quote,
    )


DRAFTS: dict[str, BrdDraft] = {
    "login_system.txt": BrdDraft(
        requirements=[
            draft_req(
                "Customer sign-in",
                FUNCTIONAL,
                3,
                "registered customers can sign in with their email address and a password",
            ),
            draft_req("Password reset", FUNCTIONAL, 4, "must be able to reset it by email"),
            draft_req(
                "Availability", NON_FUNCTIONAL, 5, "available 24 hours a day, 365 days a year"
            ),
            draft_req("Order history", FUNCTIONAL, 6, "see their order history after signing in"),
            draft_req(
                "Account administration",
                BUSINESS,
                7,
                "Staff will manage the customer accounts through the existing admin tool",
                scope=Scope.OUT,
            ),
        ],
        open_questions=[
            OpenQuestion(question="What response time counts as fast?", start_line=8, end_line=8)
        ],
    ),
    "leave_management.txt": BrdDraft(
        requirements=[
            draft_req(
                "Leave request approval",
                FUNCTIONAL,
                2,
                "Employees submit leave requests in the system",
            ),
            draft_req(
                "Remaining leave display",
                FUNCTIONAL,
                3,
                "remaining paid leave days must be shown to the employee before submitting",
            ),
            draft_req(
                "Payroll integration",
                BUSINESS,
                4,
                "Payroll integration is out of scope for this phase",
                scope=Scope.OUT,
            ),
            draft_req("Approval time limit", NON_FUNCTIONAL, 5, "completed within 3 business days"),
        ],
    ),
    "inventory_mixed_ja.txt": BrdDraft(
        requirements=[
            draft_req(
                "新在庫システム",
                BUSINESS,
                2,
                "Our warehouse needs a new inventory system",
                description="倉庫に新しい在庫管理システムが必要である。",
            ),
            draft_req(
                "在庫数のリアルタイム確認",
                FUNCTIONAL,
                3,
                "倉庫ごとの在庫数をリアルタイムで確認できること",
                description="倉庫ごとの在庫数をリアルタイムで確認できること。",
            ),
            draft_req(
                "安全在庫アラート",
                FUNCTIONAL,
                4,
                "Stock below the safety level must trigger an alert to the purchasing team",
                description="在庫が安全水準を下回ったら購買チームへアラートを出すこと。",
            ),
        ],
        open_questions=[
            OpenQuestion(question="一括発注の締め処理の詳細は？", start_line=5, end_line=5)
        ],
    ),
}


def draft_for(name: str) -> BrdDraft:
    return DRAFTS[name]


def bad_draft() -> BrdDraft:
    """A draft whose quote is not in the cited line."""
    return BrdDraft(
        requirements=[draft_req("Invented", FUNCTIONAL, 3, "the portal shall read minds")]
    )
