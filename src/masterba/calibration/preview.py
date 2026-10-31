"""Render a draft template and compare its layout with the sample (spec 09 section 6)."""

from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

from masterba.calibration.models import MappingDraft
from masterba.models import (
    BasicDesignContent,
    BasicDesignItem,
    BrdContent,
    BrdItem,
    DetailDesignContent,
    DetailDesignItem,
    Document,
    Payload,
    SrsContent,
    SrsItem,
    TestCaseItem,
    TestSpecContent,
)
from masterba.models.enums import (
    BasicDesignKind,
    DetailDesignKind,
    DocStatus,
    DocType,
    Level,
    Scope,
    SrsKind,
)
from masterba.models.payloads import LEVEL_BY_TEST_TYPE
from masterba.rendering.engine import render_document
from masterba.rendering.template import ResolvedTemplate
from masterba.rendering.xlsxio import workbook_bytes


def demo_document(doc_type: DocType) -> tuple[Document, Payload]:
    """A small invented document of the given type, for previews without a project."""
    doc_id = f"DOC-{doc_type.value}-0001"
    document = Document(
        id=doc_id,
        type=doc_type,
        version=1,
        status=DocStatus.DRAFT,
        template_id="preview",
        content_ref=f"json/{doc_type.value.lower()}/{doc_id}.v1.json",
        project_id="PRJ-001",
    )
    ref = f"{doc_id}#item"
    content: Payload
    if doc_type is DocType.BRD:
        content = BrdContent(
            items=[
                BrdItem(
                    item_id=f"{ref}.{n}",
                    requirement_id=f"REQ-000{n}",
                    title=f"Sample requirement {n}",
                    description="A sentence long enough to show how wrapped text looks here.",
                    scope=Scope.IN if n < 3 else Scope.OUT,
                    source_ref="intake/sample.txt#L1-L1",
                )
                for n in (1, 2, 3)
            ]
        )
    elif doc_type is DocType.SRS:
        content = SrsContent(
            items=[
                SrsItem(
                    item_id=f"{ref}.{n}",
                    requirement_id=f"REQ-000{n}",
                    kind=SrsKind.FUNCTIONAL if n < 3 else SrsKind.NON_FUNCTIONAL,
                    statement=f"The system shall do thing {n}.",
                    acceptance_hint="Check it.",
                    derives_from=[f"REQ-000{n}"],
                )
                for n in (1, 2, 3)
            ]
        )
    elif doc_type is DocType.BASIC_DESIGN:
        content = BasicDesignContent(
            items=[
                BasicDesignItem(
                    item_id=f"{ref}.{n}",
                    kind=BasicDesignKind.FUNCTION,
                    name=f"Function {n}",
                    description="What it does.",
                    realizes=["DOC-SRS-0001#item.1"],
                )
                for n in (1, 2, 3)
            ]
        )
    elif doc_type is DocType.DETAIL_DESIGN:
        content = DetailDesignContent(
            items=[
                DetailDesignItem(
                    item_id=f"{ref}.{n}",
                    kind=DetailDesignKind.MODULE,
                    name=f"Module {n}",
                    spec="Operations, inputs, outputs and errors.",
                    refines=["DOC-BASIC_DESIGN-0001#item.1"],
                )
                for n in (1, 2, 3)
            ]
        )
    else:
        level = LEVEL_BY_TEST_TYPE[doc_type]
        content = TestSpecContent(
            items=[
                TestCaseItem(
                    item_id=f"{ref}.{n}",
                    test_id=f"TC-{level.value}-000{n}",
                    level=Level(level.value),
                    precondition="A registered user exists.",
                    input="valid data",
                    steps=["Open the page", "Submit the form"],
                    expected="The result is shown.",
                    verifies=["DOC-SRS-0001#item.1"],
                )
                for n in (1, 2, 3)
            ]
        )
    return document, content


def render_preview(
    template: ResolvedTemplate, document: Document, content: Payload, target: Path
) -> Path:
    """Write the rendered workbook to `target` and return it."""
    target.write_bytes(workbook_bytes(render_document(document, content, template)))
    return target


def compare_layout(sample: Path, preview: Path, draft: MappingDraft) -> list[str]:
    """Differences between the sample and the preview in what a reader sees as layout."""
    before = load_workbook(sample)
    after = load_workbook(preview)
    differences: list[str] = []
    if before.sheetnames != after.sheetnames:
        differences.append(f"sheet names differ: {before.sheetnames} vs {after.sheetnames}")
        return differences
    for table in draft.tables:
        a, b = before[table.sheet], after[table.sheet]
        columns = max(a.max_column, b.max_column)
        for column in range(1, columns + 1):
            letter = get_column_letter(column)
            head_a = a.cell(row=table.header_row, column=column).value
            head_b = b.cell(row=table.header_row, column=column).value
            if head_a != head_b:
                differences.append(
                    f"{table.sheet}!{letter}{table.header_row}: {head_a!r} vs {head_b!r}"
                )
            width_a = a.column_dimensions[letter].width if letter in a.column_dimensions else None
            width_b = b.column_dimensions[letter].width if letter in b.column_dimensions else None
            if width_a != width_b:
                differences.append(f"{table.sheet} column {letter} width: {width_a} vs {width_b}")
    return differences
