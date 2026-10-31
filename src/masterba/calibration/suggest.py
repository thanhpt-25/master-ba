"""Optional model refinement of the heuristic mapping (spec 09 section 3.1)."""

import json
from dataclasses import dataclass

from pydantic import ValidationError

from masterba.agents.requirements_analyst import REPO_ROOT, load_system_prompt
from masterba.calibration.heuristic import SYNONYMS, fields_for
from masterba.calibration.models import MappingDraft, WorkbookProfile
from masterba.calibration.validate import validate_mapping
from masterba.llm import LLM, LLMError, LLMOutputError
from masterba.models.enums import DocType

PROMPT_PATH = REPO_ROOT / "agents" / "template-calibrator.md"
TOOL_NAME = "submit_mapping"
MAX_ATTEMPTS = 2
PROFILE_ROWS_FOR_MODEL = 12


@dataclass(frozen=True)
class Suggestion:
    draft: MappingDraft
    used_model: bool
    message: str | None = None


def fields_view(doc_type: DocType) -> str:
    """The fields a column may show, with the labels the heuristic already knows for them."""
    lines = []
    for field in sorted(fields_for(doc_type)):
        known = ", ".join(SYNONYMS.get(field, ())) or "-"
        lines.append(f"- {field} (usual labels: {known})")
    return "\n".join(lines)


def profile_view(profile: WorkbookProfile) -> str:
    """The profile as JSON, with only the first rows of each sheet."""
    sheets = [
        s.model_copy(update={"rows": s.rows[:PROFILE_ROWS_FOR_MODEL]}) for s in profile.sheets
    ]
    return json.dumps(
        profile.model_copy(update={"sheets": sheets}).model_dump(mode="json"), ensure_ascii=False
    )


def _user(
    profile: WorkbookProfile, heuristic: MappingDraft, doc_type: DocType, errors: list[str]
) -> str:
    message = (
        f"<document_type>{doc_type.value}</document_type>\n\n"
        f"<item_fields>\n{fields_view(doc_type)}\n</item_fields>\n\n"
        f"<sample_profile>\n{profile_view(profile)}\n</sample_profile>\n\n"
        f"<heuristic_draft>\n{heuristic.model_dump_json(indent=1)}\n</heuristic_draft>"
    )
    if errors:
        listing = "\n".join(f"- {e}" for e in errors)
        message += (
            f"\n\nYour previous mapping was rejected:\n{listing}\nReturn a corrected mapping."
        )
    return message


def suggest_mapping(
    llm: LLM, profile: WorkbookProfile, heuristic: MappingDraft, doc_type: DocType
) -> Suggestion:
    """The model's validated mapping, or the heuristic one with a message saying why."""
    system = load_system_prompt(PROMPT_PATH)
    errors: list[str] = []
    for _ in range(MAX_ATTEMPTS):
        try:
            result = llm.generate(
                system=system,
                user=_user(profile, heuristic, doc_type, errors),
                output=MappingDraft,
                tool_name=TOOL_NAME,
            )
        except (LLMOutputError, ValidationError) as exc:
            errors = [str(exc)]
            continue
        except LLMError as exc:
            return Suggestion(heuristic, False, f"the model could not be used: {exc}")
        errors = validate_mapping(result.value, profile, doc_type)
        if not errors:
            kept = [*result.value.warnings, *heuristic.warnings]
            draft = result.value.model_copy(update={"warnings": list(dict.fromkeys(kept))})
            return Suggestion(draft, True)
    return Suggestion(
        heuristic, False, "the model's mapping was rejected twice: " + "; ".join(errors)
    )
