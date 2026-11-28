"""Derive a `RenderContext` from the store, with no model (spec 19 section 1, spec 26)."""

import subprocess
from collections import Counter
from pathlib import Path

from masterba.diff import ChangeType, diff_documents
from masterba.models import DecisionRecord, Document, Payload, PayloadItem, payload_items
from masterba.models.enums import DrTrigger, ItemStatus, QuestionStatus, ReviewDecision
from masterba.models.payloads import BasicDesignItem, BrdItem, DetailDesignItem, SrsItem
from masterba.rendering.catalog import doc_spec
from masterba.rendering.codes import display_code
from masterba.rendering.context import AUTHOR, QuestionRow, RenderContext, Revision, TraceRow
from masterba.trace_store import (
    ProjectStore,
    document_versions,
    get_config,
    get_document,
    get_dr_extra,
    get_trace_links,
    latest_documents,
    list_decision_records,
    list_questions,
    list_reviews,
)

TRIGGER_LABELS: dict[DrTrigger, str] = {
    DrTrigger.REQUIREMENT_CHANGE: "要件変更",
    DrTrigger.DESIGN_CHANGE: "設計変更",
    DrTrigger.DEFECT: "不具合対応",
    DrTrigger.CLARIFICATION: "顧客回答反映",
    DrTrigger.KNOWLEDGE_CHANGE: "参照資料変更",
    DrTrigger.REVIEW_FEEDBACK: "レビュー指摘対応",
}
FIRST_SUMMARY = "初版作成"
FIRST_REASON = "新規作成"
FIRST_SHEETS = "全体"
_ADDED, _CHANGED, _REMOVED = "追加", "変更", "削除"


