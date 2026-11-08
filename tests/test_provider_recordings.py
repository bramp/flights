"""Tests for recording and replaying provider responses without network access."""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable
from datetime import date
from pathlib import Path

import httpx
import pytest

from backend.app.models.queries import LegSearch, SearchIssueKind, SearchStatus
from backend.app.models.schemas import ConcreteCabinClass, ProviderMode
from backend.app.providers import google_flights, provider_recordings
from backend.app.providers.google_flights import CompositeFlightProvider
from backend.app.providers.replay_provider_recordings import replay_recording


def test_parser_failure_is_recorded_and_replayable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    html = '<script class="ds:1">AF_initDataCallback({data: null, sideChannel: {}});</script>'
    monkeypatch.setattr(provider_recordings, "RECORDING_DIR", tmp_path)
    monkeypatch.setattr(google_flights, "fetch_flights_html", lambda _query: html)
    monkeypatch.delenv("FARESPLIT_RECORD_PROVIDER_RESPONSES", raising=False)

    provider = CompositeFlightProvider(mode=ProviderMode.FAST_FLIGHTS, rate_limit_seconds=0)
    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    result = provider.search(query)

    assert result.status == SearchStatus.FAILED
    files = list(tmp_path.glob("*.json.gz"))
    assert len(files) == 1
    with gzip.open(files[0], "rt", encoding="utf-8") as stream:
        recording = json.load(stream)
    assert recording["provider"] == "fast_flights"
    assert recording["query"] == {
        "origin": "SFO",
        "destination": "LHR",
        "departure_date": "2026-11-10",
        "cabin": "business",
    }
    assert recording["parse_error"] == "TypeError"
    assert recording["body"] == html
    assert "api_key" not in json.dumps(recording)
    with pytest.raises(TypeError):
        replay_recording(files[0])


def test_opt_in_recording_can_be_replayed_without_fetching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fast_flights_html: Callable[[object], str]
) -> None:
    monkeypatch.setattr(provider_recordings, "RECORDING_DIR", tmp_path)
    monkeypatch.setenv("FARESPLIT_RECORD_PROVIDER_RESPONSES", "1")
    monkeypatch.setattr(
        google_flights,
        "fetch_flights_html",
        lambda _query: pytest.fail("Replay must not fetch a provider response"),
    )
    query = {
        "origin": "SFO",
        "destination": "LHR",
        "departure_date": "2026-11-10",
        "cabin": "business",
    }
    path = provider_recordings.record_provider_response("fast_flights", query, fast_flights_html([None]))
    assert path is not None
    assert replay_recording(path) == "fast_flights: parsed 0 flight option(s)"


def test_serpapi_parse_failure_records_body_without_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provider_recordings, "RECORDING_DIR", tmp_path)
    monkeypatch.delenv("FARESPLIT_RECORD_PROVIDER_RESPONSES", raising=False)
    provider = CompositeFlightProvider(mode=ProviderMode.SERPAPI, rate_limit_seconds=0)
    provider.serpapi_key = "private-test-key"
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, text="{"))
    client = httpx.Client
    monkeypatch.setattr(
        google_flights.httpx,
        "Client",
        lambda **_kwargs: client(transport=transport),
    )

    query = LegSearch.single("SFO", "LHR", date(2026, 11, 10), ConcreteCabinClass.BUSINESS)
    result = provider.search(query)

    assert result.status == SearchStatus.FAILED
    assert result.issues[0].kind == SearchIssueKind.PROVIDER_ERROR
    files = list(tmp_path.glob("*.json.gz"))
    assert len(files) == 1
    with gzip.open(files[0], "rt", encoding="utf-8") as stream:
        recording = json.load(stream)
    assert recording["provider"] == "serpapi"
    assert recording["body"] == "{"
    assert recording["parse_error"] == "JSONDecodeError"
    assert "private-test-key" not in json.dumps(recording)
    with pytest.raises(json.JSONDecodeError):
        replay_recording(files[0])
