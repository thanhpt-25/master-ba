"""Builders for contract objects used across tests."""

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
    DocStatus,
    DocType,
    ItemStatus,
    Level,
    ReqCategory,
    Scope,
    SrsKind,
)

PROJECT = "PRJ-001"


def make_config(project_id: str = PROJECT) -> ProjectConfig:
    return ProjectConfig(project_id=project_id, company_id="default")


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
