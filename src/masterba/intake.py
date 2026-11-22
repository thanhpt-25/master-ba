"""Intake files: plain text as is, Word, PDF and Excel converted to Markdown (spec 19 section 18).

The stored intake is the converted text, so line citations and quote checks work on it exactly as
on a text intake. Conversion reuses the knowledge base extractors.
"""

import hashlib
import re
from collections.abc import Iterable
from pathlib import Path

from masterba.knowledge.extract import ExtractionError
from masterba.knowledge.extract.blocks import Block
from masterba.trace_store import InvalidDocumentError

TEXT_SUFFIXES = (".txt", ".md")
CONVERTED_SUFFIXES = (".docx", ".pdf", ".xlsx")
INTAKE_SUFFIXES = TEXT_SUFFIXES + CONVERTED_SUFFIXES
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]+")


def intake_name(file_name: str) -> str:
    """The name the intake is stored under: `.txt`/`.md` as given, others `<stem>-<ext>.md`."""
    path = Path(file_name)
    suffix = path.suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return path.name
    if suffix not in CONVERTED_SUFFIXES:
        raise InvalidDocumentError(
            f"unsupported intake type {suffix or '(none)'}; use {', '.join(INTAKE_SUFFIXES)}"
        )
    stem = _UNSAFE.sub("-", path.stem).strip("-._")[:48] or "intake"
    if not path.stem.isascii():  # e.g. 要件定義.docx: keep names of different files apart
        stem = f"{stem}-{hashlib.sha256(path.stem.encode()).hexdigest()[:6]}"
    return f"{stem}-{suffix.lstrip('.')}.md"


def _blocks(path: Path, suffix: str) -> Iterable[Block]:
    # The same lazy imports as the knowledge base: a broken parser only fails its own type.
    if suffix == ".docx":
        from masterba.knowledge.extract.docx import docx_blocks

        return docx_blocks(path)
    if suffix == ".pdf":
        from masterba.knowledge.extract.pdf import pdf_blocks

        return pdf_blocks(path)
    from masterba.knowledge.extract.xlsx import xlsx_blocks

    return xlsx_blocks(path)


def blocks_to_markdown(blocks: Iterable[Block]) -> str:
    """Markdown lines in document order: headings when they change, page marks, sheet headings."""
    lines: list[str] = []
    headings: tuple[str, ...] = ()
    sheet: str | None = None
    page: int | None = None

    def gap() -> None:
        if lines and lines[-1] != "":
            lines.append("")

    for block in blocks:
        if block.sheet is not None and block.sheet != sheet:
            sheet = block.sheet
            gap()
            lines += [f"## {sheet}", ""]
        if block.page is not None and block.page != page:
            page = block.page
            gap()
            lines.append(f"<!-- p.{page} -->")
        if block.heading_path != headings:
            shared = 0
            while (
                shared < min(len(headings), len(block.heading_path))
                and headings[shared] == block.heading_path[shared]
            ):
                shared += 1
            for level, title in enumerate(block.heading_path[shared:], start=shared + 1):
                gap()
                lines += [f"{'#' * min(level, 6)} {title}", ""]
            headings = block.heading_path
        if block.rows:
            if block.keep_rows:  # spreadsheet rows keep their row number
                lines += [f"R{n}: {text}" for n, text in block.rows]
            else:
                lines += [f"| {text} |" for _, text in block.rows]
            lines.append("")
        else:
            text = block.text.strip()
            if text:
                lines += [*text.splitlines(), ""]
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n" if lines else ""


def intake_text(path: Path) -> str:
    """The intake text of a file; raises InvalidDocumentError when it cannot be read."""
    suffix = path.suffix.lower()
    intake_name(path.name)  # refuses an unsupported type
    if suffix in TEXT_SUFFIXES:
        return path.read_text(encoding="utf-8")
    try:
        text = blocks_to_markdown(_blocks(path, suffix))
    except ExtractionError as exc:
        raise InvalidDocumentError(f"cannot read intake {path.name}: {exc}") from exc
    except Exception as exc:  # noqa: BLE001 - any parser failure is reported, nothing is written
        first = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
        raise InvalidDocumentError(f"cannot read intake {path.name}: {first}") from exc
    if not text.strip():
        raise InvalidDocumentError(f"cannot read intake {path.name}: no text found")
    return text
