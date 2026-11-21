"""Draft sections and their gate (spec 19 part 2, section 7)."""

from masterba.agents.sections import (
    DraftSection,
    line_range,
    section_ref,
    sections_view,
    to_content,
    upstream_sections_block,
    validate_sections,
)
from masterba.models import DocumentSection
from masterba.models.enums import DocLanguage, DocType, SectionKey

BG, CONSTRAINTS = SectionKey.BACKGROUND, SectionKey.CONSTRAINTS


def section(key: SectionKey, *sources: str, body: str = "勤怠管理を一元化する。") -> DraftSection:
    return DraftSection(key=key, body=body, sources=list(sources))


def test_line_ranges() -> None:
    assert line_range("L3") == (3, 3)
    assert line_range("L3-L5") == (3, 5)
    assert line_range("L5-L3") is None
    assert line_range("3-5") is None


def test_a_brd_section_must_cite_intake_lines() -> None:
    ok = [section(BG, "L1-L2"), section(CONSTRAINTS, "L3")]
    assert validate_sections(ok, DocType.BRD, language=DocLanguage.JA, line_count=5) == []
    errors = validate_sections(
        [section(BG, "L9"), section(BG, "REQ-0001")],
        DocType.BRD,
        language=DocLanguage.JA,
        line_count=5,
    )
    assert errors == [
        "section background: source L9 is outside the intake",
        "section background: given twice",
        "section background: source 'REQ-0001' is not a line range like L3-L5",
    ]


def test_keys_sources_length_and_language_are_checked() -> None:
    errors = validate_sections(
        [
            section(SectionKey.SYSTEM_OVERVIEW, "REQ-0001"),
            section(BG, "REQ-0009", body="Only English here."),
            section(CONSTRAINTS, "REQ-0001", body="制" * 4001),
        ],
        DocType.SRS,
        language=DocLanguage.JA,
        known_sources={"REQ-0001"},
    )
    assert errors == [
        "section system_overview: not a section of this document (allowed: background, "
        "constraints)",
        "section background: source REQ-0009 is not an item you were given",
        "section background: body must be written in Japanese but has no Japanese characters",
        "section constraints: longer than 4000 characters",
    ]


def test_test_specs_have_no_sections() -> None:
    [error] = validate_sections(
        [section(BG, "x")], DocType.TEST_IT, language=None, known_sources={"x"}
    )
    assert error == "section background: not a section of this document (allowed: none)"


def test_content_is_ordered_and_sources_converted() -> None:
    stored = to_content([section(CONSTRAINTS, "L3"), section(BG, "L1")], lambda s: f"intake#{s}")
    assert [(s.key, s.sources) for s in stored] == [
        (BG, ["intake#L1"]),
        (CONSTRAINTS, ["intake#L3"]),
    ]


def test_views_and_upstream_block() -> None:
    assert sections_view([]) == ""
    assert sections_view([section(BG, "L1")]) == (
        "Document sections:\n- [background] 背景・目的: 勤怠管理を一元化する。 (sources L1)"
    )
    assert upstream_sections_block("DOC-BRD-0001", []) == ""
    stored = DocumentSection(key=BG, body="目的", sources=["intake/a.md#L1-L1"])
    assert upstream_sections_block("DOC-BRD-0001", [stored]) == (
        "<upstream_sections>\nDOC-BRD-0001#background 背景・目的: 目的\n</upstream_sections>"
    )
    assert section_ref("DOC-SRS-0001", CONSTRAINTS) == "DOC-SRS-0001#constraints"
