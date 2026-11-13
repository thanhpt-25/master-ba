"""Company template folders: calibrate, edit, check, preview, confirm (spec 09 sections 5 and 6)."""

import json
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from masterba.calibration.build import build_template
from masterba.calibration.heuristic import VALUE_MAP_FIELDS
from masterba.calibration.models import MappingDraft
from masterba.calibration.preview import compare_layout, demo_document, render_preview
from masterba.calibration.profile import CalibrationError, heuristic_draft, profile_workbook
from masterba.calibration.suggest import suggest_mapping
from masterba.calibration.validate import advisory_warnings, validate_mapping
from masterba.llm import LLM
from masterba.models.enums import DocType
from masterba.models.ids import COMPANY_ID_PATTERN
from masterba.rendering import InvalidTemplateError, load_template
from masterba.trace_store import NotFoundError, ProjectStore, get_document
from masterba.trace_store.git import commit_paths, ensure_ready

COMPANY = COMPANY_ID_PATTERN
Clock = Callable[[], datetime]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Paths:
    folder: Path
    doc_type: DocType

    def _file(self, suffix: str) -> Path:
        return self.folder / f"{self.doc_type.value}{suffix}"

    @property
    def definition(self) -> Path:
        return self._file(".template.json")

    @property
    def shell(self) -> Path:
        return self._file(".xlsx")

    @property
    def sample(self) -> Path:
        return self._file(".sample.xlsx")

    @property
    def calibration(self) -> Path:
        return self._file(".calibration.json")

    @property
    def confirmed(self) -> Path:
        return self._file(".confirmed")

    @property
    def preview(self) -> Path:
        return self._file(".preview.xlsx")


@dataclass(frozen=True)
class CalibrationResult:
    draft: MappingDraft
    messages: tuple[str, ...]
    files: tuple[Path, ...]


@dataclass(frozen=True)
class PreviewResult:
    path: Path
    differences: tuple[str, ...]


def valid_company(company: str) -> str:
    if not re.fullmatch(COMPANY, company) or company == "default":
        raise CalibrationError(
            "a company id has 1 to 40 letters, digits, dots, dashes or underscores; "
            "'default' is the baseline and cannot be calibrated"
        )
    return company


def paths_for(root: Path, company: str, doc_type: DocType) -> Paths:
    return Paths(root / "templates" / "companies" / valid_company(company), doc_type)


def state_of(root: Path, company: str, doc_type: DocType) -> str:
    paths = paths_for(root, company, doc_type)
    if not paths.definition.exists():
        return "none"
    return "confirmed" if paths.confirmed.exists() else "draft"


def load_draft(root: Path, company: str, doc_type: DocType) -> MappingDraft:
    paths = paths_for(root, company, doc_type)
    if not paths.calibration.exists():
        raise NotFoundError(f"no calibrated template of {doc_type.value} for {company}")
    return MappingDraft.model_validate_json(paths.calibration.read_text("utf-8"))


def _write(root: Path, paths: Paths, draft: MappingDraft, company: str, message: str) -> list[Path]:
    built = build_template(draft, paths.sample, company)
    paths.definition.write_text(
        json.dumps(
            built.definition.model_dump(mode="json"), sort_keys=True, indent=2, ensure_ascii=False
        )
        + "\n",
        encoding="utf-8",
    )
    paths.shell.write_bytes(built.shell)
    paths.calibration.write_text(draft.model_dump_json(indent=2) + "\n", encoding="utf-8")
    removed = paths.confirmed.exists()
    paths.confirmed.unlink(missing_ok=True)
    files = [paths.definition, paths.shell, paths.sample, paths.calibration]
    commit_paths(root, [*files, paths.confirmed] if removed else files, message)
    return files


def calibrate(
    root: Path,
    company: str,
    doc_type: DocType,
    sample: Path,
    *,
    llm: LLM | None = None,
    replace: bool = False,
) -> CalibrationResult:
    """Read the sample, propose a mapping and write a draft template (never a confirmed one)."""
    paths = paths_for(root, company, doc_type)
    ensure_ready(root)
    if state_of(root, company, doc_type) == "confirmed" and not replace:
        raise CalibrationError(
            f"{doc_type.value} of {company} is confirmed; calibrating again needs --replace "
            "and the new draft must be confirmed again"
        )
    profile = profile_workbook(sample, doc_type)
    draft = heuristic_draft(profile, doc_type, sample)
    messages: list[str] = []
    if llm is not None:
        outcome = suggest_mapping(llm, profile, draft, doc_type)
        draft = outcome.draft
        messages.append(
            "the model refined the mapping" if outcome.used_model else str(outcome.message)
        )
    errors = validate_mapping(draft, profile, doc_type)
    if errors:
        raise CalibrationError("; ".join(errors))
    draft = draft.model_copy(
        update={"warnings": list(dict.fromkeys([*draft.warnings, *advisory_warnings(draft)]))}
    )
    paths.folder.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(sample, paths.sample)
    files = _write(root, paths, draft, company, f"template({company}): calibrate {doc_type.value}")
    return CalibrationResult(draft, tuple(messages), tuple(files))


