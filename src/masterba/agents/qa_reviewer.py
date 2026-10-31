"""qa-reviewer-agent: one stage-neutral reviewer, driven by a checklist file (spec 04 section 4).

The model returns issues only. The verdict is computed from them (`QaReport.passed`), so a
report that contradicts itself cannot exist. Only the checklist differs between stages.
"""

import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, ValidationError, model_validator

from masterba.agents.requirements_analyst import REPO_ROOT, load_system_prompt
from masterba.llm import LLM, LLMOutputError
from masterba.models.base import FrozenModel
from masterba.models.enums import DocLanguage, DocType
from masterba.models.ids import ItemRef

PROMPT_PATH = REPO_ROOT / "agents" / "qa-reviewer.md"
CHECKLIST_DIR = REPO_ROOT / "skills" / "qa-review" / "checklists"
TOOL_NAME = "submit_qa_report"
MAX_ATTEMPTS = 2
Severity = Literal["blocking", "advisory"]
_RANK = {"advisory": 0, "blocking": 1}
_LANGUAGE_INSTRUCTION = {
    DocLanguage.JA: "Write the `message` of every issue in Japanese (日本語).",
    DocLanguage.EN: "Write the `message` of every issue in English.",
}


class Check(FrozenModel):
    id: str = Field(min_length=1)
    severity: Severity
    text: str = Field(min_length=1)


class Checklist(FrozenModel):
    stage: str = Field(min_length=1)
    checks: list[Check] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_ids(self) -> Self:
        ids = [c.id for c in self.checks]
        if len(ids) != len(set(ids)):
            raise ValueError("checklist ids must be unique")
        return self


class QaIssue(FrozenModel):
    checklist_id: str = Field(min_length=1)
    severity: Severity
    ref: ItemRef | None = None
    message: str = Field(min_length=1)
    action_required: str | None = None
    customer_question: bool = False


class QaReport(FrozenModel):
    issues: list[QaIssue] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not any(i.severity == "blocking" for i in self.issues)


class QaOutputInvalidError(Exception):
    """The reviewer's report was unusable even after one retry."""

    def __init__(self, errors: list[str], input_tokens: int = 0, output_tokens: int = 0) -> None:
        super().__init__("qa output invalid: " + "; ".join(errors))
        self.errors = errors
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


@dataclass(frozen=True)
class QaReview:
    report: QaReport
    input_tokens: int
    output_tokens: int
    attempts: int
    notes: tuple[str, ...] = ()
    customer_questions: tuple[str, ...] = ()


def checklist_path(stage: DocType | str) -> Path:
    """Checklist file of a document type, or of a named checklist such as ``"tests"``."""
    stem = stage.value.lower() if isinstance(stage, DocType) else stage
    return CHECKLIST_DIR / f"{stem}.toml"


def load_checklist(path: Path) -> Checklist:
    return Checklist.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))


def validate_report(
    report: QaReport, checklist: Checklist, item_counts: Mapping[str, int]
) -> list[str]:
    known = {c.id for c in checklist.checks}
    errors: list[str] = []
    for index, issue in enumerate(report.issues, start=1):
        if issue.checklist_id not in known:
            errors.append(f"issue {index}: unknown checklist_id {issue.checklist_id!r}")
        if issue.ref is not None:
            head, _, number = issue.ref.partition("#item.")
            if not 1 <= int(number) <= item_counts.get(head, 0):
                errors.append(f"issue {index}: ref {issue.ref} is not an item of the draft")
    return errors


def cap_severity(report: QaReport, checklist: Checklist) -> QaReport:
    """The model may downgrade a check's severity, never raise it."""
    ceiling = {c.id: c.severity for c in checklist.checks}
    issues = [
        i
        if _RANK[i.severity] <= _RANK[ceiling[i.checklist_id]]
        else i.model_copy(update={"severity": ceiling[i.checklist_id]})
        for i in report.issues
    ]
    return QaReport(issues=issues)


def _downgrade_reason(issue: QaIssue) -> str | None:
    if issue.severity != "blocking":
        return None
    if issue.customer_question:
        return "customer question"
    if not (issue.action_required or "").strip():
        return "no action required"
    return None


def normalise_report(report: QaReport) -> tuple[QaReport, list[str], list[str]]:
    """Blocking means "change this": downgrade issues that name no change (spec 11 section 1.3).

    Returns the report, one note per downgrade and the customer questions it found.
    """
    issues: list[QaIssue] = []
    notes: list[str] = []
    questions: list[str] = []
    for issue in report.issues:
        reason = _downgrade_reason(issue)
        if issue.customer_question:
            questions.append(f"{issue.ref or 'document'}: {issue.message}")
        if reason is None:
            issues.append(issue)
            continue
        issues.append(issue.model_copy(update={"severity": "advisory"}))
        notes.append(f"[{issue.checklist_id}] {issue.ref or 'document'}: downgraded ({reason})")
    return QaReport(issues=issues), notes, questions


def system_prompt_for(checklist: Checklist, language: DocLanguage, base: str | None = None) -> str:
    text = base if base is not None else load_system_prompt(PROMPT_PATH)
    checks = "\n".join(f"- {c.id} ({c.severity}): {c.text}" for c in checklist.checks)
    return (
        f"{text}\n\n## Checklist for the {checklist.stage} stage\n\n{checks}\n\n"
        f"## Output language\n\n{_LANGUAGE_INSTRUCTION[language]}"
    )


def _user_message(upstream: str, draft_view: str, errors: list[str]) -> str:
    message = f"<upstream>\n{upstream}\n</upstream>\n\n<draft>\n{draft_view}\n</draft>"
    if errors:
        listing = "\n".join(f"- {e}" for e in errors)
        message += f"\n\nYour previous report was unusable:\n{listing}\nReturn a corrected report."
    return message


def review(
    llm: LLM,
    *,
    checklist: Checklist,
    item_counts: Mapping[str, int],
    upstream: str,
    draft_view: str,
    language: DocLanguage,
    system_prompt: str | None = None,
) -> QaReview:
    """Review a draft against a checklist; one retry on an unusable report."""
    system = system_prompt_for(checklist, language, system_prompt)
    errors: list[str] = []
    tokens_in = tokens_out = 0
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = llm.generate(
                system=system,
                user=_user_message(upstream, draft_view, errors),
                output=QaReport,
                tool_name=TOOL_NAME,
            )
        except (LLMOutputError, ValidationError) as exc:
            errors = [str(exc)]
            continue
        tokens_in += result.input_tokens
        tokens_out += result.output_tokens
        errors = validate_report(result.value, checklist, item_counts)
        if not errors:
            report, notes, questions = normalise_report(cap_severity(result.value, checklist))
            return QaReview(report, tokens_in, tokens_out, attempt, tuple(notes), tuple(questions))
    raise QaOutputInvalidError(errors, tokens_in, tokens_out)
