"""Save raw flight-provider responses for offline investigation and replay.

Recordings are gzip-compressed JSON files in ``data/cache/provider-responses``
relative to the current working directory. They contain unredacted input and
must be handled as potentially sensitive local data.
"""

from __future__ import annotations

import gzip
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

RECORDING_DIR = Path("data/cache/provider-responses")
_LOGGER = logging.getLogger(__name__)


def record_provider_response(
    provider: str,
    query: dict[str, str],
    body: str,
    *,
    parse_error: BaseException | None = None,
) -> Path | None:
    """Save a provider response on parse failure or when recording is enabled.

    Record whenever ``parse_error`` is supplied. Otherwise, record only when
    ``FARESPLIT_RECORD_PROVIDER_RESPONSES=1``. The supplied query and body are
    stored as given, without redaction. Do not include credentials in the
    query, and protect the response body and recording file as needed.

    Args:
        provider: Provider identifier. Replay supports ``fast_flights`` and
            ``serpapi``.
        query: Search details needed for replay, including origin, destination,
            ISO departure date, and cabin.
        body: Raw provider response text.
        parse_error: Optional parser failure. Only its class name is stored.

    Returns:
        The path to the saved file, or ``None`` if recording is disabled or
        an operating-system error prevents the write. Write errors are logged.

    Examples:
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from unittest.mock import patch
        >>> from backend.app.providers import provider_recordings as recordings
        >>> query = {
        ...     "origin": "SFO", "destination": "LHR",
        ...     "departure_date": "2026-11-10", "cabin": "economy",
        ... }
        >>> with TemporaryDirectory() as directory:
        ...     with patch.object(recordings, "RECORDING_DIR", Path(directory)):
        ...         path = recordings.record_provider_response(
        ...             "serpapi", query, "{", parse_error=ValueError("Invalid JSON")
        ...         )
        ...         path is not None and path.is_file()
        True
    """
    if parse_error is None and os.environ.get("FARESPLIT_RECORD_PROVIDER_RESPONSES") != "1":
        return None

    recording = {
        "version": 1,
        "provider": provider,
        "recorded_at": datetime.now(UTC).isoformat(),
        "query": query,
        "parse_error": type(parse_error).__name__ if parse_error is not None else None,
        "body": body,
    }
    path = RECORDING_DIR / f"{datetime.now(UTC):%Y%m%dT%H%M%S.%fZ}-{uuid4().hex}.json.gz"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(path, "wt", encoding="utf-8") as stream:
            json.dump(recording, stream, separators=(",", ":"), ensure_ascii=False)
    except OSError:
        _LOGGER.exception("Could not save %s provider response recording to %s", provider, path)
        return None
    return path
