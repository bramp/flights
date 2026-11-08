"""Synthetic upstream HTML fixtures that exercise the real fast-flights parser."""

from __future__ import annotations

import json
from collections.abc import Callable

import pytest


def _response_html(payload: object) -> str:
    return f'<script class="ds:1">AF_initDataCallback({{data: {json.dumps(payload)}, sideChannel: {{}}}});</script>'


def _flight_payload(results: object) -> list[object]:
    return [None, None, None, results, None, None, None, [None, [[], []]]]


MALFORMED_RESPONSES: dict[str, tuple[str, type[Exception]]] = {
    "missing-script": ("<html><body>Temporarily unavailable</body></html>", AttributeError),
    "missing-data": ('<script class="ds:1">AF_initDataCallback({});</script>', IndexError),
    "invalid-json": (
        '<script class="ds:1">AF_initDataCallback({data: invalid, sideChannel: {}});</script>',
        json.JSONDecodeError,
    ),
    "wrong-root": (_response_html({}), KeyError),
    "null-root": (_response_html(None), TypeError),
    "invalid-metadata": (
        _response_html([None, None, None, [None], None, None, None, [None, [[["SA", "Star", "extra"]], []]]]),
        ValueError,
    ),
}


@pytest.fixture(params=tuple(MALFORMED_RESPONSES))
def malformed_fast_flights_response(request: pytest.FixtureRequest) -> tuple[str, type[Exception]]:
    return MALFORMED_RESPONSES[request.param]


@pytest.fixture
def fast_flights_html() -> Callable[[object], str]:
    def render(results: object) -> str:
        return _response_html(_flight_payload(results))

    return render
