"""Tests for the airline directory loaded from airlines.json and carrier metadata resolution."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.app.data.airlines import AIRLINES, MAJOR_ALLIANCES, VALID_CLASSIFICATIONS, _load_airlines
from backend.app.providers.google_flights import resolve_airline_metadata
from backend.app.providers.pricing_engine import CARRIERS


def _write(tmp_path: Path, records: list[dict[str, object]]) -> Path:
    path = tmp_path / "airlines.json"
    path.write_text(json.dumps(records), encoding="utf-8")
    return path


def _major_alliance_records() -> list[dict[str, object]]:
    return [{"code": f"X{i}", "alliance": alliance} for i, alliance in enumerate(MAJOR_ALLIANCES)]


def test_airlines_json_lists_every_major_alliance() -> None:
    present = {a.alliance for a in AIRLINES.values()}
    assert set(MAJOR_ALLIANCES) <= present
    assert present <= VALID_CLASSIFICATIONS


def test_simulated_carriers_match_airline_directory() -> None:
    for carrier in CARRIERS:
        airline = AIRLINES[carrier.code]
        assert (carrier.name, carrier.alliance, carrier.is_lcc, carrier.bag_fee_usd) == (
            airline.name,
            airline.alliance,
            airline.is_lcc,
            airline.bag_fee_usd,
        )


def test_loader_rejects_unknown_alliance(tmp_path: Path) -> None:
    path = _write(tmp_path, [*_major_alliance_records(), {"code": "ZZ", "alliance": "Star Aliance"}])
    with pytest.raises(ValueError, match="Unknown alliance"):
        _load_airlines(path)


def test_loader_rejects_missing_major_alliance(tmp_path: Path) -> None:
    path = _write(tmp_path, _major_alliance_records()[:-1])
    with pytest.raises(ValueError, match=MAJOR_ALLIANCES[-1]):
        _load_airlines(path)


def test_loader_rejects_duplicate_and_invalid_codes(tmp_path: Path) -> None:
    duplicate = _write(tmp_path, [*_major_alliance_records(), {"code": "X0", "alliance": "LCC"}])
    with pytest.raises(ValueError, match="Duplicate"):
        _load_airlines(duplicate)
    invalid = _write(tmp_path, [*_major_alliance_records(), {"code": "ua", "alliance": "LCC"}])
    with pytest.raises(ValueError, match="Invalid airline code"):
        _load_airlines(invalid)


@pytest.mark.parametrize(
    ("code", "name", "expected"),
    [
        ("UA", "", ("UA", "Star Alliance", False, 40.0)),
        ("A3", "", ("A3", "Star Alliance", False, 40.0)),
        ("NK", "", ("NK", "LCC", True, 50.0)),
        ("", "Ryanair DAC", ("FR", "LCC", True, 60.0)),
        ("Q9", "", ("Q9", "Non-Aligned", False, 45.0)),
    ],
)
def test_resolve_airline_metadata(code: str, name: str, expected: tuple[str, str, bool, float]) -> None:
    assert resolve_airline_metadata(code, name) == expected
