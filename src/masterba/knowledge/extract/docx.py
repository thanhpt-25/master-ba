"""`.docx` extraction (Requirement 4.5): body in document order; external parts never opened."""

import re
from collections.abc import Iterator
from pathlib import Path

import docx
from docx.table import Table
from docx.text.paragraph import Paragraph

from masterba.knowledge.extract.blocks import Block, heading_path, push_heading

_HEADING_STYLE = re.compile(r"^Heading ([1-9])$")


def _row_text(cells: list[str]) -> str:
    kept: list[str] = []
    for text in cells:
        if not kept or kept[-1] != text:  # merged cells repeat their text
            kept.append(text)
    return " | ".join(t for t in kept if t)


def docx_blocks(path: Path) -> Iterator[Block]:
    document = docx.Document(str(path))
    stack: list[tuple[int, str]] = []
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = paragraph.text
            style = paragraph.style.name if paragraph.style is not None else ""
            heading = _HEADING_STYLE.match(style or "")
            if heading and text.strip():
                level = int(heading.group(1))
                push_heading(stack, level, text.strip())
            elif text.strip():
                yield Block(text=text, heading_path=heading_path(stack))
        elif tag == "tbl":
            table = Table(child, document)
            rows = [
                (n, _row_text([c.text.strip() for c in row.cells]))
                for n, row in enumerate(table.rows, start=1)
            ]
            yield Block(rows=tuple(rows), heading_path=heading_path(stack))
