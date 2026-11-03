"""detail-design-agent: Basic Design -> Detail Design draft (spec 06 sections 2 and 4)."""

from collections.abc import Sequence

from pydantic import Field

from masterba.agents.design_writer import DesignAnswer
from masterba.agents.requirements_analyst import (
    REPO_ROOT,
    language_problem,
    load_system_prompt,
)
from masterba.llm import LLM, LLMResult
from masterba.models import BasicDesignContent, BasicDesignItem
from masterba.models.base import FrozenModel
from masterba.models.enums import DetailDesignKind, DocLanguage, ItemStatus
from masterba.models.ids import ItemRef
from masterba.models.knowledge import KbCitation

PROMPT_PATH = REPO_ROOT / "agents" / "detail-design.md"
TOOL_NAME = "submit_detail_design"
_LANGUAGE_INSTRUCTION = {
    DocLanguage.JA: "Write every `name`, `spec` and answer text in Japanese (日本語).",
    DocLanguage.EN: "Write every `name`, `spec` and answer text in English.",
}


class DraftDetailItem(FrozenModel):
    kind: DetailDesignKind
    name: str = Field(min_length=1)
    spec: str = Field(min_length=1)
    refines: list[ItemRef] = Field(min_length=1)
    kb_citations: list[KbCitation] = Field(default_factory=list)


class DetailDesignDraft(FrozenModel):
    items: list[DraftDetailItem] = Field(min_length=1)
    answers: list[DesignAnswer] = Field(default_factory=list)


def active_basic_items(content: BasicDesignContent) -> list[BasicDesignItem]:
    return [i for i in content.items if i.status is ItemStatus.ACTIVE]


def basic_view(items: Sequence[BasicDesignItem]) -> str:
    return "\n".join(f"{i.item_id} [{i.kind.value}] {i.name}: {i.description}" for i in items)


def detail_refs(draft: DetailDesignDraft, doc_id: str) -> list[str]:
    return [f"{doc_id}#item.{n}" for n in range(1, len(draft.items) + 1)]


def detail_view(draft: DetailDesignDraft, doc_id: str) -> str:
    lines = [
        f"{ref} [{item.kind.value}] {item.name}: {item.spec} (refines {', '.join(item.refines)})"
        for ref, item in zip(detail_refs(draft, doc_id), draft.items, strict=True)
    ]
    if draft.answers:
        lines.append("Answers the designer gave to the tester:")
        lines.extend(f"- {a.ref}: {a.text}" for a in draft.answers)
    return "\n".join(lines)


def validate_detail_draft(
    draft: DetailDesignDraft,
    basic_items: Sequence[BasicDesignItem],
    doc_id: str,
    language: DocLanguage | None = None,
) -> list[str]:
    """Deterministic gate: refined items exist, every Basic Design item is refined."""
    allowed = {i.item_id for i in basic_items}
    errors: list[str] = []
    refined: set[str] = set()
    seen: dict[tuple[str, str], int] = {}
    for index, item in enumerate(draft.items, start=1):
        for ref in item.refines:
            if ref not in allowed:
                errors.append(f"item {index}: {ref} is not an active Basic Design item")
            refined.add(ref)
        key = (item.kind.value, " ".join(item.name.split()).lower())
        if key in seen:
            errors.append(f"item {index}: name duplicates item {seen[key]} of the same kind")
        seen.setdefault(key, index)
        if language is not None and (problem := language_problem(item.spec, language)):
            errors.append(f"item {index}: spec {problem}")
    valid_refs = set(detail_refs(draft, doc_id))
    for index, answer in enumerate(draft.answers, start=1):
        if answer.ref not in valid_refs:
            errors.append(f"answer {index}: {answer.ref} is not an item of the detail design")
        if language is not None and (problem := language_problem(answer.text, language)):
            errors.append(f"answer {index}: text {problem}")
    missing = [i.item_id for i in basic_items if i.item_id not in refined]
    if missing:
        errors.append(f"Basic Design items not refined by any detail item: {', '.join(missing)}")
    return errors


def system_prompt_for(language: DocLanguage, base: str | None = None) -> str:
    text = base if base is not None else load_system_prompt(PROMPT_PATH)
    return f"{text}\n\n## Output language\n\n{_LANGUAGE_INSTRUCTION[language]}"


def write_detail(
    llm: LLM,
    basic_items: Sequence[BasicDesignItem],
    language: DocLanguage,
    previous: DetailDesignDraft | None,
    feedback: Sequence[str],
    doc_id: str,
    system_prompt: str | None = None,
    *,
    references: str = "",
) -> LLMResult[DetailDesignDraft]:
    """One designer call: a first detail design, or a revision with the pending feedback."""
    user = f"<basic_design>\n{basic_view(basic_items)}\n</basic_design>"
    if references:  # the Reference_Block (spec 12); empty keeps the prompt unchanged
        user += f"\n\n{references}"
    if previous is not None:
        listing = "\n".join(f"- {f}" for f in feedback)
        user += (
            f"\n\n<previous_design>\n{detail_view(previous, doc_id)}\n</previous_design>\n\n"
            f"The previous detail design was sent back for these reasons:\n{listing}\n"
            "Return a corrected, complete detail design. Put the answer to every tester question "
            "into the spec of the item it concerns and also list it in `answers`."
        )
    return llm.generate(
        system=system_prompt_for(language, system_prompt),
        user=user,
        output=DetailDesignDraft,
        tool_name=TOOL_NAME,
    )
