"""Prose sections of a draft (背景・目的, 制約事項, ...) and their gate (spec 19 part 2).

A writer may return a section only when its sources support it; a section without sources, or
with a source outside what the writer was given, is sent back. A missing section is allowed: the
workbook then says the input does not state it, which is better than invented text.
"""

import re
from collections.abc import Callable, Collection, Sequence

from pydantic import Field

from masterba.models import DocumentSection
from masterba.models.base import FrozenModel
from masterba.models.enums import DocLanguage, DocType, SectionKey
from masterba.models.payloads import SECTIONS_BY_TYPE

SECTION_TITLES: dict[SectionKey, str] = {
    SectionKey.BACKGROUND: "背景・目的",
    SectionKey.CONSTRAINTS: "制約事項",
    SectionKey.SYSTEM_OVERVIEW: "システム概要",
    SectionKey.IT_VIEWPOINTS: "結合テスト観点",
}
MAX_SECTION_CHARS = 4_000
_LINES = re.compile(r"^L(\d+)(?:-L(\d+))?$")


class DraftSection(FrozenModel):
    key: SectionKey
    body: str = Field(min_length=1)
    sources: list[str] = Field(min_length=1)


def line_range(source: str) -> tuple[int, int] | None:
    """`L12` or `L12-L14` as (12, 12) or (12, 14); None for anything else."""
    match = _LINES.match(source.strip())
    if match is None:
        return None
    start = int(match[1])
    end = int(match[2] or start)
    return (start, end) if 1 <= start <= end else None


def validate_sections(
    sections: Sequence[DraftSection],
    doc_type: DocType,
    *,
    language: DocLanguage | None,
    known_sources: Collection[str] | None = None,
    line_count: int | None = None,
) -> list[str]:
    """Gate for draft sections: allowed keys, once each, real sources, right language.

    A BRD cites intake lines (`line_count`); later documents cite upstream ids (`known_sources`).
    """
    # Imported here: requirements_analyst imports this module for `DraftSection`.
    from masterba.agents.requirements_analyst import language_problem

    allowed = SECTIONS_BY_TYPE.get(doc_type, ())
    errors: list[str] = []
    seen: set[SectionKey] = set()
    for section in sections:
        name = f"section {section.key.value}"
        if section.key not in allowed:
            keys = ", ".join(k.value for k in allowed) or "none"
            errors.append(f"{name}: not a section of this document (allowed: {keys})")
        if section.key in seen:
            errors.append(f"{name}: given twice")
        seen.add(section.key)
        if len(section.body) > MAX_SECTION_CHARS:
            errors.append(f"{name}: longer than {MAX_SECTION_CHARS} characters")
        for source in section.sources:
            if line_count is not None:
                lines = line_range(source)
                if lines is None:
                    errors.append(f"{name}: source {source!r} is not a line range like L3-L5")
                elif lines[1] > line_count:
                    errors.append(f"{name}: source {source} is outside the intake")
            elif known_sources is not None and source not in known_sources:
                errors.append(f"{name}: source {source} is not an item you were given")
        if language is not None and (problem := language_problem(section.body, language)):
            errors.append(f"{name}: body {problem}")
    return errors


def to_content(
    sections: Sequence[DraftSection], convert: Callable[[str], str] = str
) -> list[DocumentSection]:
    """Stored sections in the order of `SectionKey`, with each source passed through `convert`."""
    order = list(SectionKey)
    return [
        DocumentSection(key=s.key, body=s.body, sources=[convert(x) for x in s.sources])
        for s in sorted(sections, key=lambda s: order.index(s.key))
    ]


def sections_view(sections: Sequence[DraftSection | DocumentSection]) -> str:
    """Lines for a draft view shown to QA or to the writer on a revision."""
    if not sections:
        return ""
    lines = ["Document sections:"]
    lines.extend(
        f"- [{s.key.value}] {SECTION_TITLES[s.key]}: {' '.join(s.body.split())} "
        f"(sources {', '.join(s.sources)})"
        for s in sections
    )
    return "\n".join(lines)


def section_ref(doc_id: str, key: SectionKey) -> str:
    """How a later document cites a section of an upstream one, e.g. `DOC-BRD-0001#background`."""
    return f"{doc_id}#{key.value}"


def upstream_sections_block(doc_id: str, sections: Sequence[DocumentSection]) -> str:
    """`<upstream_sections>` for a writer; empty when the upstream document has none."""
    if not sections:
        return ""
    lines = [
        f"{section_ref(doc_id, s.key)} {SECTION_TITLES[s.key]}: {' '.join(s.body.split())}"
        for s in sections
    ]
    return "<upstream_sections>\n" + "\n".join(lines) + "\n</upstream_sections>"
