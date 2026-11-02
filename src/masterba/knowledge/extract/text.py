"""`.md` and `.txt` extraction (Requirements 4.1, 4.2)."""

import re
from collections.abc import Iterator
from pathlib import Path

from masterba.knowledge.extract.blocks import Block, heading_path, push_heading

_HEADING = re.compile(r"^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$")
_FENCE = re.compile(r"^ {0,3}(```|~~~)")


def read_text(path: Path) -> str:
    text = path.read_bytes().decode("utf-8").removeprefix("﻿")
    return text.replace("\r\n", "\n").replace("\r", "\n")


def text_blocks(path: Path, *, markdown: bool) -> Iterator[Block]:
    """Paragraphs separated by blank lines; for Markdown, ATX headings outside fenced code
    start a new block, update the heading stack and are not chunk text."""
    stack: list[tuple[int, str]] = []
    lines: list[str] = []
    fenced = False

    def flush() -> Iterator[Block]:
        if "".join(lines).strip():
            yield Block(text="\n".join(lines), heading_path=heading_path(stack))
        lines.clear()

    for line in read_text(path).split("\n"):
        if markdown and _FENCE.match(line):
            fenced = not fenced
        heading = None if (fenced or not markdown) else _HEADING.match(line)
        if heading:
            yield from flush()
            level = len(heading.group(1))
            push_heading(stack, level, heading.group(2).strip())
        elif not line.strip() and not fenced:
            yield from flush()
        else:
            lines.append(line)
    yield from flush()