def set_column(
    root: Path, company: str, doc_type: DocType, sheet: str, col: str, field: str | None
) -> MappingDraft:
    """Assign a field to a column (or clear it); re-validated, rebuilt, confirmation removed."""
    paths = paths_for(root, company, doc_type)
    ensure_ready(root)
    draft = load_draft(root, company, doc_type)
    table = next((t for t in draft.tables if t.sheet == sheet), None)
    if table is None or not any(c.col == col for c in table.columns):
        raise CalibrationError(f"'{sheet}' has no mapped column {col}")
    columns = [
        c.model_copy(
            update={"field": field, "value_map": VALUE_MAP_FIELDS.get(field) if field else None}
        )
        if c.col == col
        else c
        for c in table.columns
    ]
    changed = draft.model_copy(
        update={
            "tables": [
                t.model_copy(update={"columns": columns}) if t is table else t for t in draft.tables
            ]
        }
    )
    profile = profile_workbook(paths.sample, doc_type)
    errors = validate_mapping(changed, profile, doc_type)
    if errors:
        raise CalibrationError("; ".join(errors))
    _write(root, paths, changed, company, f"template({company}): edit {doc_type.value}")
    return changed


def check(root: Path, company: str, doc_type: DocType) -> list[str]:
    """Problems the renderer's own loader and the mapping gate would report (empty = fine)."""
    paths = paths_for(root, company, doc_type)
    if not paths.definition.exists():
        return [f"no template of {doc_type.value} for {company}"]
    problems: list[str] = []
    try:
        load_template(paths.definition)
    except InvalidTemplateError as exc:
        problems.append(str(exc))
    draft = load_draft(root, company, doc_type)
    problems.extend(validate_mapping(draft, profile_workbook(paths.sample, doc_type), doc_type))
    return problems


def confirm(
    root: Path, company: str, doc_type: DocType, by: str, now: Clock = _now
) -> dict[str, str]:
    """Mark the draft as the company's official template (refused while `check` fails)."""
    if not by.strip():
        raise CalibrationError("say who confirms the template")
    paths = paths_for(root, company, doc_type)
    ensure_ready(root)
    problems = check(root, company, doc_type)
    if problems:
        raise CalibrationError("; ".join(problems))
    marker = {"by": by.strip(), "at": now().astimezone(UTC).isoformat(timespec="seconds")}
    paths.confirmed.write_text(json.dumps(marker, sort_keys=True) + "\n", encoding="utf-8")
    commit_paths(root, [paths.confirmed], f"template({company}): confirm {doc_type.value}")
    return marker


def unconfirm(root: Path, company: str, doc_type: DocType) -> None:
    paths = paths_for(root, company, doc_type)
    ensure_ready(root)
    if not paths.confirmed.exists():
        raise CalibrationError("the template is not confirmed")
    paths.confirmed.unlink()
    commit_paths(root, [paths.confirmed], f"template({company}): unconfirm {doc_type.value}")


def preview(
    root: Path, company: str, doc_type: DocType, project: ProjectStore | None = None
) -> PreviewResult:
    """Render the draft with a project document (or a demo one) and compare it with the sample."""
    paths = paths_for(root, company, doc_type)
    template = load_template(paths.definition)
    draft = load_draft(root, company, doc_type)
    if project is not None:
        try:
            document, content = get_document(project, f"DOC-{doc_type.value}-0001")
        except NotFoundError:
            document, content = demo_document(doc_type)
    else:
        document, content = demo_document(doc_type)
    render_preview(template, document, content, paths.preview)
    return PreviewResult(paths.preview, tuple(compare_layout(paths.sample, paths.preview, draft)))


def list_templates(root: Path, company: str | None = None) -> list[dict[str, str]]:
    base = root / "templates" / "companies"
    if not base.exists():
        return []
    found: list[dict[str, str]] = []
    for folder in sorted(p for p in base.iterdir() if p.is_dir()):
        if company is not None and folder.name != company:
            continue
        for doc_type in DocType:
            state = state_of(root, folder.name, doc_type) if COMPANY.match(folder.name) else "none"
            if state != "none":
                found.append({"company": folder.name, "doc_type": doc_type.value, "state": state})
    return found
