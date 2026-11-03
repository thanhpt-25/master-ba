"""Offline guarantee for knowledge tests (Requirement 15.5)."""

import socket
from collections.abc import Iterator
from typing import Any, NoReturn

import pytest

ONLINE_MARKERS = ("live", "rag_eval")


@pytest.fixture(autouse=True)
def no_network(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Fail the test on any socket connect unless it carries the `live` or `rag_eval` marker."""
    if any(request.node.get_closest_marker(name) for name in ONLINE_MARKERS):
        yield
        return

    def _refuse(self: socket.socket, address: Any) -> NoReturn:
        pytest.fail(f"network access attempted in an offline test: connect({address!r})")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    yield
