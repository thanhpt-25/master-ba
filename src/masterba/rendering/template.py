"""Template loading and company-override resolution (spec 02 sections 2 and 6)."""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from masterba.models import TemplateDefinition
from masterba.models.enums import DocType, TemplateSource
from masterba.rendering.bindings import (
    RULES_ADAPTER,
    Bindings,
    Rule,
    validate_bindings,
)
from masterba.rendering.errors import InvalidTemplateError, TemplateNotFoundError

logger = logging.getLogger(__name__)

DEFAULT_COMPANY = "default"


@dataclass(frozen=True)
class ResolvedTemplate:
    definition: TemplateDefinition
    bindings: Bindings
    rules: tuple[Rule, ...]
    sheet_map: dict[str, str]
    shell_path: Path


def _json_path(directory: Path, doc_type: DocType) -> Path:
    return directory / f"{doc_type.value}.template.json"


def load_template(json_path: Path) -> ResolvedTemplate:
    """Parse and validate one `<DOC_TYPE>.template.json` and locate its `.xlsx` shell."""
    try:
        definition = TemplateDefinition.model_validate(json.loads(json_path.read_text("utf-8")))
        bindings = Bindings.model_validate(definition.cell_bindings)
        rules = tuple(RULES_ADAPTER.validate_python(definition.validation_rules))
    except (OSError, ValueError, ValidationError) as exc:
        raise InvalidTemplateError(f"{json_path}: {exc}") from exc
    if json_path.name != f"{definition.doc_type.value}.template.json":
        raise InvalidTemplateError(
            f"{json_path.name} does not match doc_type {definition.doc_type}"
        )
    sheet_map = {str(k): str(v) for k, v in definition.sheet_map.items()}
    validate_bindings(bindings, definition.doc_type, sheet_map)
    shell_path = json_path.with_name(f"{definition.doc_type.value}.xlsx")
    if not shell_path.exists():
        raise InvalidTemplateError(f"missing workbook shell {shell_path}")
    return ResolvedTemplate(definition, bindings, rules, sheet_map, shell_path)


def resolve_template(templates_root: Path, company_id: str, doc_type: DocType) -> ResolvedTemplate:
    """Company template when confirmed, otherwise the default one."""
    if Path(company_id).name != company_id or company_id in {"", ".", ".."}:
        raise InvalidTemplateError(f"invalid company id {company_id!r}")
    if company_id != DEFAULT_COMPANY:
        company_dir = templates_root / "companies" / company_id
        candidate = _json_path(company_dir, doc_type)
        if candidate.exists():
            template = load_template(candidate)
            confirmed = (company_dir / f"{doc_type.value}.confirmed").exists()
            if template.definition.source is not TemplateSource.CALIBRATED_FROM_SAMPLE or confirmed:
                return template
            logger.warning("ignoring unconfirmed template %s; using default", candidate)
    default = _json_path(templates_root / DEFAULT_COMPANY, doc_type)
    if not default.exists():
        raise TemplateNotFoundError(f"no template for {doc_type.value} (looked for {default})")
    return load_template(default)
