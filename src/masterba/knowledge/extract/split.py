"""Split extracted text into chunk-sized pieces (Requirement 4.8).

Lengths are counted in Unicode code points of the original text. Pieces are
stripped, and blank pieces are dropped.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

MAX_CHUNK_CHARS = 1_000

# A sentence ends after a full-width terminator, or after `.`, `!` or `?`
# followed by whitespace or the end of the text.
_SENTENCE_END = re.compile(r"[。！？]|[.!?](?=\s|$)")


def _sentences(text: str) -> list[str]:
    """Contiguous slices of ``text`` that each end at a sentence boundary
    (the last one may end at the end of the text)."""
    pieces: list[str] = []
    start = 0
    for match in _SENTENCE_END.finditer(text):
        pieces.append(text[start : match.end()])
        start = match.end()
    if start < len(text):
        pieces.append(text[start:])
    return pieces


def _raw_pieces(text: str, limit: int) -> list[str]:
    """Contiguous slices of ``text``, each at most ``limit`` code points,
    whose concatenation is ``text``."""
    if len(text) <= limit:
        return [text]
    pieces: list[str] = []
    current = ""
    for sentence in _sentences(text):
        if len(sentence) > limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.extend(sentence[i : i + limit] for i in range(0, len(sentence), limit))
        elif len(current) + len(sentence) <= limit:
            current += sentence
        else:
            pieces.append(current)
            current = sentence
    if current:
        pieces.append(current)
    return pieces


def split_text(text: str, limit: int = MAX_CHUNK_CHARS) -> list[str]:
    """Split ``text`` at sentence boundaries into pieces of at most ``limit``
    code points. Sentences are packed greedily; a sentence longer than
    ``limit`` is cut every ``limit`` code points. Each piece is stripped and
    blank pieces are dropped, so the pieces are non-blank substrings of
    ``text`` in order."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    return [piece.strip() for piece in _raw_pieces(text, limit) if piece.strip()]


def split_rows(
    rows: Sequence[tuple[int, str]], limit: int = MAX_CHUNK_CHARS
) -> list[tuple[int, int, str]]:
    """Pack ``(row_number, row_text)`` rows into pieces of at most ``limit``
    code points, splitting only at row boundaries. Rows in a piece are joined
    by a newline. A single row longer than ``limit`` is split by
    :func:`split_text`, and each of its pieces carries that row number as
    first and last row. Blank rows are skipped. Returns
    ``(first_row, last_row, text)`` triples in row order."""
    if limit < 1:
        raise ValueError("limit must be at least 1")
    result: list[tuple[int, int, str]] = []
    group: list[tuple[int, str]] = []
    size = 0

    def flush() -> None:
        nonlocal group, size
        if group:
            text = "\n".join(row_text for _, row_text in group).strip()
            if text:
                result.append((group[0][0], group[-1][0], text))
        group = []
        size = 0

    for number, row_text in rows:
        if not row_text.strip():
            continue
        if len(row_text) > limit:
            flush()
            result.extend((number, number, piece) for piece in split_text(row_text, limit))
            continue
        added = len(row_text) + (1 if group else 0)
        if size + added > limit:
            flush()
            added = len(row_text)
        group.append((number, row_text))
        size += added
    flush()
    return result
