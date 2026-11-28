"""Data a workbook prints besides the payload: cover, history, traceability (spec 19, spec 26).

Pure values only; `rendering/history.py` derives them from the store.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field, fields

from masterba.models.enums import DocType

DOC_TITLES: dict[DocType, str] = {
    DocType.BRD: "業務要件定義書",
    DocType.SRS: "システム要件定義書",
    DocType.BASIC_DESIGN: "基本設計書",
    DocType.DETAIL_DESIGN: "詳細設計書",
    DocType.TEST_IT: "結合テスト仕様書",
    DocType.TEST_ST: "総合テスト仕様書",
    DocType.TEST_UT: "単体テスト仕様書",
    DocType.TEST_UAT: "受入テスト仕様書",
}

AUTHOR = "MasterBA"
PUBLISHER = "MasterBA"
CLASSIFICATION = "社外秘"


def version_label(version: int) -> str:
    """版数 as a Japanese SIer prints it: version 2 is `2.0`."""
    return f"{version}.0"


@dataclass(frozen=True)
class Revision:
    """One row of 改訂履歴."""

    version: int
    date: str | None
    summary: str
    reason: str
    author: str
    approver: str | None = None
    approved_on: str | None = None
    changed_sheets: str = ""  # 改訂箇所

    @property
    def version_label(self) -> str:
        return version_label(self.version)


@dataclass(frozen=True)
class TraceRow:
    """One row of トレーサビリティ: an active item and the ends of its trace links."""

    item: str  # the item ref (管理ID)
    name: str
    upstream: tuple[str, ...]
    downstream: tuple[str, ...]
    code: str = ""  # REQ id, test case id or display code (spec 26 section 2)


@dataclass(frozen=True)
class QuestionRow:
    """One row of 未決事項: an open customer question of the document's stage."""

    id: str
    text: str
    refs: tuple[str, ...]
    asked_on: str
    status: str


@dataclass(frozen=True)
class RenderContext:
    company: str | None = None
    author: str = AUTHOR
    revisions: tuple[Revision, ...] = ()
    trace: tuple[TraceRow, ...] = ()
    questions: tuple[QuestionRow, ...] = ()
    names: Mapping[str, str] = field(default_factory=dict)  # item ref or REQ id to its name

    def revision(self, version: int) -> Revision | None:
        return next((r for r in self.revisions if r.version == version), None)

    @property
    def created_on(self) -> str | None:
        return self.revisions[0].date if self.revisions else None


EMPTY_CONTEXT = RenderContext(author="")

REVISION_FIELDS = frozenset({*(f.name for f in fields(Revision)), "version_label"})
TRACE_FIELDS = frozenset(f.name for f in fields(TraceRow))
QUESTION_FIELDS = frozenset(f.name for f in fields(QuestionRow))
