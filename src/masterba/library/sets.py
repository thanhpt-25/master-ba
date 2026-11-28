"""Template sets on disk: list, clone, keep the built-in set current (spec 29 sections 1.1, 1.3)."""

import json
import shutil
from pathlib import Path
from typing import Any

from masterba.calibration.profile import CalibrationError
from masterba.calibration.store import state_of, valid_company
from masterba.models.enums import DocType
from masterba.rendering.template import DEFAULT_COMPANY
from masterba.trace_store.git import commit_paths, ensure_ready

BUNDLED = Path(__file__).resolve().parents[3] / "templates"
# Files of a set that a clone copies (previews are scratch and stay behind).
CLONED_SUFFIXES = (".template.json", ".xlsx", ".sample.xlsx", ".calibration.json", ".confirmed")


def set_types(root: Path, set_id: str) -> dict[str, str]:
    """Doc type to `confirmed` or `draft` for a company set; every type for the built-in set."""
    if set_id == DEFAULT_COMPANY:
        return {t.value: "confirmed" for t in DocType}
    found: dict[str, str] = {}
    for doc_type in DocType:
        state = state_of(root, set_id, doc_type)
        if state != "none":
            found[doc_type.value] = state
    return found


def clone(root: Path, source: str, target: str) -> list[Path]:
    """Copy a company set to a new folder and commit it; the caller records the new owner."""
    if source == DEFAULT_COMPANY:
        raise CalibrationError("the built-in set cannot be cloned; calibrate a sample instead")
    valid_company(target)
    src = root / "templates" / "companies" / valid_company(source)
    dst = root / "templates" / "companies" / target
    if not src.is_dir():
        raise CalibrationError(f"no template set {source}")
    if dst.exists():
        raise CalibrationError(f"template set {target} already exists")
    ensure_ready(root)
    dst.mkdir(parents=True)
    written: list[Path] = []
    for doc_type in DocType:
        for suffix in CLONED_SUFFIXES:
            name = f"{doc_type.value}{suffix}"
            origin = src / name
            if not origin.is_file():
                continue
            copy = dst / name
            if suffix == ".template.json":
                data: dict[str, Any] = json.loads(origin.read_text("utf-8"))
                data["company_id"] = target
                text = json.dumps(data, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
                copy.write_text(text, encoding="utf-8")
            else:
                shutil.copyfile(origin, copy)
            written.append(copy)
    if not written:
        dst.rmdir()
        raise CalibrationError(f"template set {source} has no files")
    commit_paths(root, written, f"template({target}): clone of {source}")
    return written


def sync_builtin(root: Path, bundled: Path = BUNDLED) -> list[str]:
    """Copy the bundled built-in templates over the work tree's copy where they differ."""
    source = bundled / DEFAULT_COMPANY
    target = root / "templates" / DEFAULT_COMPANY
    if not source.is_dir() or source.resolve() == target.resolve():
        return []
    changed: list[str] = []
    for path in sorted(source.iterdir()):
        if not path.is_file():
            continue
        copy = target / path.name
        if copy.is_file() and copy.read_bytes() == path.read_bytes():
            continue
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, copy)
        changed.append(path.name)
    return changed
