"""srs-writer-agent: BRD requirements -> SRS draft (spec 04 section 5)."""

from collections.abc import Sequence
from dataclasses import dataclass

from pydantic import Field

from masterba.agents.requirements_analyst import (
    REPO_ROOT,
    language_problem,
    load_system_prompt,
)
from masterba.llm import LLM, LLMResult
from masterba.models import BrdContent, RequirementItem
from masterba.models.base import FrozenModel
from masterba.models.enums import DocLanguage, ItemStatus, ReqCategory, Scope, SrsKind
from masterba.models.ids import ReqId
from masterba.models.knowledge import KbCitation

PROMPT_PATH = REPO_ROOT / "agents" / "srs-writer.md"
TOOL_NAME = "submit_srs"
_LANGUAGE_INSTRUCTION = {
    DocLanguage.JA: "Write every `statement` and `acceptance_hint` in Japanese (日本語). "
    "Use 「〜すること」 style obligations.",
    DocLanguage.EN: "Write every `statement` and `acceptance_hint` in English, using 'shall'.",
}


class DraftSrsItem(FrozenModel):
    kind: SrsKind
    statement: str = Field(min_length=1)
    acceptance_hint: str | None = None
    derives_from: list[ReqId] = Field(min_length=1)
    kb_citations: list[KbCitation] = Field(default_factory=list)


class SrsOpenQuestion(FrozenModel):
    question: str = Field(min_length=1)
    req_ids: list[ReqId] = Field(min_length=1)


class SrsDraft(FrozenModel):
    items: list[DraftSrsItem] = Field(min_length=1)
    open_questions: list[SrsOpenQuestion] = Field(default_factory=list)


@dataclass(frozen=True)
class BrdRequirement:
    req_id: str
    category: ReqCategory
    title: str
    description: str


def brd_requirements(
    content: BrdContent, requirements: Sequence[RequirementItem]
) -> list[BrdRequirement]:
    """Active, in-scope BRD requirements in BRD order, with their category."""
    category = {r.id: r.category for r in requirements}
    return [
        BrdRequirement(i.requirement_id, category[i.requirement_id], i.title, i.description)
        for i in content.items
        if i.status is ItemStatus.ACTIVE and i.scope is Scope.IN and i.requirement_id in category
    ]


def brd_view(brd: Sequence[BrdRequirement]) -> str:
    return "\n".join(f"{r.req_id} [{r.category.value}] {r.title}: {r.description}" for r in brd)


def draft_view(draft: SrsDraft, doc_id: str) -> str:
    lines: list[str] = []
    for number, item in enumerate(draft.items, start=1):
        hint = f" | acceptance: {item.acceptance_hint}" if item.acceptance_hint else ""
        source = ", ".join(item.derives_from)
        lines.append(
            f"{doc_id}#item.{number} [{item.kind.value}] {item.statement}{hint} (from {source})"
        )
    if draft.open_questions:
        lines.append("Open questions the writer raised for the customer (not requirements):")
        lines.extend(f"- {', '.join(q.req_ids)}: {q.question}" for q in draft.open_questions)
    return "\n".join(lines)


def validate_srs_draft(
    draft: SrsDraft, brd: Sequence[BrdRequirement], language: DocLanguage | None = None
) -> list[str]:
    """Deterministic gate: citations exist and are in scope, every requirement is covered."""
    allowed = {r.req_id for r in brd}
    errors: list[str] = []
    cited: set[str] = set()
    seen: dict[str, int] = {}
    for index, item in enumerate(draft.items, start=1):
        for req_id in item.derives_from:
            if req_id not in allowed:
                errors.append(f"item {index}: {req_id} is not an in-scope BRD requirement")
            cited.add(req_id)
        key = " ".join(item.statement.split()).lower()
        if key in seen:
            errors.append(f"item {index}: statement duplicates item {seen[key]}")
        seen.setdefault(key, index)
        if language is not None:
            for text in (item.statement, item.acceptance_hint or ""):
                if text and (problem := language_problem(text, language)):
                    errors.append(f"item {index}: text {problem}")
    for index, question in enumerate(draft.open_questions, start=1):
        for req_id in question.req_ids:
            if req_id not in allowed:
                errors.append(f"open question {index}: {req_id} is not an in-scope BRD requirement")
        if language is not None and (problem := language_problem(question.question, language)):
            errors.append(f"open question {index}: text {problem}")
    missing = [r.req_id for r in brd if r.req_id not in cited]
    if missing:
        errors.append(f"in-scope requirements not covered by any item: {', '.join(missing)}")
    return errors


def system_prompt_for(language: DocLanguage, base: str | None = None) -> str:
    text = base if base is not None else load_system_prompt(PROMPT_PATH)
    return f"{text}\n\n## Output language\n\n{_LANGUAGE_INSTRUCTION[language]}"


def write_srs(
    llm: LLM,
    brd: Sequence[BrdRequirement],
    language: DocLanguage,
    previous: SrsDraft | None,
    feedback: Sequence[str],
    doc_id: str,
    system_prompt: str | None = None,
) -> LLMResult[SrsDraft]:
    """One writer call: a first draft, or a revision when `previous` and `feedback` are given."""
    user = f"<brd>\n{brd_view(brd)}\n</brd>"
    if previous is not None:
        listing = "\n".join(f"- {f}" for f in feedback)
        user += (
            f"\n\n<previous_draft>\n{draft_view(previous, doc_id)}\n</previous_draft>\n\n"
            f"The previous draft was rejected for these reasons:\n{listing}\n"
            "Return a corrected, complete SRS."
        )
    return llm.generate(
        system=system_prompt_for(language, system_prompt),
        user=user,
        output=SrsDraft,
        tool_name=TOOL_NAME,
    )
