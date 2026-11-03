# Feature: local-rag, Property 9: Extraction is deterministic and numbered from 1
import unicodedata
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from masterba.knowledge.extract import ExtractionError, extract_source

_texts = st.text(st.sampled_from(list("ｶﾀｶﾅ１２３受注ab #\n. ")), min_size=1, max_size=400)


@given(_texts, st.sampled_from([".md", ".txt"]))
def test_extraction_is_deterministic(text: str, suffix: str) -> None:
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / f"KB-0007{suffix}"
        path.write_text(text, encoding="utf-8")
        try:
            first = extract_source("KB-0007", path, suffix)
        except ExtractionError:
            return
        assert extract_source("KB-0007", path, suffix) == first
    assert [c.ref for c in first] == [f"KB-0007#chunk.{n}" for n in range(1, len(first) + 1)]
    for chunk in first:
        assert chunk.text in text.replace("\r\n", "\n")
        expected = unicodedata.normalize("NFKC", "\n".join([*chunk.heading_path, chunk.text]))
        assert chunk.index_text == expected
