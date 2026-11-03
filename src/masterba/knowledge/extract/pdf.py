"""`.pdf` extraction (Requirements 4.6, 4.11): text layer only, one block per page."""

from collections.abc import Iterator
from pathlib import Path

from pypdf import PasswordType, PdfReader

from masterba.knowledge.extract.blocks import Block
from masterba.knowledge.extract.errors import ExtractionError


def pdf_blocks(path: Path) -> Iterator[Block]:
    reader = PdfReader(path, strict=False)
    if reader.is_encrypted and reader.decrypt("") == PasswordType.NOT_DECRYPTED:
        raise ExtractionError("password-protected PDF")
    for number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            yield Block(text=text, page=number)
