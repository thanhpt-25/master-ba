"""Text extraction and chunking for knowledge sources (spec 12, Requirement 4)."""

import unicodedata
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from masterba.knowledge.extract.blocks import Block
from masterba.knowledge.extract.errors import ExtractionError
from masterba.knowledge.extract.split import MAX_CHUNK_CHARS, split_rows, split_text

EXTRACTOR_VERSION = 1

__all__ = ["EXTRACTOR_VERSION", "MAX_CHUNK_CHARS", "Chunk", "ExtractionError", "extract_source"]


@dataclass(frozen=True)
class Chunk:
    ref: str  # KB-0001#chunk.3
    text: str  # original text, shown and used for quote checks
    index_text: str  # NFKC(heading path + "\n" + text), used by both indexes
    heading_path: tuple[str, ...]
    sheet: str | None = None
    rows: tuple[int, int] | None = None
    page: int | None = None


def _blocks(path: Path, suffix: str) -> Iterable[Block]:
    # Parsers are imported lazily, so a broken parser library only fails sources of its type.
    if suffix in (".md", ".txt"):
        from masterba.knowledge.extract.text import text_blocks

        return text_blocks(path, markdown=suffix == ".md")
    if suffix == ".xlsx":
        from masterba.knowledge.extract.xlsx import xlsx_blocks

        return xlsx_blocks(path)
    if suffix == ".docx":
        from masterba.knowledge.extract.docx import docx_blocks

        return docx_blocks(path)
    if suffix == ".pdf":
        from masterba.knowledge.extract.pdf import pdf_blocks

        return pdf_blocks(path)
    raise ExtractionError(f"unsupported type {suffix}")


def _pieces(block: Block) -> Iterator[tuple[str, tuple[int, int] | None]]:
    if block.rows:
        for first, last, text in split_rows(block.rows):
            yield text, (first, last) if block.keep_rows else None
    else:
        for text in split_text(block.text):
            yield text, None


def _index_text(heading_path: tuple[str, ...], text: str) -> str:
    return unicodedata.normalize("NFKC", "\n".join([*heading_path, text]))


def extract_source(source_id: str, path: Path, suffix: str) -> list[Chunk]:
    """Chunks of one stored source, numbered from 1. Opens only `path`.

    Raises ExtractionError with the `failed` reason: `no text found`, `password-protected PDF`
    or `cannot read <type>: <first line of the parser error>`.
    """
    suffix = suffix.lower()
    chunks: list[Chunk] = []
    try:
        for block in _blocks(path, suffix):
            for text, rows in _pieces(block):
                chunks.append(
                    Chunk(
                        ref=f"{source_id}#chunk.{len(chunks) + 1}",
                        text=text,
                        index_text=_index_text(block.heading_path, text),
                        heading_path=block.heading_path,
                        sheet=block.sheet,
                        rows=rows,
                        page=block.page,
                    )
                )
    except ExtractionError:
        raise
    except Exception as exc:  # noqa: BLE001 - any parser failure fails this source only
        first = (str(exc).strip().splitlines() or [type(exc).__name__])[0]
        raise ExtractionError(f"cannot read {suffix.lstrip('.')}: {first}") from exc
    if not chunks:
        raise ExtractionError("no text found")
    return chunks
