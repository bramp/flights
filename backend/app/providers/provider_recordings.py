"""Record and replay raw flight-provider responses without network access."""

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
    """Save a provider body on parse failure or when recording is enabled."""
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
