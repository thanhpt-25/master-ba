import pytest

from masterba.knowledge.extract.split import MAX_CHUNK_CHARS, split_rows, split_text


def test_short_text_is_one_stripped_piece() -> None:
    assert split_text("  Hello world.  ") == ["Hello world."]


def test_blank_text_gives_no_pieces() -> None:
    assert split_text("   \n\t ") == []
    assert split_text("") == []


def test_splits_at_sentence_boundaries_and_packs_greedily() -> None:
    text = "Aaaa. Bbbb. Cccc."
    assert split_text(text, limit=12) == ["Aaaa. Bbbb.", "Cccc."]


def test_period_without_following_whitespace_is_not_a_boundary() -> None:
    text = "v1.2.3 is out"
    assert split_text(text, limit=8) == ["v1.2.3 i", "s out"]


def test_full_width_terminators_are_boundaries() -> None:
    text = "あいう。えお！かき？"
    assert split_text(text, limit=5) == ["あいう。", "えお！", "かき？"]


def test_long_sentence_is_hard_cut() -> None:
    text = "x" * (MAX_CHUNK_CHARS * 2 + 5)
    pieces = split_text(text)
    assert [len(p) for p in pieces] == [MAX_CHUNK_CHARS, MAX_CHUNK_CHARS, 5]
    assert "".join(pieces) == text


def test_invalid_limit_is_refused() -> None:
    with pytest.raises(ValueError):
        split_text("a", limit=0)
    with pytest.raises(ValueError):
        split_rows([(1, "a")], limit=0)


def test_split_rows_packs_at_row_boundaries() -> None:
    rows = [(2, "aaa"), (3, "bbb"), (4, "ccc"), (5, "   ")]
    assert split_rows(rows, limit=7) == [(2, 3, "aaa\nbbb"), (4, 4, "ccc")]


def test_split_rows_splits_a_long_row_with_its_row_number() -> None:
    rows = [(1, "ab"), (2, "One. Two. Three."), (3, "cd")]
    assert split_rows(rows, limit=10) == [
        (1, 1, "ab"),
        (2, 2, "One. Two."),
        (2, 2, "Three."),
        (3, 3, "cd"),
    ]


def test_split_rows_empty_input() -> None:
    assert split_rows([]) == []
