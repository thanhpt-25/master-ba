# Feature: local-rag, Property 21: Citation gate verdicts
# Feature: local-rag, Property 22: Quote check is whitespace-insensitive and exact otherwise
from hypothesis import given
from hypothesis import strategies as st

from masterba.knowledge.citations import collapse, validate_kb_citations
from masterba.models import KbCitation

CHUNKS = {
    "KB-0001#chunk.1": "受注とは 顧客から\n注文を受けること。",
    "KB-0002#chunk.3": "Order\tintake rules.",
}
_refs = st.sampled_from(
    [*CHUNKS, "KB-0001#chunk.9", "KB-0042#chunk.1", "KB-1#chunk.1", "x", "KB-0001#chunk.0"]
)


def _expected_ok(ref: str, covers: bool, seen: frozenset[str]) -> bool:
    return covers and ref in CHUNKS and ref in seen


@given(
    st.lists(
        st.tuples(st.integers(1, 5).map(lambda n: f"DOC-SRS-0001#item.{n}"), _refs), max_size=6
    ),
    st.booleans(),
    st.sets(st.sampled_from(list(CHUNKS))).map(frozenset),
)
def test_gate_verdicts(pairs: list[tuple[str, str]], covers: bool, seen: frozenset[str]) -> None:
    citations = [(item, KbCitation(chunk_ref=ref)) for item, ref in pairs]
    messages = validate_kb_citations(
        citations,
        manifest_ids=frozenset({"KB-0001", "KB-0002"}),
        chunk_text=CHUNKS.get,
        index_covers_manifest=covers,
        seen_refs=seen,
    )
    failing = [(i, r) for i, r in pairs if not _expected_ok(r, covers, seen)]
    assert len(messages) == len(failing)
    for message, (item, ref) in zip(messages, failing, strict=True):
        assert message.startswith(f"{ref} in {item}: ")


_ws = st.sampled_from([" ", "\t", "\n", "　", "  \n "])


@given(st.data())
def test_quote_check(data: st.DataObject) -> None:
    ref = data.draw(st.sampled_from(list(CHUNKS)))
    words = collapse(CHUNKS[ref]).split(" ")
    start = data.draw(st.integers(0, len(words) - 1))
    end = data.draw(st.integers(start + 1, len(words)))
    quote = "".join(w + data.draw(_ws) for w in words[start:end])
    mutated = data.draw(st.sampled_from(["", " 　 ", "x" * 501, quote.upper() + "Z", quote]))

    def run(q: str) -> list[str]:
        return validate_kb_citations(
            [("DOC-BRD-0001#item.1", KbCitation(chunk_ref=ref, quote=q))],
            manifest_ids=frozenset({"KB-0001", "KB-0002"}),
            chunk_text=CHUNKS.get,
            index_covers_manifest=True,
            seen_refs=frozenset(CHUNKS),
        )

    assert run(quote) == []
    collapsed = collapse(mutated)
    ok = 1 <= len(collapsed) <= 500 and collapsed in collapse(CHUNKS[ref])
    assert (run(mutated) == []) == ok
