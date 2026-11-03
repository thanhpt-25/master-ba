# Feature: local-rag, Property 7: Markdown chunks respect paragraphs and headings
from pathlib import Path
from tempfile import TemporaryDirectory

from hypothesis import given
from hypothesis import strategies as st

from masterba.knowledge.extract import ExtractionError, extract_source

_words = st.text("あいう受注abc ", min_size=1, max_size=30).map(str.strip).filter(bool)
_paragraph = st.lists(_words, min_size=1, max_size=3).map(lambda lines: (0, "\n".join(lines)))
_heading = st.tuples(st.integers(1, 6), _words)
_docs = st.lists(_heading | _paragraph, min_size=1, max_size=12)


@given(_docs)
def test_markdown_chunks(doc: list[tuple[int, str]]) -> None:
    # level 0 is a paragraph, 1-6 a heading
    lines: list[str] = []
    expected: list[tuple[tuple[str, ...], str]] = []
    stack: list[tuple[int, str]] = []
    for level, value in doc:
        if level:
            title = value
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
            lines += ["#" * level + " " + title, ""]
        else:
            lines += [value, ""]
            expected.append((tuple(t for _, t in stack), value))
    with TemporaryDirectory() as tmp:
        path = Path(tmp) / "KB-0001.md"
        path.write_text("\n".join(lines), encoding="utf-8")
        try:
            chunks = extract_source("KB-0001", path, ".md")
        except ExtractionError:
            assert not expected
            return
    assert [(c.heading_path, c.text) for c in chunks] == expected
    for chunk in chunks:
        assert "\n\n" not in chunk.text
        assert not any(line.lstrip().startswith("#") for line in chunk.text.split("\n"))
