"""basic-test-design-agent: design + SRS -> IT and ST test drafts (spec 05 sections 2 and 4)."""

from collections.abc import Sequence

from pydantic import Field, field_validator

from masterba.agents.design_writer import (
    BasicDesignDraft,
    design_refs,
    design_view,
    srs_view,
)
from masterba.agents.requirements_analyst import (
    REPO_ROOT,
    language_problem,
    load_system_prompt,
)
from masterba.llm import LLM, LLMResult
from masterba.models import SrsItem
from masterba.models.base import FrozenModel
from masterba.models.enums import DocLanguage
from masterba.models.ids import ItemRef
from masterba.models.knowledge import KbCitation

PROMPT_PATH = REPO_ROOT / "agents" / "basic-test-design.md"
TOOL_NAME = "submit_tests"
_LANGUAGE_INSTRUCTION = {
    DocLanguage.JA: "Write every precondition, input, step, expected result, reason and question "
    "in Japanese (日本語).",
    DocLanguage.EN: "Write every precondition, input, step, expected result, reason and question "
    "in English.",
}


class DraftTestCase(FrozenModel):
    precondition: str
    input: str
    steps: list[str] = Field(min_length=1)
    expected: str = Field(min_length=1)
    verifies: list[ItemRef] = Field(min_length=1)
    kb_citations: list[KbCitation] = Field(default_factory=list)

    @field_validator("steps")
    @classmethod
    def _no_blank_step(cls, steps: list[str]) -> list[str]:
        if any(not step.strip() for step in steps):
            raise ValueError("steps must not be blank")
        return steps


class DraftExclusion(FrozenModel):
    item_ref: ItemRef
    reason: str = Field(min_length=1)


class DesignQuestion(FrozenModel):
    ref: ItemRef
    question: str = Field(min_length=1)


class TestDraft(FrozenModel):
    __test__ = False  # not a pytest class

    it_cases: list[DraftTestCase] = Field(default_factory=list)
    st_cases: list[DraftTestCase] = Field(default_factory=list)
    exclusions: list[DraftExclusion] = Field(default_factory=list)
    questions: list[DesignQuestion] = Field(default_factory=list)


def cases_view(draft: TestDraft, it_doc_id: str, st_doc_id: str) -> str:
    """Numbered view of both test documents with the refs the cases get on commit."""
    lines: list[str] = []
    for doc_id, level, cases in (
        (it_doc_id, "IT", draft.it_cases),
        (st_doc_id, "ST", draft.st_cases),
    ):
        for number, case in enumerate(cases, start=1):
            steps = " ".join(f"{n}. {s}" for n, s in enumerate(case.steps, start=1))
            lines.append(
                f"{doc_id}#item.{number} [{level}] verifies {', '.join(case.verifies)} | "
                f"precondition: {case.precondition} | input: {case.input} | steps: {steps} | "
                f"expected: {case.expected}"
            )
    if draft.exclusions:
        lines.append("Items left without a test case:")
        lines.extend(f"- {e.item_ref}: {e.reason}" for e in draft.exclusions)
    if draft.questions:
        lines.append("Questions the tester asked the designer:")
        lines.extend(f"- {q.ref}: {q.question}" for q in draft.questions)
    return "\n".join(lines)


def validate_test_draft(
    draft: TestDraft,
    design: BasicDesignDraft,
    srs_items: Sequence[SrsItem],
    design_doc_id: str,
    language: DocLanguage | None = None,
) -> list[str]:
    """Deterministic gate: refs resolve, steps are real, every item is tested or excluded."""
    design_set = set(design_refs(design, design_doc_id))
    srs_set = {i.item_id for i in srs_items}
    errors: list[str] = []
    it_tested: set[str] = set()
    st_tested: set[str] = set()
    for level, cases, valid, tested in (
        ("IT", draft.it_cases, design_set, it_tested),
        ("ST", draft.st_cases, srs_set, st_tested),
    ):
        for index, case in enumerate(cases, start=1):
            for ref in case.verifies:
                if ref not in valid:
                    kind = "a design item" if level == "IT" else "an active SRS item"
                    errors.append(f"{level} case {index}: {ref} is not {kind}")
                tested.add(ref)
            if language is not None:
                for text in (case.precondition, case.input, case.expected, *case.steps):
                    if text and (problem := language_problem(text, language)):
                        errors.append(f"{level} case {index}: text {problem}")
                        break
    excluded: set[str] = set()
    for index, exclusion in enumerate(draft.exclusions, start=1):
        if exclusion.item_ref not in design_set | srs_set:
            errors.append(f"exclusion {index}: {exclusion.item_ref} is not a design or SRS item")
        if exclusion.item_ref in it_tested | st_tested:
            errors.append(f"exclusion {index}: {exclusion.item_ref} is also tested")
        if language is not None and (problem := language_problem(exclusion.reason, language)):
            errors.append(f"exclusion {index}: reason {problem}")
        excluded.add(exclusion.item_ref)
    for index, question in enumerate(draft.questions, start=1):
        if question.ref not in design_set:
            errors.append(f"question {index}: {question.ref} is not a design item")
    untested_design = sorted(design_set - it_tested - excluded)
    if untested_design:
        errors.append(
            f"design items with no IT case and no exclusion: {', '.join(untested_design)}"
        )
    untested_srs = sorted(srs_set - st_tested - excluded)
    if untested_srs:
        errors.append(f"SRS items with no ST case and no exclusion: {', '.join(untested_srs)}")
    return errors


def system_prompt_for(language: DocLanguage, base: str | None = None) -> str:
    text = base if base is not None else load_system_prompt(PROMPT_PATH)
    return f"{text}\n\n## Output language\n\n{_LANGUAGE_INSTRUCTION[language]}"


def write_tests(
    llm: LLM,
    design: BasicDesignDraft,
    srs_items: Sequence[SrsItem],
    language: DocLanguage,
    previous: TestDraft | None,
    feedback: Sequence[str],
    design_doc_id: str,
    it_doc_id: str,
    st_doc_id: str,
    system_prompt: str | None = None,
    *,
    references: str = "",
) -> LLMResult[TestDraft]:
    """One tester call: first tests, or a revision with the pending feedback."""
    user = (
        f"<srs>\n{srs_view(srs_items)}\n</srs>\n\n"
        f"<design>\n{design_view(design, design_doc_id)}\n</design>"
    )
    if references:  # the Reference_Block (spec 12); empty keeps the prompt unchanged
        user += f"\n\n{references}"
    if previous is not None:
        listing = "\n".join(f"- {f}" for f in feedback)
        user += (
            f"\n\n<previous_tests>\n{cases_view(previous, it_doc_id, st_doc_id)}\n"
            f"</previous_tests>\n\nThe previous tests were sent back for these reasons:\n"
            f"{listing}\nReturn corrected, complete tests."
        )
    return llm.generate(
        system=system_prompt_for(language, system_prompt),
        user=user,
        output=TestDraft,
        tool_name=TOOL_NAME,
    )
