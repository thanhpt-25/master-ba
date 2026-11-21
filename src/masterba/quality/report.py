"""The quality report: measured facts per document plus a rubric for the human reviewer.

No model is called. The figures are what a reviewer would otherwise count by hand; the rubric
scores (1 to 5) are left for an SIer reviewer to fill in (spec 19 part 2, section 6).
"""

from collections import Counter
from dataclasses import dataclass, field

from masterba.models import Document, Payload, payload_items, payload_sections
from masterba.models.enums import DocLanguage, ItemStatus, QuestionStatus, SrsKind
from masterba.models.payloads import SECTIONS_BY_TYPE, SrsItem, TestSpecContent
from masterba.quality.lint import RULES, Finding, lint_document
from masterba.trace_store import (
    ProjectStore,
    get_config,
    get_trace_links,
    latest_documents,
    list_questions,
)

RUBRIC: tuple[tuple[str, str], ...] = (
    ("網羅性 (completeness)", "Every upstream need is covered; nothing is missing or invented."),
    ("正確性 (correctness)", "Statements match the source; no contradiction, no wrong figure."),
    ("検証可能性 (testability)", "A tester can judge each item or case OK or NG."),
    ("表現・用語 (wording)", "One point per sentence, consistent terms, である style."),
    ("構成 (structure)", "Sheets and items sit where an IPA-style document puts them."),
)
MAX_LISTED_FINDINGS = 30


@dataclass(frozen=True)
class DocumentQuality:
    doc_id: str
    version: int
    status: str
    active_items: int
    sections: tuple[str, ...]
    missing_sections: tuple[str, ...]
    traced_upstream: int
    traced_downstream: int
    figures: dict[str, str] = field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    open_questions: int = 0

    @property
    def findings_by_rule(self) -> Counter[str]:
        return Counter(f.rule for f in self.findings)


def _keys(item: object) -> set[str]:
    keys = {getattr(item, "item_id", "")}
    for name in ("requirement_id", "test_id"):
        value = getattr(item, name, None)
        if isinstance(value, str):
            keys.add(value)
    return keys


def _share(count: int, total: int) -> str:
    return f"{count}/{total}" + (f" ({100 * count // total}%)" if total else "")


def _figures(content: Payload) -> dict[str, str]:
    active = [i for i in payload_items(content) if i.status is ItemStatus.ACTIVE]
    figures: dict[str, str] = {}
    srs = [i for i in active if isinstance(i, SrsItem)]
    if srs:
        functional = [i for i in srs if i.kind is SrsKind.FUNCTIONAL]
        hinted = sum(1 for i in functional if i.acceptance_hint)
        figures["functional items with an acceptance hint"] = _share(hinted, len(functional))
        nfr = [i for i in srs if i.kind is SrsKind.NON_FUNCTIONAL]
        measured = sum(1 for i in nfr if any(c.isdigit() for c in i.statement))
        figures["non-functional items with a figure"] = _share(measured, len(nfr))
    if isinstance(content, TestSpecContent):
        figures["exclusions"] = str(len(content.exclusions))
    return figures


def assess(store: ProjectStore, doc: Document, content: Payload) -> DocumentQuality:
    language: DocLanguage = get_config(store).document_language
    links = get_trace_links(store)
    sources = {link.to_id for link in links}
    targets = {link.from_id for link in links}
    active = [i for i in payload_items(content) if i.status is ItemStatus.ACTIVE]
    present = tuple(s.key.value for s in payload_sections(content))
    expected = tuple(k.value for k in SECTIONS_BY_TYPE.get(doc.type, ()))
    open_count = sum(
        1 for q in list_questions(store) if q.stage is doc.type and q.status is QuestionStatus.OPEN
    )
    return DocumentQuality(
        doc_id=doc.id,
        version=doc.version,
        status=doc.status.value,
        active_items=len(active),
        sections=present,
        missing_sections=tuple(k for k in expected if k not in present),
        traced_upstream=sum(1 for i in active if _keys(i) & sources),
        traced_downstream=sum(1 for i in active if _keys(i) & targets),
        figures=_figures(content),
        findings=tuple(lint_document(content, language)),
        open_questions=open_count,
    )


def project_quality(store: ProjectStore) -> list[DocumentQuality]:
    return [assess(store, doc, content) for doc, content in latest_documents(store)]


def to_markdown(project_id: str, report: list[DocumentQuality]) -> str:
    lines = [f"# Quality report: {project_id}", ""]
    if not report:
        return "\n".join([*lines, "No documents yet.", ""])
    lines += [
        "| Document | Ver. | Status | Items | Upstream traced | Downstream traced | "
        "Missing sections | Style findings | Open questions |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for q in report:
        lines.append(
            f"| {q.doc_id} | {q.version} | {q.status} | {q.active_items} | "
            f"{_share(q.traced_upstream, q.active_items)} | "
            f"{_share(q.traced_downstream, q.active_items)} | "
            f"{', '.join(q.missing_sections) or '-'} | {len(q.findings)} | {q.open_questions} |"
        )
    for q in report:
        lines += ["", f"## {q.doc_id} v{q.version}", ""]
        for name, value in q.figures.items():
            lines.append(f"- {name}: {value}")
        for rule, count in sorted(q.findings_by_rule.items()):
            lines.append(f"- {rule} ({RULES[rule]}): {count}")
        if q.findings:
            lines += ["", "| Rule | Ref | Finding |", "|---|---|---|"]
            for f in q.findings[:MAX_LISTED_FINDINGS]:
                lines.append(f"| {f.rule} | {f.ref} | {f.message.replace('|', '/')} |")
            if len(q.findings) > MAX_LISTED_FINDINGS:
                lines.append(f"| | | {len(q.findings) - MAX_LISTED_FINDINGS} more |")
        lines += ["", "Reviewer score (1 = unusable, 5 = hand to the customer as is):", ""]
        lines += ["| Criterion | What to check | Score | Notes |", "|---|---|---|---|"]
        lines += [f"| {name} | {what} | | |" for name, what in RUBRIC]
    return "\n".join(lines) + "\n"
