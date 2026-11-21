"""Data a workbook prints besides the payload: cover, revision history, traceability (spec 19).

Pure values only; `rendering/history.py` derives them from the store.
"""

from dataclasses import dataclass, fields

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


@dataclass(frozen=True)
class TraceRow:
    """One row of トレーサビリティ: an active item and the ends of its trace links."""

    item: str
    name: str
    upstream: tuple[str, ...]
    downstream: tuple[str, ...]


@dataclass(frozen=True)
class RenderContext:
    company: str | None = None
    author: str = AUTHOR
    revisions: tuple[Revision, ...] = ()
    trace: tuple[TraceRow, ...] = ()

    def revision(self, version: int) -> Revision | None:
        return next((r for r in self.revisions if r.version == version), None)

    @property
    def created_on(self) -> str | None:
        return self.revisions[0].date if self.revisions else None


EMPTY_CONTEXT = RenderContext(author="")

REVISION_FIELDS = frozenset(f.name for f in fields(Revision))
TRACE_FIELDS = frozenset(f.name for f in fields(TraceRow))
