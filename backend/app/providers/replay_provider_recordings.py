"""Replay compressed flight-provider responses without network access."""

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
    """Parse one saved provider response without making a remote request."""
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
    """Replay all compressed provider recordings in a directory."""
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