def _added_on(root: Path, path: Path) -> str | None:
    """Commit date (YYYY/MM/DD) of the commit that added `path`; None when git has none."""
    found = subprocess.run(
        ["git", "log", "--diff-filter=A", "--format=%cs", "--", str(path)],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    dates = found.stdout.split()
    return dates[-1].replace("-", "/") if found.returncode == 0 and dates else None


def _changed_items(before: Payload, after: Payload) -> dict[str, str]:
    """Item id to 追加 / 変更 / 削除; setting `removed` counts as 削除."""
    kinds: dict[str, str] = {}
    for change in diff_documents(before, after):
        if change.change_type is ChangeType.ADDED:
            kinds[change.item_id] = _ADDED
        elif change.change_type is ChangeType.REMOVED or (
            change.field == "status" and change.new == ItemStatus.REMOVED.value
        ):
            kinds[change.item_id] = _REMOVED
        else:
            kinds.setdefault(change.item_id, _CHANGED)
    return kinds


def _summary(kinds: dict[str, str]) -> str:
    """`追加 n件、変更 n件、削除 n件`, counted per item."""
    counts = Counter(kinds.values())
    parts = [
        f"{label} {counts[label]}件" for label in (_ADDED, _CHANGED, _REMOVED) if counts[label]
    ]
    return "、".join(parts) or "変更なし"


def _matches_ignoring_status(item: PayloadItem, where: tuple[tuple[str, str], ...]) -> bool:
    for key, expected in where:
        if key == "status":
            continue
        actual = getattr(item, key)
        if str(getattr(actual, "value", actual)) != expected:
            return False
    return True


def _changed_sheets(doc: Document, before: Payload, after: Payload, ids: set[str]) -> str:
    """改訂箇所: the default content sheets that list a changed item, in workbook order."""
    items = {i.item_id: i for i in payload_items(before)}
    items.update({i.item_id: i for i in payload_items(after)})
    changed = [items[i] for i in sorted(ids) if i in items]
    names = [
        sheet.name
        for sheet in doc_spec(doc.type).sheets
        if sheet.columns
        and sheet.source is None
        and any(_matches_ignoring_status(item, sheet.where) for item in changed)
    ]
    return "、".join(names)


def _reason(dr: DecisionRecord) -> str:
    return f"{dr.id}（{TRIGGER_LABELS[dr.trigger]}）: {dr.description}"


def _dr_reasons(store: ProjectStore, doc: Document, revised_by: str | None) -> dict[int, str]:
    """Version to reason, from each DR's propagation progress (spec 07 section 6).

    `revised_by` names the DR writing `doc.version` right now, before its progress lists it.
    """
    reasons: dict[int, str] = {}
    for dr in list_decision_records(store):
        progress = get_dr_extra(store, dr.id, "propagation") or {}
        entry = progress.get("documents", {}).get(doc.id)
        if entry and entry.get("outcome") == "revised" and entry.get("version"):
            reasons[int(entry["version"])] = _reason(dr)
        if dr.id == revised_by:
            reasons.setdefault(doc.version, _reason(dr))
    return reasons


def _approvals(store: ProjectStore, doc_id: str) -> dict[int, tuple[str, str]]:
    approvals: dict[int, tuple[str, str]] = {}
    for review in list_reviews(store):
        if review.decision is not ReviewDecision.APPROVED:
            continue
        for reviewed in review.documents:
            if reviewed.doc_id == doc_id:
                approvals[reviewed.version] = (review.by, review.at.strftime("%Y/%m/%d"))
    return approvals


def revisions(
    store: ProjectStore, doc: Document, revised_by: str | None = None
) -> tuple[Revision, ...]:
    """One `Revision` per stored version up to `doc.version`."""
    reasons = _dr_reasons(store, doc, revised_by)
    approvals = _approvals(store, doc.id)
    rows: list[Revision] = []
    previous: Payload | None = None
    for version in (v for v in document_versions(store, doc.id) if v <= doc.version):
        stored, content = get_document(store, doc.id, version)
        approver, approved_on = approvals.get(version, (None, None))
        kinds = {} if previous is None else _changed_items(previous, content)
        rows.append(
            Revision(
                version=version,
                date=_added_on(store.root, store.path / stored.content_ref),
                summary=FIRST_SUMMARY if previous is None else _summary(kinds),
                reason=FIRST_REASON if previous is None else reasons.get(version, ""),
                author=AUTHOR,
                approver=approver,
                approved_on=approved_on,
                changed_sheets=(
                    FIRST_SHEETS
                    if previous is None
                    else _changed_sheets(doc, previous, content, set(kinds))
                ),
            )
        )
        previous = content
    return tuple(rows)


def _name(item: object) -> str:
    if isinstance(item, BrdItem):
        return item.title
    if isinstance(item, SrsItem):
        return item.statement
    if isinstance(item, BasicDesignItem | DetailDesignItem):
        return item.name
    return ""


def trace_rows(store: ProjectStore, content: Payload) -> tuple[TraceRow, ...]:
    """Upstream and downstream ends of the stored trace links of every active item."""
    links = get_trace_links(store)
    rows: list[TraceRow] = []
    for item in payload_items(content):
        if item.status is not ItemStatus.ACTIVE:
            continue
        keys = {item.item_id}
        if isinstance(item, BrdItem | SrsItem):
            keys.add(item.requirement_id)
        test_id = getattr(item, "test_id", None)
        if isinstance(test_id, str):
            keys.add(test_id)
        upstream = sorted({link.from_id for link in links if link.to_id in keys} - keys)
        downstream = sorted({link.to_id for link in links if link.from_id in keys} - keys)
        rows.append(
            TraceRow(
                item.item_id, _name(item), tuple(upstream), tuple(downstream), display_code(item)
            )
        )
    return tuple(rows)


def open_question_rows(store: ProjectStore, doc: Document) -> tuple[QuestionRow, ...]:
    """未決事項: the open questions of the document's stage, by id."""
    return tuple(
        QuestionRow(
            id=q.id,
            text=q.text,
            refs=tuple(q.refs),
            asked_on=q.asked_on.strftime("%Y/%m/%d"),
            status=q.status.value,
        )
        for q in sorted(list_questions(store), key=lambda q: q.id)
        if q.stage is doc.type and q.status is QuestionStatus.OPEN
    )


def item_names(store: ProjectStore) -> dict[str, str]:
    """Item ref and REQ id to the name printed for it, over the latest stored documents."""
    names: dict[str, str] = {}
    for _, content in latest_documents(store):
        for item in payload_items(content):
            name = _name(item)
            if not name:
                continue
            names[item.item_id] = name
            if isinstance(item, BrdItem | SrsItem):
                names[item.requirement_id] = name
    return names


def build_context(
    store: ProjectStore, doc: Document, content: Payload, revised_by: str | None = None
) -> RenderContext:
    company = get_config(store).company_id
    return RenderContext(
        company=None if company == "default" else company,
        author=AUTHOR,
        revisions=revisions(store, doc, revised_by),
        trace=trace_rows(store, content),
        questions=open_question_rows(store, doc),
        names=item_names(store),
    )
