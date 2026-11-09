"""Verify the doctest network guard and its support for mocks."""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path
from typing import Literal

import httpx
import pytest
from fast_flights import Query, fetcher
from fast_flights.integrations.base import FetchIntegration

pytest_plugins = ("pytester",)

_BLOCK_MESSAGE = "Doctests must not make live network requests"


@pytest.fixture
def mocked_http_client() -> Iterator[httpx.Client]:
    def respond(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="ok")

    with httpx.Client(transport=httpx.MockTransport(respond), trust_env=False) as client:
        yield client


class StubFetchIntegration(FetchIntegration):
    def fetch_html(self, _query: Query | str, /) -> str:
        return "mock flights"


@pytest.mark.usefixtures("block_doctest_network")
class TestDoctestNetworkGuard:
    def test_blocks_fast_flights(self) -> None:
        with pytest.raises(pytest.fail.Exception, match=_BLOCK_MESSAGE):
            fetcher.Client()

    def test_blocks_name_resolution(self) -> None:
        with pytest.raises(pytest.fail.Exception, match=_BLOCK_MESSAGE):
            socket.getaddrinfo("127.0.0.1", 80)

    @pytest.mark.parametrize("operation", ["connect", "connect_ex"])
    def test_blocks_socket_connections(self, operation: Literal["connect", "connect_ex"]) -> None:
        with socket.socket() as connection:
            connect = connection.connect if operation == "connect" else connection.connect_ex
            with pytest.raises(pytest.fail.Exception, match=_BLOCK_MESSAGE):
                connect(("127.0.0.1", 1))

    def test_blocks_http_requests(self) -> None:
        with httpx.Client(trust_env=False) as client, pytest.raises(pytest.fail.Exception, match=_BLOCK_MESSAGE):
            client.get("http://127.0.0.1:1")

    def test_allows_mocked_http(self, mocked_http_client: httpx.Client) -> None:
        assert mocked_http_client.get("https://example.invalid").text == "ok"

    def test_allows_mocked_fast_flights(self) -> None:
        assert fetcher.fetch_flights_html("query", fetch_integration=StubFetchIntegration()) == "mock flights"


def test_guard_applies_automatically_to_doctests(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    pytester.makeconftest((Path(__file__).resolve().parents[1] / "conftest.py").read_text())
    example = '''
        """
        >>> import socket
        >>> socket.getaddrinfo("127.0.0.1", 80)
        """
        import socket

        def test_regular():
            assert socket.getaddrinfo("127.0.0.1", 80)
    '''
    pytester.makepyfile(test_first=example, test_second=example)
    result = pytester.runpytest_subprocess("--doctest-modules", "-q")
    result.assert_outcomes(failed=2, passed=2)
    result.stdout.fnmatch_lines([f"*{_BLOCK_MESSAGE}*", f"*{_BLOCK_MESSAGE}*"])


def test_regular_tests_can_resolve_loopback() -> None:
    assert socket.getaddrinfo("127.0.0.1", 80, socket.AF_INET, socket.SOCK_STREAM)
