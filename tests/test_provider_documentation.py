"""Verify that provider documentation examples run without live requests."""

from __future__ import annotations

import doctest
import inspect
import subprocess
import sys
from pathlib import Path
from types import ModuleType

import pytest

from backend.app import providers
from backend.app.providers import (
    base,
    google_flights,
    pricing_engine,
    provider_recordings,
    replay_provider_recordings,
)

PROVIDER_MODULES = (
    pytest.param(base, id="base"),
    pytest.param(google_flights, id="google_flights"),
    pytest.param(pricing_engine, id="pricing_engine"),
    pytest.param(provider_recordings, id="provider_recordings"),
    pytest.param(replay_provider_recordings, id="replay_provider_recordings"),
)


@pytest.mark.parametrize("module", PROVIDER_MODULES)
def test_provider_documentation_examples(module: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_live_request(*_args: object, **_kwargs: object) -> None:
        pytest.fail("Provider documentation examples must not make live requests.")

    monkeypatch.setattr(google_flights, "fetch_flights_html", reject_live_request)
    monkeypatch.setattr(google_flights.httpx, "Client", reject_live_request)
    result = doctest.testmod(module)
    assert result.attempted > 0
    assert result.failed == 0


@pytest.mark.parametrize("module", [*PROVIDER_MODULES, pytest.param(providers, id="providers")])
def test_public_provider_api_has_docstrings(module: ModuleType) -> None:
    assert inspect.getdoc(module)
    for name, symbol in inspect.getmembers(module):
        if name.startswith("_") or getattr(symbol, "__module__", None) != module.__name__:
            continue
        if inspect.isfunction(symbol) or inspect.isclass(symbol):
            assert inspect.getdoc(symbol), f"{module.__name__}.{name}"
        if inspect.isclass(symbol):
            for method_name, method in inspect.getmembers(symbol, inspect.isfunction):
                if not method_name.startswith("_") and method.__module__ == module.__name__:
                    assert inspect.getdoc(method), f"{module.__name__}.{name}.{method_name}"


def test_documented_replay_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provider_recordings, "RECORDING_DIR", tmp_path)
    monkeypatch.setenv("FARESPLIT_RECORD_PROVIDER_RESPONSES", "1")
    query = {
        "origin": "SFO",
        "destination": "LHR",
        "departure_date": "2026-11-10",
        "cabin": "economy",
    }
    path = provider_recordings.record_provider_response("serpapi", query, "{}")
    assert path is not None

    # The interpreter, module, and temporary directory are controlled by this test.
    completed = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "backend.app.providers.replay_provider_recordings", str(tmp_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert f"{path.name}: serpapi: parsed 0 flight option(s)" in completed.stderr
