"""Replay compressed flight-provider responses without network access.

Run ``python -m backend.app.providers.replay_provider_recordings`` to replay
the default recording directory, or pass another directory as an argument.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
from datetime import date
from pathlib import Path

from fast_flights.parser import parse as parse_fast_flights

from backend.app.models.schemas import ConcreteCabinClass
from backend.app.providers.google_flights import CompositeFlightProvider
from backend.app.providers.provider_recordings import RECORDING_DIR

_LOGGER = logging.getLogger(__name__)


def replay_recording(path: Path) -> str:
    """Parse one saved provider response without making a remote request.

    The recording must identify ``fast_flights`` or ``serpapi`` and include
    the recorded body and query fields for origin, destination, ISO departure
    date, and cabin. Parsing can update the in-memory airline, airport, and
    observed-duration registries, as it does for a live response.

    Args:
        path: Path to a gzip-compressed JSON recording.

    Returns:
        A summary containing the provider name and parsed option count.

    Raises:
        OSError: If the file cannot be read.
        KeyError: If a required recording or query field is missing.
        ValueError: If the provider, cabin, date, or response body is invalid.
            Parser exceptions can also propagate.

    Examples:
        >>> import os
        >>> from pathlib import Path
        >>> from tempfile import TemporaryDirectory
        >>> from unittest.mock import patch
        >>> from backend.app.providers import provider_recordings as recordings
        >>> from backend.app.providers.replay_provider_recordings import replay_recording
        >>> query = {
        ...     "origin": "SFO", "destination": "LHR",
        ...     "departure_date": "2026-11-10", "cabin": "economy",
        ... }
        >>> with TemporaryDirectory() as directory:
        ...     with patch.object(recordings, "RECORDING_DIR", Path(directory)):
        ...         with patch.dict(os.environ, {"FARESPLIT_RECORD_PROVIDER_RESPONSES": "1"}):
        ...             path = recordings.record_provider_response("serpapi", query, "{}")
        ...             assert path is not None
        ...             replay_recording(path)
        'serpapi: parsed 0 flight option(s)'
    """
    with gzip.open(path, "rt", encoding="utf-8") as stream:
        recording = json.load(stream)

    provider = recording["provider"]
    query = recording["query"]
    body = recording["body"]
    cabin = ConcreteCabinClass(query["cabin"])
    departure_date = date.fromisoformat(query["departure_date"])

    if provider == "fast_flights":
        if not isinstance(body, str):
            raise ValueError(f"{path}: fast-flights recording body must be HTML text")
        parsed = parse_fast_flights(body)
        options = CompositeFlightProvider.parse_fast_flights_results(
            parsed,
            query["origin"],
            query["destination"],
            departure_date,
            cabin,
        )
    elif provider == "serpapi":
        if not isinstance(body, str):
            raise ValueError(f"{path}: SerpApi recording body must be JSON text")
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: SerpApi recording must contain a JSON object")
        options = CompositeFlightProvider.parse_google_flights_payload(
            data,
            query["origin"],
            query["destination"],
            departure_date,
            cabin,
        )
    else:
        raise ValueError(f"{path}: unsupported provider {provider!r}")

    return f"{provider}: parsed {len(options)} flight option(s)"


def main() -> None:
    """Replay compressed provider recordings from the command line.

    Process files in name order and log the result of each replay. Recognized
    file and parsing errors are logged so later files can still be processed.

    Raises:
        SystemExit: If no recordings are found or the command-line arguments
            are invalid.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=RECORDING_DIR)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    paths = sorted(args.directory.glob("*.json.gz"))
    if not paths:
        raise SystemExit(f"No provider recordings found in {args.directory}")
    for path in paths:
        try:
            _LOGGER.info("%s: %s", path.name, replay_recording(path))
        except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            _LOGGER.error("%s: replay failed (%s): %s", path.name, type(exc).__name__, exc)


if __name__ == "__main__":
    main()
