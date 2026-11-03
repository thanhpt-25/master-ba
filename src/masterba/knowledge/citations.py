"""The knowledge citation gate (spec 12, Requirement 10). Pure: no index access here."""

import re
from collections.abc import Callable, Sequence

from masterba.models import KbCitation
from masterba.models.ids import parse_chunk_ref

MAX_QUOTE_CHARS = 500
_WHITESPACE = re.compile(r"\s+")  # \s covers U+3000 for str patterns


def collapse(text: str) -> str:
    return _WHITESPACE.sub(" ", text).strip()


def _problem(
    citation: KbCitation,
    manifest_ids: frozenset[str],
    chunk_text: Callable[[str], str | None],
    index_covers_manifest: bool,
    seen_refs: frozenset[str],
) -> str | None:
    ref = citation.chunk_ref
    if not index_covers_manifest:
        return "the knowledge base index is unavailable"
    parsed = parse_chunk_ref(ref)
    if parsed is None:
        return "malformed Chunk_Ref"
    if parsed[0] not in manifest_ids:
        return "unknown Source_Id"
    text = chunk_text(ref)
    if text is None:
        return "unknown chunk"
    if citation.quote is not None:
        quote = collapse(citation.quote)
        if not quote:
            return "the quote is empty"
        if len(quote) > MAX_QUOTE_CHARS:
            return f"the quote is longer than {MAX_QUOTE_CHARS} characters"
        if quote not in collapse(text):
            return "the quote is not copied exactly from the passage"
    if ref not in seen_refs:
        return "was not in any knowledge block of this run"
    return None


def validate_kb_citations(
    citations: Sequence[tuple[str, KbCitation]],
    *,
    manifest_ids: frozenset[str],
    chunk_text: Callable[[str], str | None],
    index_covers_manifest: bool,
    seen_refs: frozenset[str],
) -> list[str]:
    """One message per failing citation, each naming the item ref and the Chunk_Ref."""
    messages: list[str] = []
    for item_ref, citation in citations:
        problem = _problem(citation, manifest_ids, chunk_text, index_covers_manifest, seen_refs)
        if problem is not None:
            messages.append(f"{citation.chunk_ref} in {item_ref}: {problem}")
    return messages
