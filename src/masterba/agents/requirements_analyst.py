"""requirements-analyst-agent: customer intake text -> BRD draft (spec 03 section 3).

The model returns a *draft* without ids. Everything here is deterministic around that one call:
the prompt, the validation gate and the single retry. Ids are assigned later by the pipeline.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Self

from pydantic import Field, model_validator

from masterba.llm import LLM, LLMOutputError
from masterba.models.base import FrozenModel
from masterba.models.enums import DocLanguage, ReqCategory, Scope

REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_PATH = REPO_ROOT / "agents" / "requirements-analyst.md"
TOOL_NAME = "submit_brd"
MAX_ATTEMPTS = 2
MAX_CJK_SHARE_IN_ENGLISH = 0.3
_CJK = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uff66-\uff9f]")
_LANGUAGE_INSTRUCTION = {
    DocLanguage.JA: "Write `title`, `description` and the text of every open question in "
    "Japanese (日本語).",
    DocLanguage.EN: "Write `title`, `description` and the text of every open question in English.",
}


class DraftRequirement(FrozenModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: ReqCategory
    scope: Scope
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    evidence_quote: str = Field(min_length=1)

    @model_validator(mode="after")
    def _ordered_lines(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not be before start_line")
        return self


class OpenQuestion(FrozenModel):
    question: str = Field(min_length=1)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def _ordered_lines(self) -> Self:
        if self.end_line < self.start_line:
            raise ValueError("end_line must not be before start_line")
        return self


class BrdDraft(FrozenModel):
    requirements: list[DraftRequirement] = Field(min_length=1)
    open_questions: list[OpenQuestion] = Field(default_factory=list)


class DraftRejectedError(Exception):
    """The model's draft failed validation even after the retry."""

    def __init__(self, errors: list[str]) -> None:
        super().__init__("draft rejected: " + "; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Analysis:
    draft: BrdDraft
    attempts: int
    input_tokens: int
    output_tokens: int


def load_system_prompt(path: Path = PROMPT_PATH) -> str:
    """Read the agent prompt, dropping the YAML frontmatter."""
    text = path.read_text(encoding="utf-8")
    if text.startswith("---\n"):
        _, _, text = text[4:].partition("\n---\n")
    return text.strip()


def intake_lines(text: str) -> list[str]:
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def number_lines(text: str) -> str:
    return "\n".join(f"{n:>4}| {line}" for n, line in enumerate(intake_lines(text), start=1))


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _language_problem(text: str, language: DocLanguage) -> str | None:
    """Loose check: it can only catch text clearly in the wrong script, not prove a language."""
    cjk = len(_CJK.findall(text))
    if language is DocLanguage.JA and cjk == 0:
        return "must be written in Japanese but has no Japanese characters"
    if language is DocLanguage.EN and cjk > MAX_CJK_SHARE_IN_ENGLISH * max(len(text), 1):
        return "must be written in English but is mostly Japanese"
    return None


def validate_draft(
    draft: BrdDraft, intake_text: str, language: DocLanguage | None = None
) -> list[str]:
    """Deterministic acceptance gate; returns one message per problem (empty = accepted)."""
    lines = intake_lines(intake_text)
    total = len(lines)
    errors: list[str] = []
    seen: dict[str, int] = {}
    for index, req in enumerate(draft.requirements, start=1):
        if req.end_line > total:
            errors.append(
                f"requirement {index}: lines {req.start_line}-{req.end_line} are outside "
                f"the intake ({total} lines)"
            )
        else:
            cited = _collapse(" ".join(lines[req.start_line - 1 : req.end_line]))
            if _collapse(req.evidence_quote) not in cited:
                errors.append(
                    f"requirement {index}: evidence_quote is not found in "
                    f"lines {req.start_line}-{req.end_line}"
                )
        if language is not None and (problem := _language_problem(req.description, language)):
            errors.append(f"requirement {index}: description {problem}")
        key = _collapse(req.title).lower()
        if key in seen:
            errors.append(f"requirement {index}: title duplicates requirement {seen[key]}")
        seen.setdefault(key, index)
    for index, question in enumerate(draft.open_questions, start=1):
        if question.end_line > total:
            errors.append(
                f"open question {index}: lines {question.start_line}-{question.end_line} "
                f"are outside the intake ({total} lines)"
            )
        if language is not None and (problem := _language_problem(question.question, language)):
            errors.append(f"open question {index}: text {problem}")
    return errors


def uncovered_lines(draft: BrdDraft, intake_text: str) -> list[int]:
    """Non-blank intake lines that no requirement and no open question cites."""
    lines = intake_lines(intake_text)
    covered: set[int] = set()
    cited: list[DraftRequirement | OpenQuestion] = [*draft.requirements, *draft.open_questions]
    for item in cited:
        covered.update(range(item.start_line, item.end_line + 1))
    return [n for n, line in enumerate(lines, start=1) if line.strip() and n not in covered]


def _user_message(intake_text: str, errors: list[str]) -> str:
    message = f"<intake>\n{number_lines(intake_text)}\n</intake>"
    if errors:
        listing = "\n".join(f"- {e}" for e in errors)
        message += (
            "\n\nYour previous draft was rejected for these reasons:\n"
            f"{listing}\nReturn a corrected, complete draft."
        )
    return message


def system_prompt_for(language: DocLanguage, base: str | None = None) -> str:
    """The agent prompt plus the project's output-language section."""
    text = base if base is not None else load_system_prompt()
    return (
        f"{text}\n\n## Output language\n\n{_LANGUAGE_INSTRUCTION[language]} Keep "
        "`evidence_quote` exactly as written in the intake, in whatever language the intake uses."
    )


def analyse_intake(
    llm: LLM, intake_text: str, language: DocLanguage, system_prompt: str | None = None
) -> Analysis:
    """One model call plus at most one retry; raises `DraftRejectedError` if still invalid."""
    system = system_prompt_for(language, system_prompt)
    errors: list[str] = []
    tokens_in = tokens_out = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = llm.generate(
                system=system,
                user=_user_message(intake_text, errors),
                output=BrdDraft,
                tool_name=TOOL_NAME,
            )
        except LLMOutputError as exc:
            errors = [str(exc)]
            continue
        tokens_in += result.input_tokens
        tokens_out += result.output_tokens
        errors = validate_draft(result.value, intake_text, language)
        if not errors:
            return Analysis(result.value, attempt, tokens_in, tokens_out)
    raise DraftRejectedError(errors)
