import socket

import pytest


def test_connect_fails_the_test() -> None:
    with (
        socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock,
        pytest.raises(pytest.fail.Exception, match="network access attempted"),
    ):
        sock.connect(("127.0.0.1", 9))


def test_create_connection_is_blocked() -> None:
    with pytest.raises(pytest.fail.Exception, match="network access attempted"):
        socket.create_connection(("127.0.0.1", 9), timeout=1)
