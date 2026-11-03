"""Keyword index: character bigrams stored as hex tokens in SQLite FTS5 (Requirement 5.8).

FTS5 has no bigram tokenizer, so bigrams are computed here and written as `x<utf-8 hex>`
tokens into a column with the `ascii` tokenizer, which keeps each token whole.
"""

import sqlite3
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from masterba.knowledge.extract import Chunk
from masterba.models.ids import chunk_key

_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunks (
    ref TEXT PRIMARY KEY, source_id TEXT NOT NULL, n INTEGER NOT NULL,
    text TEXT NOT NULL, heading_path TEXT NOT NULL, sheet TEXT,
    row_first INTEGER, row_last INTEGER, page INTEGER);
CREATE VIRTUAL TABLE IF NOT EXISTS fts USING fts5(
    tokens, ref UNINDEXED, source_id UNINDEXED, tokenize='ascii');
"""
_HEADING_SEP = "\x1f"


def _hex(token: str) -> str:
    return "x" + token.encode("utf-8").hex()


def bigram_tokens(text: str) -> list[str]:
    """NFKC + casefold, split on whitespace; a one-character segment gives one unigram,
    longer segments give overlapping bigrams. Each token is `x` + UTF-8 hex."""
    tokens: list[str] = []
    for segment in unicodedata.normalize("NFKC", text).casefold().split():
        if len(segment) == 1:
            tokens.append(_hex(segment))
        else:
            tokens.extend(_hex(segment[i : i + 2]) for i in range(len(segment) - 1))
    return tokens


@dataclass(frozen=True)
class StoredChunk:
    ref: str
    source_id: str
    text: str
    heading_path: tuple[str, ...]
    sheet: str | None
    rows: tuple[int, int] | None
    page: int | None


class KeywordIndex:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._db = sqlite3.connect(path)
        self._db.executescript(_SCHEMA)

    def close(self) -> None:
        self._db.close()

    def add(self, chunks: Sequence[Chunk], source_id: str) -> None:
        with self._db:
            for chunk in chunks:
                first, last = chunk.rows or (None, None)
                self._db.execute(
                    "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        chunk.ref,
                        source_id,
                        chunk_key(chunk.ref)[1],
                        chunk.text,
                        _HEADING_SEP.join(chunk.heading_path),
                        chunk.sheet,
                        first,
                        last,
                        chunk.page,
                    ),
                )
                self._db.execute(
                    "INSERT INTO fts (tokens, ref, source_id) VALUES (?, ?, ?)",
                    (" ".join(bigram_tokens(chunk.index_text)), chunk.ref, source_id),
                )

    def delete_source(self, source_id: str) -> None:
        with self._db:
            self._db.execute("DELETE FROM chunks WHERE source_id = ?", (source_id,))
            self._db.execute("DELETE FROM fts WHERE source_id = ?", (source_id,))

    def _match(self, expression: str, limit: int, sources: frozenset[str] | None) -> list[str]:
        """The best `limit` refs by bm25, ties by chunk_key; limit and filter run in SQL."""
        if sources is not None and not sources:
            return []
        where, params = "fts MATCH ?", [expression]
        if sources is not None:
            where += f" AND source_id IN ({','.join('?' * len(sources))})"
            params.extend(sorted(sources))
        scored = f"SELECT ref, bm25(fts) AS score FROM fts WHERE {where}"
        top = self._db.execute(f"{scored} ORDER BY score LIMIT ?", [*params, limit]).fetchall()
        if len(top) == limit:
            # Rows tied with the last score are all fetched, so chunk_key decides the cut.
            top = self._db.execute(
                f"SELECT ref, score FROM ({scored}) WHERE score <= ?", [*params, top[-1][1]]
            ).fetchall()
        ranked = sorted((score, chunk_key(ref), ref) for ref, score in top)
        return [ref for _, _, ref in ranked[:limit]]

    def search(self, query: str, limit: int, sources: frozenset[str] | None) -> list[str]:
        """Phrase matches first, then any-token matches, each by bm25 then chunk_key."""
        ordered = bigram_tokens(query)
        if not ordered or limit < 1:
            return []
        # Tokens are [x0-9a-f]+ only, so quoting them cannot break the MATCH syntax,
        # and the expression is still passed as one bound parameter.
        phrase = '"' + " ".join(ordered) + '"'
        anyone = " OR ".join(f'"{t}"' for t in dict.fromkeys(ordered))
        found = [*self._match(phrase, limit, sources), *self._match(anyone, limit, sources)]
        return list(dict.fromkeys(found))[:limit]

    def chunk(self, ref: str) -> StoredChunk | None:
        row = self._db.execute(
            "SELECT ref, source_id, text, heading_path, sheet, row_first, row_last, page "
            "FROM chunks WHERE ref = ?",
            (ref,),
        ).fetchone()
        if row is None:
            return None
        ref_, sid, text, heading, sheet, first, last, page = row
        return StoredChunk(
            ref=ref_,
            source_id=sid,
            text=text,
            heading_path=tuple(heading.split(_HEADING_SEP)) if heading else (),
            sheet=sheet,
            rows=(first, last) if first is not None else None,
            page=page,
        )

    def chunk_refs(self) -> list[str]:
        refs = [r for (r,) in self._db.execute("SELECT ref FROM chunks")]
        return sorted(refs, key=chunk_key)

    def sources(self) -> frozenset[str]:
        rows = self._db.execute("SELECT DISTINCT source_id FROM chunks")
        return frozenset(s for (s,) in rows)
