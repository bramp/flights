"""Verify the documented provider-recording replay command."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from backend.app.providers import provider_recordings


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
