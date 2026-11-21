"""Content payloads, one per document family (specs/01-data-contracts.md section 2.1)."""

from collections.abc import Sequence

from pydantic import Field

from masterba.models.base import FrozenModel
from masterba.models.enums import (
    BasicDesignKind,
    DetailDesignKind,
    DocType,
    ItemStatus,
    Level,
    Scope,
    SectionKey,
    SrsKind,
)
from masterba.models.ids import ItemRef, ReqId, ReqOrItemRef, TcId
from masterba.models.knowledge import KbCitation


class PayloadItem(FrozenModel):
    item_id: ItemRef
    status: ItemStatus = ItemStatus.ACTIVE
    kb_citations: list[KbCitation] = Field(default_factory=list)


class BrdItem(PayloadItem):
    requirement_id: ReqId
    title: str = Field(min_length=1)
    description: str
    scope: Scope
    source_ref: str = Field(min_length=1)


class SrsItem(PayloadItem):
    requirement_id: ReqId
    kind: SrsKind
    statement: str = Field(min_length=1)
    acceptance_hint: str | None = None
    derives_from: list[ReqId] = Field(default_factory=list)


class BasicDesignItem(PayloadItem):
    kind: BasicDesignKind
    name: str = Field(min_length=1)
    description: str
    realizes: list[ReqOrItemRef] = Field(default_factory=list)


class DetailDesignItem(PayloadItem):
    kind: DetailDesignKind
    name: str = Field(min_length=1)
    spec: str
    refines: list[ItemRef] = Field(default_factory=list)


class TestCaseItem(PayloadItem):
    __test__ = False  # not a pytest class

    test_id: TcId
    level: Level
    precondition: str
    input: str
    steps: list[str]
    expected: str = Field(min_length=1)
    verifies: list[ReqOrItemRef] = Field(default_factory=list)


class TestExclusion(FrozenModel):
    """An item deliberately left without a test case, with the reason."""

    __test__ = False  # not a pytest class

    item_ref: ItemRef
    reason: str = Field(min_length=1)


class DocumentSection(FrozenModel):
    """Document-level prose (背景・目的, 制約事項, ...) with the sources it rests on.

    Sources are intake citations (`intake/<file>#L<a>-L<b>`) in a BRD and upstream REQ ids or
    item refs in later documents. Sections are not items: they carry no id and no trace link.
    """

    key: SectionKey
    body: str = Field(min_length=1)
    sources: list[str] = Field(min_length=1)


class BrdContent(FrozenModel):
    items: list[BrdItem]
    sections: list[DocumentSection] = Field(default_factory=list)


class SrsContent(FrozenModel):
    items: list[SrsItem]
    sections: list[DocumentSection] = Field(default_factory=list)


class BasicDesignContent(FrozenModel):
    items: list[BasicDesignItem]
    sections: list[DocumentSection] = Field(default_factory=list)


class DetailDesignContent(FrozenModel):
    items: list[DetailDesignItem]
    sections: list[DocumentSection] = Field(default_factory=list)


class TestSpecContent(FrozenModel):
    __test__ = False  # not a pytest class

    items: list[TestCaseItem]
    exclusions: list[TestExclusion] = Field(default_factory=list)


Payload = BrdContent | SrsContent | BasicDesignContent | DetailDesignContent | TestSpecContent

PAYLOAD_BY_TYPE: dict[DocType, type[Payload]] = {
    DocType.BRD: BrdContent,
    DocType.SRS: SrsContent,
    DocType.BASIC_DESIGN: BasicDesignContent,
    DocType.DETAIL_DESIGN: DetailDesignContent,
    DocType.TEST_IT: TestSpecContent,
    DocType.TEST_ST: TestSpecContent,
    DocType.TEST_UT: TestSpecContent,
    DocType.TEST_UAT: TestSpecContent,
}

LEVEL_BY_TEST_TYPE: dict[DocType, Level] = {
    DocType.TEST_IT: Level.IT,
    DocType.TEST_ST: Level.ST,
    DocType.TEST_UT: Level.UT,
    DocType.TEST_UAT: Level.UAT,
}


SECTIONS_BY_TYPE: dict[DocType, tuple[SectionKey, ...]] = {
    DocType.BRD: (SectionKey.BACKGROUND, SectionKey.CONSTRAINTS),
    DocType.SRS: (SectionKey.BACKGROUND, SectionKey.CONSTRAINTS),
    DocType.BASIC_DESIGN: (SectionKey.IT_VIEWPOINTS,),
    DocType.DETAIL_DESIGN: (SectionKey.SYSTEM_OVERVIEW,),
}


def payload_items(payload: Payload) -> Sequence[PayloadItem]:
    return payload.items


def payload_sections(payload: Payload) -> Sequence[DocumentSection]:
    return getattr(payload, "sections", ())
