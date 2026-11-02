from pathlib import Path

from masterba.knowledge.extract import Chunk
from masterba.knowledge.keyword import KeywordIndex, bigram_tokens


def _chunk(ref: str, text: str, heading: tuple[str, ...] = ()) -> Chunk:
    return Chunk(ref=ref, text=text, index_text="\n".join([*heading, text]), heading_path=heading)


def test_bigram_tokens() -> None:
    assert bigram_tokens("受注 A ｱｲ") == [
        "x" + "受注".encode().hex(),
        "x61",
        "x" + "アイ".encode().hex(),
    ]
    assert bigram_tokens("   ") == []


def test_search_orders_filters_and_deletes(tmp_path: Path) -> None:
    index = KeywordIndex(tmp_path / "k.sqlite")
    index.add(
        [
            _chunk("KB-0001#chunk.1", "受注の登録", ("用語集",)),
            _chunk("KB-0001#chunk.2", "注文と受付"),
        ],
        "KB-0001",
    )
    index.add([_chunk("KB-0002#chunk.1", "受注 受注 受注")], "KB-0002")
    assert set(index.search("受注", 10, None)) == {"KB-0001#chunk.1", "KB-0002#chunk.1"}
    assert index.search("受注", 10, frozenset({"KB-0001"})) == ["KB-0001#chunk.1"]
    assert index.search("用語", 10, None) == ["KB-0001#chunk.1"]  # heading text is indexed
    assert index.search('") OR (', 10, None) == []
    stored = index.chunk("KB-0001#chunk.1")
    assert stored is not None and stored.heading_path == ("用語集",)
    index.delete_source("KB-0001")
    assert index.chunk_refs() == ["KB-0002#chunk.1"]
    assert index.sources() == frozenset({"KB-0002"})
    assert index.chunk("KB-0001#chunk.1") is None
