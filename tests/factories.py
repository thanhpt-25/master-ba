"""Builders for contract objects used across tests."""

from pathlib import Path

from masterba.agents import (
    BasicDesignDraft,
    BrdDraft,
    DesignAnswer,
    DesignQuestion,
    DetailDesignDraft,
    DraftDesignItem,
    DraftDetailItem,
    DraftExclusion,
    DraftRequirement,
    DraftSrsItem,
    DraftTestCase,
    OpenQuestion,
    QaIssue,
    QaReport,
    SrsDraft,
    TestDraft,
    UnitTestDraft,
)
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
    DetailDesignKind,
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


def make_config(
    project_id: str = PROJECT,
    language: DocLanguage = DocLanguage.EN,
    max_rounds: int = 3,
    token_budget: int | None = None,
) -> ProjectConfig:
    return ProjectConfig(
        project_id=project_id,
        company_id="default",
        document_language=language,
        team_max_rounds=max_rounds,
        team_token_budget=token_budget,
    )


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


def qa_pass() -> QaReport:
    return QaReport()


def qa_block(
    checklist_id: str = "BRD-01", ref: str | None = None, message: str = "Fix it."
) -> QaReport:
    return QaReport(
        issues=[QaIssue(checklist_id=checklist_id, severity="blocking", ref=ref, message=message)]
    )


def srs_item(
    kind: SrsKind, statement: str, derives_from: list[str], hint: str | None = None
) -> DraftSrsItem:
    return DraftSrsItem(
        kind=kind, statement=statement, acceptance_hint=hint, derives_from=derives_from
    )


def login_srs_draft() -> SrsDraft:
    """Covers the four in-scope requirements REQ-0001..0004 of the login BRD draft."""
    return SrsDraft(
        items=[
            srs_item(
                SrsKind.FUNCTIONAL,
                "The system shall let a registered customer sign in with email and password.",
                ["REQ-0001"],
                "Sign in with valid credentials and see the portal home.",
            ),
            srs_item(
                SrsKind.FUNCTIONAL,
                "The system shall let a customer reset a forgotten password by email.",
                ["REQ-0002"],
                "Request a reset mail and set a new password with the link.",
            ),
            srs_item(
                SrsKind.NON_FUNCTIONAL,
                "The portal shall be available 24 hours a day, 365 days a year.",
                ["REQ-0003"],
            ),
            srs_item(
                SrsKind.FUNCTIONAL,
                "The system shall show a signed-in customer their order history.",
                ["REQ-0004"],
                "Sign in and open the order history page.",
            ),
        ]
    )


def incomplete_srs_draft() -> SrsDraft:
    """Leaves REQ-0003 and REQ-0004 uncovered."""
    return SrsDraft(items=login_srs_draft().items[:2])


SRS_DOC = "DOC-SRS-0001"
DESIGN_DOC = "DOC-BASIC_DESIGN-0001"


def srs_ref(n: int) -> str:
    return f"{SRS_DOC}#item.{n}"


def design_ref(n: int) -> str:
    return f"{DESIGN_DOC}#item.{n}"


def design_item(
    kind: BasicDesignKind, name: str, description: str, *realizes: int
) -> DraftDesignItem:
    return DraftDesignItem(
        kind=kind,
        name=name,
        description=description,
        realizes=[srs_ref(n) for n in realizes],
    )


def login_design_draft() -> BasicDesignDraft:
    """Five design items realising the four SRS items of the login demo."""
    return BasicDesignDraft(
        items=[
            design_item(
                BasicDesignKind.SCREEN,
                "Login screen",
                "Form with email and password fields and a submit button.",
                1,
            ),
            design_item(
                BasicDesignKind.FUNCTION,
                "Authentication",
                "Checks the email and password of a registered customer and opens a session.",
                1,
            ),
            design_item(
                BasicDesignKind.FUNCTION,
                "Password reset",
                "Sends a reset link by email and stores the new password.",
                2,
            ),
            design_item(
                BasicDesignKind.FUNCTION,
                "Availability",
                "The portal runs around the clock; planned downtime is not allowed.",
                3,
            ),
            design_item(
                BasicDesignKind.FUNCTION,
                "Order history",
                "Lists the signed-in customer's past orders, newest first.",
                4,
            ),
        ]
    )


