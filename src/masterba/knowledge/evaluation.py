"""Retrieval evaluation: Recall@5 per language for keyword, vector and hybrid (Requirement 8).

Run: `uv run python -m masterba.knowledge.evaluation [--model NAME]` with the rag extra and a
model set up by `masterba kb setup`. Sources get Source_Ids in file-name order.
"""

import argparse
import datetime as dt
import hashlib
import shutil
import sys
import tempfile
import tomllib
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from masterba.knowledge.embedder import Embedder, configured_model, load_embedder, model_present
from masterba.knowledge.indexer import (
    IndexBackend,
    activate,
    build_generation,
    lance_vectors,
    open_index,
)
from masterba.knowledge.paths import KbPaths
from masterba.knowledge.retriever import CANDIDATES, rrf_fuse
from masterba.knowledge.store import SourceSuffix
from masterba.models import KbManifest, KbSource

EVAL_DIR = Path(__file__).resolve().parents[3] / "tests" / "knowledge" / "eval"
K = 5
MODES = ("keyword", "vector", "hybrid")


@dataclass(frozen=True)
class EvalQuestion:
    lang: str
    text: str
    expected: str


@dataclass(frozen=True)
class Recall:
    lang: str
    mode: str
    hits: int
    questions: int

    @property
    def value(self) -> float:
        return self.hits / self.questions if self.questions else 0.0


class EvaluationError(Exception):
    """The evaluation set does not match the indexed samples."""


def load_questions(eval_dir: Path = EVAL_DIR) -> list[EvalQuestion]:
    data = tomllib.loads((eval_dir / "questions.toml").read_text(encoding="utf-8"))
    return [EvalQuestion(q["lang"], q["text"], q["expected"]) for q in data["questions"]]


def _manifest(sources: Sequence[Path]) -> KbManifest:
    now = dt.datetime.now(dt.UTC)
    return KbManifest(
        sources=[
            KbSource(
                id=f"KB-{n:04d}",
                file_name=path.name,
                suffix=cast(SourceSuffix, path.suffix.lower()),
                sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                added_by="evaluation",
                added_at=now,
            )
            for n, path in enumerate(sources, start=1)
        ]
    )


def _backend(embedder: Embedder | None) -> IndexBackend:
    def load(name: str) -> Embedder:
        assert embedder is not None
        return embedder

    return IndexBackend(lambda: (embedder.name if embedder else None, None), load, lance_vectors)


def build_eval_index(
    root: Path,
    embedder: Embedder | None,
    eval_dir: Path = EVAL_DIR,
    backend: IndexBackend | None = None,
) -> KbPaths:
    """Index the sample sources under `root` (a temporary folder)."""
    sources = sorted(p for p in (eval_dir / "sources").iterdir() if p.is_file())
    paths = KbPaths(root / "knowledge")
    paths.sources.mkdir(parents=True)
    manifest = _manifest(sources)
    for entry, path in zip(manifest.sources, sources, strict=True):
        shutil.copyfile(path, paths.source_file(entry.id, entry.suffix))
    outcome = build_generation(paths, manifest, base=None, backend=backend or _backend(embedder))
    activate(paths, outcome.generation)
    return paths


def evaluate(
    paths: KbPaths,
    questions: Sequence[EvalQuestion],
    embedder: Embedder | None,
    backend: IndexBackend | None = None,
) -> list[Recall]:
    """Recall@5 for each language and mode; `vector` and `hybrid` need an embedder."""
    index = open_index(paths, backend or _backend(embedder))
    try:
        known = set(index.keyword.chunk_refs())
        for q in questions:
            if q.expected not in known:
                raise EvaluationError(f"question {q.text!r}: expected {q.expected} is not indexed")
        hits: dict[tuple[str, str], int] = {}
        for q in questions:
            keyword = index.keyword.search(q.text, CANDIDATES, None)
            ranked = {"keyword": keyword}
            if embedder is not None and index.vectors is not None:
                vector = index.vectors.search(embedder.embed_query(q.text), CANDIDATES, None)
                ranked["vector"] = vector
                ranked["hybrid"] = [ref for ref, _ in rrf_fuse([keyword, vector])]
            for mode, refs in ranked.items():
                key = (q.lang, mode)
                hits[key] = hits.get(key, 0) + (q.expected in refs[:K])
    finally:
        index.close()
    langs = sorted({q.lang for q in questions})
    return [
        Recall(lang, mode, hits[(lang, mode)], sum(q.lang == lang for q in questions))
        for lang in langs
        for mode in MODES
        if (lang, mode) in hits
    ]


def format_table(model: str | None, results: Sequence[Recall]) -> str:
    lines = [f"model: {model or 'none (keyword only)'}", "lang  mode     recall@5  hits/questions"]
    lines += [f"{r.lang:<5} {r.mode:<8} {r.value:8.3f}  {r.hits}/{r.questions}" for r in results]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="masterba.knowledge.evaluation")
    parser.add_argument("--model", default=None)
    args = parser.parse_args(argv)
    name = args.model or configured_model()
    embedder = load_embedder(name) if model_present(name) else None
    if embedder is None:
        sys.stderr.write(f"model {name} is not set up; showing keyword results only\n")
    with tempfile.TemporaryDirectory() as tmp:
        paths = build_eval_index(Path(tmp), embedder)
        results = evaluate(paths, load_questions(), embedder)
    sys.stdout.write(format_table(embedder.name if embedder else None, results) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
