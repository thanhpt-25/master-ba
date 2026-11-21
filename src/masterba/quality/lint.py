"""Style rules a Japanese SIer reviewer checks first, as deterministic findings (spec 19 part 2).

The rules are deliberately few and precise: each one names wording a reviewer would send back.
They never decide whether content is right; QA and the human reviewer do that.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol

from masterba.agents.requirements_analyst import BrdDraft
from masterba.agents.srs_writer import SrsDraft
from masterba.models import Payload, payload_items, payload_sections
from masterba.models.enums import DocLanguage, ItemStatus, SrsKind
from masterba.models.payloads import (
    BasicDesignItem,
    BrdItem,
    DetailDesignItem,
    SrsItem,
    TestCaseItem,
)

MAX_FEEDBACK = 12
MAX_JA_SENTENCE = 150
MAX_EN_WORDS = 50

VAGUE_JA = (
    "適宜",
    "適切に",
    "速やか",
    "迅速",
    "柔軟",
    "簡単に",
    "容易に",
    "十分な",
    "十分に",
    "高速に",
    "可能な限り",
    "できるだけ",
    "なるべく",
    "必要に応じて",
    "使いやすい",
    "分かりやすい",
    "わかりやすい",
)
VAGUE_EN = (
    "appropriate",
    "appropriately",
    "as needed",
    "as soon as possible",
    "if necessary",
    "as much as possible",
    "user-friendly",
    "user friendly",
    "flexible",
    "easily",
    "quickly",
    "sufficient",
    "etc.",
    "and so on",
)
_VAGUE_EN = re.compile(r"\b(" + "|".join(re.escape(w) for w in VAGUE_EN) + r")(?=\W|$)", re.I)
VAGUE_EXPECTED_JA = re.compile(
    r"(正常に(動作|終了|処理|表示|完了)|問題(が|の)?ない|正しく(動作|処理|表示)|想定(どおり|通り))"
)
VAGUE_EXPECTED_EN = re.compile(
    r"\b(works? (correctly|properly)|as expected|no (errors?|problems?) (occurs?|is shown))\b",
    re.I,
)
_OBLIGATION_JA = re.compile(r"(こと|ならない|ねばならない)$")
_POLITE_JA = re.compile(r"(です|ます|ません|でした|ました)(。|、|$)")
_DIGIT = re.compile(r"[0-9０-９]")
_SENTENCE_JA = re.compile(r"[^。！？\n]+")


@dataclass(frozen=True)
class Finding:
    rule: str
    ref: str
    message: str


RULES: dict[str, str] = {
    "STY-01": "vague wording that a tester cannot judge",
    "STY-02": "a requirement statement without an obligation ending",
    "STY-03": "a sentence too long to read as one statement",
    "STY-04": "an expected result a tester cannot judge OK or NG",
    "STY-05": "a non-functional statement without a measurable figure",
    "STY-06": "polite です/ます style in a document written in である style",
}


def vague_words(text: str, language: DocLanguage) -> list[str]:
    if language is DocLanguage.JA:
        return [w for w in VAGUE_JA if w in text]
    return sorted({m.group(1).lower() for m in _VAGUE_EN.finditer(text)})


def _long_sentence(text: str, language: DocLanguage) -> bool:
    if language is DocLanguage.JA:
        return any(len(s.strip()) > MAX_JA_SENTENCE for s in _SENTENCE_JA.findall(text))
    return any(len(s.split()) > MAX_EN_WORDS for s in re.split(r"[.!?]\s", text))


def lint_text(ref: str, text: str, language: DocLanguage, *, vague: bool = True) -> list[Finding]:
    """Rules that apply to any prose: STY-01, STY-03, STY-06."""
    found: list[Finding] = []
    words = vague_words(text, language) if vague else []
    if words:
        quoted = "、".join(f"「{w}」" for w in words)
        found.append(
            Finding(
                "STY-01",
                ref,
                f"vague wording {quoted}: state a measurable condition, or raise an open question "
                "when the input gives none",
            )
        )
    if _long_sentence(text, language):
        found.append(Finding("STY-03", ref, "a sentence is too long: split it, one point each"))
    if language is DocLanguage.JA and _POLITE_JA.search(text):
        found.append(Finding("STY-06", ref, "use the plain である style, not です/ます"))
    return found


def lint_statement(ref: str, text: str, language: DocLanguage) -> list[Finding]:
    """STY-02: one obligation sentence (〜すること / shall)."""
    stripped = text.strip().rstrip("。.")
    ok = (
        bool(_OBLIGATION_JA.search(stripped))
        if language is DocLanguage.JA
        else re.search(r"\bshall\b", text, re.I) is not None
    )
    if ok:
        return []
    ending = "〜すること / 〜できること" if language is DocLanguage.JA else "'shall'"
    return [Finding("STY-02", ref, f"state the requirement as one obligation ending in {ending}")]


def lint_expected(ref: str, text: str, language: DocLanguage) -> list[Finding]:
    """STY-04: an expected result names what is observed, not 'works correctly'."""
    pattern = VAGUE_EXPECTED_JA if language is DocLanguage.JA else VAGUE_EXPECTED_EN
    match = pattern.search(text)
    if match is None:
        return []
    return [
        Finding(
            "STY-04",
            ref,
            f"expected result 「{match.group(0)}」 cannot be judged OK or NG: name the screen, "
            "message, value or record a tester observes",
        )
    ]


def lint_nfr(ref: str, text: str) -> list[Finding]:
    """STY-05: a non-functional statement carries a figure."""
    if _DIGIT.search(text):
        return []
    return [
        Finding(
            "STY-05",
            ref,
            "non-functional statement has no figure: give a number, unit and condition, or raise "
            "an open question when the input gives none",
        )
    ]


def _lines_overlap(a: tuple[int, int], b: tuple[int, int]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def lint_brd_draft(draft: BrdDraft, language: DocLanguage) -> list[Finding]:
    """Findings for a BRD draft; vagueness covered by an open question is not reported."""
    asked = [(q.start_line, q.end_line) for q in draft.open_questions]
    found: list[Finding] = []
    for n, req in enumerate(draft.requirements, start=1):
        covered = any(_lines_overlap((req.start_line, req.end_line), q) for q in asked)
        found += lint_text(f"requirement {n}", req.description, language, vague=not covered)
    for section in draft.sections:
        found += lint_text(f"section {section.key.value}", section.body, language, vague=False)
    return found


def lint_srs_draft(draft: SrsDraft, language: DocLanguage) -> list[Finding]:
    """Findings for an SRS draft; a requirement with an open question is not held to a figure."""
    asked = {req for q in draft.open_questions for req in q.req_ids}
    found: list[Finding] = []
    for n, item in enumerate(draft.items, start=1):
        ref = f"item {n}"
        covered = bool(asked & set(item.derives_from))
        found += lint_statement(ref, item.statement, language)
        found += lint_text(ref, item.statement, language, vague=not covered)
        if item.kind is SrsKind.NON_FUNCTIONAL and not covered:
            found += lint_nfr(ref, item.statement)
    for section in draft.sections:
        found += lint_text(f"section {section.key.value}", section.body, language, vague=False)
    return found


def _item_findings(item: object, language: DocLanguage) -> Iterable[Finding]:
    if isinstance(item, BrdItem):
        yield from lint_text(item.item_id, item.description, language)
    elif isinstance(item, SrsItem):
        yield from lint_statement(item.item_id, item.statement, language)
        yield from lint_text(item.item_id, item.statement, language)
        if item.kind is SrsKind.NON_FUNCTIONAL:
            yield from lint_nfr(item.item_id, item.statement)
    elif isinstance(item, BasicDesignItem):
        yield from lint_text(item.item_id, item.description, language)
    elif isinstance(item, DetailDesignItem):
        yield from lint_text(item.item_id, item.spec, language)
    elif isinstance(item, TestCaseItem):
        yield from lint_expected(item.test_id, item.expected, language)
        yield from lint_text(item.test_id, item.expected, language, vague=False)


def lint_document(content: Payload, language: DocLanguage) -> list[Finding]:
    """Findings for a stored document (the quality report); open questions are not known here."""
    found: list[Finding] = []
    for item in payload_items(content):
        if item.status is ItemStatus.ACTIVE:
            found.extend(_item_findings(item, language))
    for section in payload_sections(content):
        found += lint_text(f"section {section.key.value}", section.body, language, vague=False)
    return found


class _Rounds(Protocol):
    rounds: int
    max_rounds: int


class StyleFeedback:
    """Send style findings back to the writer at most once per run (spec 19 part 2).

    Only when at least two rounds remain, so fixing wording never costs the round QA needs.
    """

    def __init__(self) -> None:
        self.used = False

    def feedback(self, team: _Rounds, findings: Sequence[Finding]) -> list[str]:
        if self.used or not findings or team.max_rounds - team.rounds < 2:
            return []
        self.used = True
        lines = [f"style {f.rule} {f.ref}: {f.message}" for f in findings[:MAX_FEEDBACK]]
        if len(findings) > MAX_FEEDBACK:
            lines.append(f"style: {len(findings) - MAX_FEEDBACK} more findings of the same kinds")
        return lines
