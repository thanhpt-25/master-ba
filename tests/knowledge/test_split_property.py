# Feature: local-rag, Property 6: Split pieces are bounded, non-blank, ordered substrings
from hypothesis import given
from hypothesis import strategies as st

from masterba.knowledge.extract.split import split_text

_parts = st.sampled_from(
    ["受注を登録する。", "This is a sentence. ", "Why? ", "ｶﾀｶﾅ１２３", "  \n\t", "　", "!"]
)
_texts = st.one_of(
    st.lists(_parts | st.text(max_size=30), max_size=60).map("".join),
    st.text(min_size=900, max_size=2500, alphabet="あいうabc "),
)


@given(_texts, st.sampled_from([1000, 50, 7]))
def test_split_pieces(text: str, limit: int) -> None:
    pieces = split_text(text, limit)
    position = 0
    for piece in pieces:
        assert 1 <= len(piece) <= limit
        assert piece.strip() == piece and piece
        found = text.find(piece, position)
        assert found >= position
        position = found + len(piece)
    joined = "".join(pieces)
    assert [c for c in joined if not c.isspace()] == [c for c in text if not c.isspace()]
