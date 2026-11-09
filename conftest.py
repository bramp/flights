"""Pytest configuration shared by the test suite and module doctests."""

from __future__ import annotations

import socket
from typing import Never

import pytest
from fast_flights import fetcher


@pytest.fixture
def block_doctest_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """Block the flight client and Python socket connections."""

    def reject_live_request(*_args: object, **_kwargs: object) -> Never:
        pytest.fail("Doctests must not make live network requests.", pytrace=False)

    monkeypatch.setattr(fetcher, "Client", reject_live_request)
    monkeypatch.setattr(socket.socket, "connect", reject_live_request)
    monkeypatch.setattr(socket.socket, "connect_ex", reject_live_request)
    monkeypatch.setattr(socket, "getaddrinfo", reject_live_request)


@pytest.fixture(autouse=True)
def prevent_doctest_network(request: pytest.FixtureRequest) -> None:
    """Apply the network guard to doctests without changing other tests."""
    if isinstance(request.node, pytest.DoctestItem):
        request.getfixturevalue("block_doctest_network")
