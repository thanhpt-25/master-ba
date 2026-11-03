"""Vector stores for the hybrid retriever (Requirement 5.9).

`LanceVectorStore` needs the `rag` extra; `lancedb` is imported inside it only.
Search is exhaustive (no ANN index), ordered by cosine distance then `chunk_key`.
"""

import datetime as dt
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

from masterba.models.ids import chunk_key

VectorRow = tuple[str, str, list[float]]  # (ref, source_id, vector)


class VectorStore(Protocol):
    def add(self, rows: Sequence[VectorRow]) -> None: ...

    def delete_source(self, source_id: str) -> None: ...

    def search(
        self, vector: list[float], limit: int, sources: frozenset[str] | None
    ) -> list[str]: ...

    def refs(self) -> frozenset[str]: ...


def _cosine_distance(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return 1.0 - (dot / norm if norm else 0.0)


class InMemoryVectorStore:
    """Offline fake with the same contract as `LanceVectorStore`."""

    def __init__(self) -> None:
        self._rows: dict[str, tuple[str, list[float]]] = {}

    def add(self, rows: Sequence[VectorRow]) -> None:
        for ref, source_id, vector in rows:
            self._rows[ref] = (source_id, list(vector))

    def delete_source(self, source_id: str) -> None:
        self._rows = {r: v for r, v in self._rows.items() if v[0] != source_id}

    def search(self, vector: list[float], limit: int, sources: frozenset[str] | None) -> list[str]:
        scored = [
            (_cosine_distance(vector, vec), chunk_key(ref), ref)
            for ref, (sid, vec) in self._rows.items()
            if sources is None or sid in sources
        ]
        return [ref for _, _, ref in sorted(scored)[:limit]]

    def refs(self) -> frozenset[str]:
        return frozenset(self._rows)


class LanceVectorStore:
    """One LanceDB table `chunks(ref, source_id, vector)` under `path`."""

    TABLE = "chunks"

    def __init__(self, path: Path) -> None:
        import lancedb

        self._db: Any = lancedb.connect(str(path))
        names = self._db.table_names()
        self._table: Any = self._db.open_table(self.TABLE) if self.TABLE in names else None

    def _ensure(self, dimensions: int) -> Any:
        if self._table is None:
            import pyarrow as pa

            schema = pa.schema(
                [
                    pa.field("ref", pa.string()),
                    pa.field("source_id", pa.string()),
                    pa.field("vector", pa.list_(pa.float32(), dimensions)),
                ]
            )
            self._table = self._db.create_table(self.TABLE, schema=schema)
        return self._table

    def add(self, rows: Sequence[VectorRow]) -> None:
        if not rows:
            return
        table = self._ensure(len(rows[0][2]))
        table.add([{"ref": r, "source_id": s, "vector": v} for r, s, v in rows])

    def delete_source(self, source_id: str) -> None:
        if self._table is not None:
            # Source ids are validated KB-#### values, so the filter cannot be injected.
            self._table.delete(f"source_id = '{source_id}'")

    def search(self, vector: list[float], limit: int, sources: frozenset[str] | None) -> list[str]:
        if self._table is None or limit < 1 or (sources is not None and not sources):
            return []
        query = self._table.search(vector).metric("cosine").select(["ref", "source_id"])
        if sources is not None:
            # Ids are validated KB-#### values, so the filter cannot be injected.
            listed = ", ".join(f"'{s}'" for s in sorted(sources))
            query = query.where(f"source_id IN ({listed})", prefilter=True)
        # Twice the limit leaves room for distance ties before the chunk_key cut.
        rows = query.limit(limit * 2).to_list()
        kept = sorted((float(row["_distance"]), chunk_key(row["ref"]), row["ref"]) for row in rows)
        return [ref for _, _, ref in kept[:limit]]

    def refs(self) -> frozenset[str]:
        if self._table is None:
            return frozenset()
        return frozenset(self._table.to_arrow().column("ref").to_pylist())

    def compact(self) -> None:
        """Merge fragments and drop old versions; the generation is a private copy."""
        if self._table is not None:
            self._table.optimize(cleanup_older_than=dt.timedelta(0), delete_unverified=True)
