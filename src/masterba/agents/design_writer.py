"""basic-design-agent: SRS -> Basic Design draft (spec 05 sections 2 and 4)."""

from collections.abc import Sequence

from pydantic import Field

from masterba.agents.requirements_analyst import (
    REPO_ROOT,
    language_problem,
    load_system_prompt,
)
from masterba.llm import LLM, LLMResult
from masterba.models import SrsContent, SrsItem
from masterba.models.base import FrozenModel
from masterba.models.enums import BasicDesignKind, DocLanguage, ItemStatus
from masterba.models.ids import ItemRef
from masterba.models.knowledge import KbCitation

PROMPT_PATH = REPO_ROOT / "agents" / "basic-design.md"
TOOL_NAME = "submit_basic_design"
_LANGUAGE_INSTRUCTION = {
    DocLanguage.JA: "Write every `name`, `description` and answer text in Japanese (日本語).",
    DocLanguage.EN: "Write every `name`, `description` and answer text in English.",
}


class DesignAnswer(FrozenModel):
    """The designer's reply to a tester question about one design item."""

    ref: ItemRef
    text: str = Field(min_length=1)


class DraftDesignItem(FrozenModel):
    kind: BasicDesignKind
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    realizes: list[ItemRef] = Field(min_length=1)
    kb_citations: list[KbCitation] = Field(default_factory=list)


class BasicDesignDraft(FrozenModel):
    items: list[DraftDesignItem] = Field(min_length=1)
    answers: list[DesignAnswer] = Field(default_factory=list)


def active_srs_items(content: SrsContent) -> list[SrsItem]:
    return [i for i in content.items if i.status is ItemStatus.ACTIVE]


def srs_view(items: Sequence[SrsItem]) -> str:
    lines: list[str] = []
    for item in items:
        hint = f" | acceptance: {item.acceptance_hint}" if item.acceptance_hint else ""
        lines.append(f"{item.item_id} [{item.kind.value}] {item.statement}{hint}")
    return "\n".join(lines)


def design_refs(draft: BasicDesignDraft, doc_id: str) -> list[str]:
    return [f"{doc_id}#item.{n}" for n in range(1, len(draft.items) + 1)]


def design_view(draft: BasicDesignDraft, doc_id: str) -> str:
    lines = [
        f"{ref} [{item.kind.value}] {item.name}: {item.description} "
        f"(realizes {', '.join(item.realizes)})"
        for ref, item in zip(design_refs(draft, doc_id), draft.items, strict=True)
    ]
    if draft.answers:
        lines.append("Answers the designer gave to the tester:")
        lines.extend(f"- {a.ref}: {a.text}" for a in draft.answers)
    return "\n".join(lines)


def validate_design_draft(
    draft: BasicDesignDraft,
    srs_items: Sequence[SrsItem],
    doc_id: str,
    language: DocLanguage | None = None,
) -> list[str]:
    """Deterministic gate: realised SRS items exist, every SRS item is realised."""
    allowed = {i.item_id for i in srs_items}
    errors: list[str] = []
    realized: set[str] = set()
    seen: dict[tuple[str, str], int] = {}
    for index, item in enumerate(draft.items, start=1):
        for ref in item.realizes:
            if ref not in allowed:
                errors.append(f"item {index}: {ref} is not an active SRS item")
            realized.add(ref)
        key = (item.kind.value, " ".join(item.name.split()).lower())
        if key in seen:
            errors.append(f"item {index}: name duplicates item {seen[key]} of the same kind")
        seen.setdefault(key, index)
        if language is not None and (problem := language_problem(item.description, language)):
            errors.append(f"item {index}: description {problem}")
    valid_refs = set(design_refs(draft, doc_id))
    for index, answer in enumerate(draft.answers, start=1):
        if answer.ref not in valid_refs:
            errors.append(f"answer {index}: {answer.ref} is not an item of the design")
        if language is not None and (problem := language_problem(answer.text, language)):
            errors.append(f"answer {index}: text {problem}")
    missing = [i.item_id for i in srs_items if i.item_id not in realized]
    if missing:
        errors.append(f"SRS items not realised by any design item: {', '.join(missing)}")
    return errors


def system_prompt_for(language: DocLanguage, base: str | None = None) -> str:
    text = base if base is not None else load_system_prompt(PROMPT_PATH)
    return f"{text}\n\n## Output language\n\n{_LANGUAGE_INSTRUCTION[language]}"


def write_design(
    llm: LLM,
    srs_items: Sequence[SrsItem],
    language: DocLanguage,
    previous: BasicDesignDraft | None,
    feedback: Sequence[str],
    doc_id: str,
    system_prompt: str | None = None,
    *,
    references: str = "",
) -> LLMResult[BasicDesignDraft]:
    """One designer call: a first design, or a revision with the pending feedback."""
    user = f"<srs>\n{srs_view(srs_items)}\n</srs>"
    if references:  # the Reference_Block (spec 12); empty keeps the prompt unchanged
        user += f"\n\n{references}"
    if previous is not None:
        listing = "\n".join(f"- {f}" for f in feedback)
        user += (
            f"\n\n<previous_design>\n{design_view(previous, doc_id)}\n</previous_design>\n\n"
            f"The previous design was sent back for these reasons:\n{listing}\n"
            "Return a corrected, complete design. Put the answer to every tester question into the "
            "description of the item it concerns and also list it in `answers`."
        )
    return llm.generate(
        system=system_prompt_for(language, system_prompt),
        user=user,
        output=BasicDesignDraft,
        tool_name=TOOL_NAME,
    )
