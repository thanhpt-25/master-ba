"""What a template set prints compared with the built-in set (spec 29 section 2). No LLM."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from masterba.models.enums import DocType
from masterba.rendering.bindings import Bindings
from masterba.rendering.template import DEFAULT_COMPANY, resolve_template


@dataclass(frozen=True)
class CoverageRow:
    kind: str
    printed: bool

    def to_json(self) -> dict[str, Any]:
        return {"kind": self.kind, "printed": self.printed}


@dataclass(frozen=True)
class TypeCoverage:
    doc_type: DocType
    state: str  # "calibrated" or "fallback" (the built-in template is used)
    rows: tuple[CoverageRow, ...]

    @property
    def dropped(self) -> list[str]:
        return [r.kind for r in self.rows if not r.printed]

    def to_json(self) -> dict[str, Any]:
        return {
            "doc_type": self.doc_type.value,
            "state": self.state,
            "rows": [r.to_json() for r in self.rows],
            "dropped": self.dropped,
        }


@dataclass(frozen=True)
class Coverage:
    set_id: str
    types: tuple[TypeCoverage, ...]

    @property
    def gaps(self) -> int:
        return sum(len(t.dropped) for t in self.types)

    def to_json(self) -> dict[str, Any]:
        return {
            "set": self.set_id,
            "gaps": self.gaps,
            "types": [t.to_json() for t in self.types],
        }


# Header sources that print the same value.
SAME_VALUE = {"$document.version_label": "$document.version", "$project.name": "$project.id"}


def kinds(bindings: Bindings) -> list[str]:
    """The data kinds a template prints, in a stable order."""
    found = [f"header:{SAME_VALUE.get(h.source, h.source)}" for h in bindings.header]
    for table in bindings.tables:
        found += [f"field:{c.field}" for c in table.columns if c.field]
    found += [f"list:{listed.source}" for listed in bindings.lists]
    found += [f"section:{s.key.value}" for s in bindings.sections]
    return list(dict.fromkeys(found))


def type_coverage(templates_root: Path, set_id: str, doc_type: DocType) -> TypeCoverage:
    builtin = resolve_template(templates_root, DEFAULT_COMPANY, doc_type)
    used = resolve_template(templates_root, set_id, doc_type)
    expected = kinds(builtin.bindings)
    if used.shell_path == builtin.shell_path:
        return TypeCoverage(doc_type, "fallback", tuple(CoverageRow(k, True) for k in expected))
    printed = set(kinds(used.bindings))
    rows = tuple(CoverageRow(k, k in printed) for k in expected)
    return TypeCoverage(doc_type, "calibrated", rows)


def coverage(templates_root: Path, set_id: str, doc_types: list[DocType]) -> Coverage:
    return Coverage(set_id, tuple(type_coverage(templates_root, set_id, t) for t in doc_types))