def login_design_answered() -> BasicDesignDraft:
    """The design after the tester asked about the password limits (item 2)."""
    draft = login_design_draft()
    items = list(draft.items)
    items[1] = items[1].model_copy(
        update={"description": items[1].description + " Passwords are 8 to 64 characters long."}
    )
    answer = DesignAnswer(ref=design_ref(2), text="Passwords are 8 to 64 characters long.")
    return BasicDesignDraft(items=items, answers=[answer])


def tcase(*verifies: str, expected: str = "The result is shown.") -> DraftTestCase:
    return DraftTestCase(
        precondition="A registered customer exists.",
        input="valid data",
        steps=["Open the page", "Submit the form"],
        expected=expected,
        verifies=list(verifies),
    )


def login_test_draft() -> TestDraft:
    """One IT case per design item and one ST case per SRS item."""
    return TestDraft(
        it_cases=[tcase(design_ref(n)) for n in range(1, 6)],
        st_cases=[tcase(srs_ref(n)) for n in range(1, 5)],
    )


def login_test_draft_with_question() -> TestDraft:
    question = DesignQuestion(
        ref=design_ref(2), question="What are the minimum and maximum password lengths?"
    )
    return login_test_draft().model_copy(update={"questions": [question]})


def login_test_draft_with_exclusions() -> TestDraft:
    """Availability has no ST case (excluded) and the availability design item no IT case."""
    full = login_test_draft()
    return TestDraft(
        it_cases=[c for c in full.it_cases if design_ref(4) not in c.verifies],
        st_cases=[c for c in full.st_cases if srs_ref(3) not in c.verifies],
        exclusions=[
            DraftExclusion(item_ref=design_ref(4), reason="Needs a production monitoring setup."),
            DraftExclusion(item_ref=srs_ref(3), reason="Cannot be shown in a test period."),
        ],
    )


DETAIL_DOC = "DOC-DETAIL_DESIGN-0001"


def detail_ref(n: int) -> str:
    return f"{DETAIL_DOC}#item.{n}"


def detail_item(kind: DetailDesignKind, name: str, spec: str, *refines: int) -> DraftDetailItem:
    return DraftDetailItem(
        kind=kind, name=name, spec=spec, refines=[design_ref(n) for n in refines]
    )


def login_detail_draft() -> DetailDesignDraft:
    """Five detail items refining the five design items of the login demo."""
    return DetailDesignDraft(
        items=[
            detail_item(
                DetailDesignKind.MODULE,
                "AuthModule",
                "Operation authenticate(email, password) returns a session or an error.",
                1,
                2,
            ),
            detail_item(
                DetailDesignKind.PROCESSING_STEP,
                "Sign-in flow",
                "1. Receive input. 2. Validate format. 3. Look up the customer. 4. Check password.",
                2,
            ),
            detail_item(
                DetailDesignKind.MODULE,
                "PasswordResetModule",
                "Operation requestReset(email) sends a link; operation setPassword(token, value).",
                3,
            ),
            detail_item(
                DetailDesignKind.MODULE,
                "AvailabilityPolicy",
                "The service has no planned downtime window.",
                4,
            ),
            detail_item(
                DetailDesignKind.API,
                "OrderHistoryApi",
                "GET orders returns the signed-in customer's orders, newest first.",
                5,
            ),
        ]
    )


def login_detail_answered() -> DetailDesignDraft:
    """The detail design after the tester asked about the sign-in flow (item 2)."""
    draft = login_detail_draft()
    items = list(draft.items)
    items[1] = items[1].model_copy(
        update={
            "spec": items[1].spec + " 5. After 5 failed attempts the account locks for 15 minutes."
        }
    )
    answer = DesignAnswer(
        ref=detail_ref(2), text="Five failed attempts lock the account for 15 minutes."
    )
    return DetailDesignDraft(items=items, answers=[answer])


def login_unit_draft() -> UnitTestDraft:
    return UnitTestDraft(ut_cases=[tcase(detail_ref(n)) for n in range(1, 6)])


def login_unit_draft_with_question() -> UnitTestDraft:
    question = DesignQuestion(
        ref=detail_ref(2), question="How many failed attempts lock the account?"
    )
    return login_unit_draft().model_copy(update={"questions": [question]})


def login_unit_draft_with_exclusion() -> UnitTestDraft:
    full = login_unit_draft()
    return UnitTestDraft(
        ut_cases=[c for c in full.ut_cases if detail_ref(4) not in c.verifies],
        exclusions=[
            DraftExclusion(item_ref=detail_ref(4), reason="A policy, not executable code.")
        ],
    )
