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


@pytest.fixture
def fast_flights_unpriced_html(fast_flights_html: Callable[[object], str]) -> str:
    segment: list[object] = [None] * 22
    segment[3:7] = ["SFO", "San Francisco", "London", "LHR"]
    segment[8], segment[10] = [9], [11]
    segment[11], segment[17] = 120, "Test aircraft"
    segment[20] = segment[21] = [2026, 12, 11]
    flight: list[object] = [None] * 23
    flight[0:3] = ["nonstop", ["Test Airline"], [segment]]
    flight[22] = [None] * 7 + [100000, 120000]
    return fast_flights_html([[[flight, []]]])
