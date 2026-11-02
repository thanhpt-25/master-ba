"""The block shape every format extractor yields, in document order."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Block:
    """Either free `text` (split by sentences) or `rows` (split at row boundaries)."""

    text: str = ""
    rows: tuple[tuple[int, str], ...] = ()
    heading_path: tuple[str, ...] = ()
    sheet: str | None = None
    page: int | None = None
    keep_rows: bool = field(default=False)  # chunk carries the row range (spreadsheets)


def push_heading(stack: list[tuple[int, str]], level: int, title: str) -> None:
    """A heading of level n replaces the headings of level n and deeper."""
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append((level, title))


def heading_path(stack: list[tuple[int, str]]) -> tuple[str, ...]:
    return tuple(title for _, title in stack)
