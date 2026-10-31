"""unit-test-design-agent: Detail Design -> UT test draft (spec 06 sections 2 and 4)."""

from collections.abc import Sequence

from pydantic import Field

from masterba.agents.detail_writer import (
    DetailDesignDraft,
    basic_view,
    detail_refs,
    detail_view,
)
from masterba.agents.requirements_analyst import (
    REPO_ROOT,
    language_problem,
    load_system_prompt,
)
from masterba.agents.test_writer import DesignQuestion, DraftExclusion, DraftTestCase
from masterba.llm import LLM, LLMResult
from masterba.models import BasicDesignItem
from masterba.models.base import FrozenModel
from masterba.models.enums import DocLanguage

PROMPT_PATH = REPO_ROOT / "agents" / "unit-test-design.md"
TOOL_NAME = "submit_unit_tests"
_LANGUAGE_INSTRUCTION = {
    DocLanguage.JA: "Write every precondition, input, step, expected result, reason and question "
    "in Japanese (日本語).",
    DocLanguage.EN: "Write every precondition, input, step, expected result, reason and question "
    "in English.",
}


class UnitTestDraft(FrozenModel):
    ut_cases: list[DraftTestCase] = Field(default_factory=list)
    exclusions: list[DraftExclusion] = Field(default_factory=list)
    questions: list[DesignQuestion] = Field(default_factory=list)


def unit_cases_view(draft: UnitTestDraft, ut_doc_id: str) -> str:
    """Numbered view of the UT document with the refs the cases get on commit."""
    lines: list[str] = []
    for number, case in enumerate(draft.ut_cases, start=1):
        steps = " ".join(f"{n}. {s}" for n, s in enumerate(case.steps, start=1))
        lines.append(
            f"{ut_doc_id}#item.{number} [UT] verifies {', '.join(case.verifies)} | "
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


def validate_unit_test_draft(
    draft: UnitTestDraft,
    detail: DetailDesignDraft,
    detail_doc_id: str,
    language: DocLanguage | None = None,
) -> list[str]:
    """Deterministic gate: refs resolve, steps are real, every detail item is tested or excluded."""
    detail_set = set(detail_refs(detail, detail_doc_id))
    errors: list[str] = []
    tested: set[str] = set()
    for index, case in enumerate(draft.ut_cases, start=1):
        for ref in case.verifies:
            if ref not in detail_set:
                errors.append(f"UT case {index}: {ref} is not a detail design item")
            tested.add(ref)
        if language is not None:
            for text in (case.precondition, case.input, case.expected, *case.steps):
                if text and (problem := language_problem(text, language)):
                    errors.append(f"UT case {index}: text {problem}")
                    break
    excluded: set[str] = set()
    for index, exclusion in enumerate(draft.exclusions, start=1):
        if exclusion.item_ref not in detail_set:
            errors.append(f"exclusion {index}: {exclusion.item_ref} is not a detail design item")
        if exclusion.item_ref in tested:
            errors.append(f"exclusion {index}: {exclusion.item_ref} is also tested")
        if language is not None and (problem := language_problem(exclusion.reason, language)):
            errors.append(f"exclusion {index}: reason {problem}")
        excluded.add(exclusion.item_ref)
    for index, question in enumerate(draft.questions, start=1):
        if question.ref not in detail_set:
            errors.append(f"question {index}: {question.ref} is not a detail design item")
    untested = sorted(detail_set - tested - excluded)
    if untested:
        errors.append(f"detail items with no UT case and no exclusion: {', '.join(untested)}")
    return errors


def system_prompt_for(language: DocLanguage, base: str | None = None) -> str:
    text = base if base is not None else load_system_prompt(PROMPT_PATH)
    return f"{text}\n\n## Output language\n\n{_LANGUAGE_INSTRUCTION[language]}"


def write_unit_tests(
    llm: LLM,
    detail: DetailDesignDraft,
    basic_items: Sequence[BasicDesignItem],
    language: DocLanguage,
    previous: UnitTestDraft | None,
    feedback: Sequence[str],
    detail_doc_id: str,
    ut_doc_id: str,
    system_prompt: str | None = None,
) -> LLMResult[UnitTestDraft]:
    """One tester call: first unit tests, or a revision with the pending feedback."""
    user = (
        f"<basic_design>\n{basic_view(basic_items)}\n</basic_design>\n\n"
        f"<detail_design>\n{detail_view(detail, detail_doc_id)}\n</detail_design>"
    )
    if previous is not None:
        listing = "\n".join(f"- {f}" for f in feedback)
        user += (
            f"\n\n<previous_tests>\n{unit_cases_view(previous, ut_doc_id)}\n"
            f"</previous_tests>\n\nThe previous tests were sent back for these reasons:\n"
            f"{listing}\nReturn corrected, complete tests."
        )
    return llm.generate(
        system=system_prompt_for(language, system_prompt),
        user=user,
        output=UnitTestDraft,
        tool_name=TOOL_NAME,
    )
