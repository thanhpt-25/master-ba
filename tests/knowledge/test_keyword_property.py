# Feature: local-rag, Property 11: Verbatim terms are found by keyword search
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import assume, given
from hypothesis import strategies as st

from masterba.knowledge.extract import Chunk
from masterba.knowledge.keyword import KeywordIndex

_texts = st.text(st.sampled_from(list("受注顧客出荷請求abcXY12 ")), min_size=2, max_size=60)


@given(st.lists(_texts, min_size=1, max_size=8), st.data())
def test_verbatim_substring_is_found(texts: list[str], data: st.DataObject) -> None:
    target = data.draw(st.integers(0, len(texts) - 1))
    words = texts[target].split()
    assume(any(len(w) >= 2 for w in words))
    word = data.draw(st.sampled_from([w for w in words if len(w) >= 2]))
    start = data.draw(st.integers(0, len(word) - 2))
    end = data.draw(st.integers(start + 2, len(word)))
    term = word[start:end]
    chunks = [
        Chunk(ref=f"KB-0001#chunk.{n}", text=t, index_text=t, heading_path=())
        for n, t in enumerate(texts, start=1)
    ]
    with TemporaryDirectory() as tmp:
        index = KeywordIndex(Path(tmp) / "keyword.sqlite")
        index.add(chunks, "KB-0001")
        found = index.search(term, 50, None)
        index.close()
    assert chunks[target].ref in found
