"""Two-tier SQLite cache for granular individual flights and multi-slice ticket quotes."""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date
from pathlib import Path

from backend.app.models.schemas import (
    CacheStats,
    ConcreteCabinClass,
    FlightLegOption,
)


class FlightCache:
    """Persistent SQLite store indexing both individual flights and slice queries."""

    def __init__(self, db_path: str | Path = "flights_cache.db", ttl_seconds: int = 86400 * 7) -> None:
        self.db_path = Path(db_path)
        self.ttl_seconds = ttl_seconds
        self.session_hits = 0
        self.session_misses = 0
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS leg_search_cache (
                    cache_key TEXT PRIMARY KEY,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    departure_date TEXT NOT NULL,
                    cabin TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS granular_flights (
                    leg_id TEXT PRIMARY KEY,
                    origin TEXT NOT NULL,
                    destination TEXT NOT NULL,
                    departure_date TEXT NOT NULL,
                    cabin TEXT NOT NULL,
                    airline TEXT NOT NULL,
                    alliance TEXT NOT NULL,
                    one_way_fare REAL NOT NULL,
                    rt_half_fare REAL NOT NULL,
                    duration_hours REAL NOT NULL,
                    stops_count INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_granular_lookup
                ON granular_flights (origin, destination, departure_date, cabin)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_quote_cache (
                    quote_key TEXT PRIMARY KEY,
                    ticket_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )

    def reset_session_counters(self) -> None:
        self.session_hits = 0
        self.session_misses = 0

    @staticmethod
    def make_leg_key(
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> str:
        return f"{origin.upper()}:{destination.upper()}:{departure_date.isoformat()}:{cabin.value}"

    def get_leg_options(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
    ) -> list[FlightLegOption] | None:
        key = self.make_leg_key(origin, destination, departure_date, cabin)
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, updated_at FROM leg_search_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if row and (now - float(row["updated_at"])) <= self.ttl_seconds:
                self.session_hits += 1
                raw_list = json.loads(row["payload_json"])
                options = [FlightLegOption.model_validate(item) for item in raw_list]
                for opt in options:
                    opt.from_cache = True
                return options

            # Fallback: check granular_flights table
            rows = conn.execute(
                """
                SELECT payload_json, updated_at
                FROM granular_flights
                WHERE origin = ? AND destination = ? AND departure_date = ? AND cabin = ?
                """,
                (origin.upper(), destination.upper(), departure_date.isoformat(), cabin.value),
            ).fetchall()
            valid_rows = [r for r in rows if (now - float(r["updated_at"])) <= self.ttl_seconds]
            if valid_rows:
                self.session_hits += 1
                options = [FlightLegOption.model_validate(json.loads(r["payload_json"])) for r in valid_rows]
                for opt in options:
                    opt.from_cache = True
                return options

        self.session_misses += 1
        return None

    def store_leg_options(
        self,
        origin: str,
        destination: str,
        departure_date: date,
        cabin: ConcreteCabinClass,
        options: list[FlightLegOption],
    ) -> None:
        key = self.make_leg_key(origin, destination, departure_date, cabin)
        now = time.time()
        serialized_list = json.dumps([opt.model_dump(mode="json") for opt in options])
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO leg_search_cache
                (cache_key, origin, destination, departure_date, cabin, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    key,
                    origin.upper(),
                    destination.upper(),
                    departure_date.isoformat(),
                    cabin.value,
                    serialized_list,
                    now,
                ),
            )
            for opt in options:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO granular_flights
                    (leg_id, origin, destination, departure_date, cabin, airline, alliance,
                     one_way_fare, rt_half_fare, duration_hours, stops_count, payload_json, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        opt.leg_id,
                        opt.origin.upper(),
                        opt.destination.upper(),
                        opt.departure_date.isoformat(),
                        opt.cabin.value,
                        opt.airline,
                        opt.alliance,
                        opt.one_way_base_fare_usd,
                        opt.round_trip_half_fare_usd,
                        opt.duration_hours,
                        opt.stops_count,
                        json.dumps(opt.model_dump(mode="json")),
                        now,
                    ),
                )

    def clear_all(self) -> None:
        with self._connect() as conn:
            conn.execute("DELETE FROM leg_search_cache")
            conn.execute("DELETE FROM granular_flights")
            conn.execute("DELETE FROM ticket_quote_cache")
        self.reset_session_counters()

    def get_ticket_quote(self, quote_key: str) -> dict[str, object] | None:
        """Retrieve a cached multi-slice ticket quote (RT, Open-Jaw, Multi-City) by signature."""
        now = time.time()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT payload_json, updated_at FROM ticket_quote_cache WHERE quote_key = ?",
                (quote_key,),
            ).fetchone()
            if row and (now - float(row["updated_at"])) <= self.ttl_seconds:
                self.session_hits += 1
                data: dict[str, object] = json.loads(row["payload_json"])
                return data
        self.session_misses += 1
        return None

    def store_ticket_quote(
        self,
        quote_key: str,
        ticket_type: str,
        payload: dict[str, object],
    ) -> None:
        """Store a priced multi-slice ticket quote in SQLite."""
        now = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO ticket_quote_cache
                (quote_key, ticket_type, payload_json, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (quote_key, ticket_type, json.dumps(payload), now),
            )

    def get_stats(self) -> CacheStats:
        with self._connect() as conn:
            flights_count = conn.execute("SELECT COUNT(*) AS cnt FROM granular_flights").fetchone()["cnt"]
            leg_queries_count = conn.execute("SELECT COUNT(*) AS cnt FROM leg_search_cache").fetchone()["cnt"]
            ticket_quotes_count = conn.execute("SELECT COUNT(*) AS cnt FROM ticket_quote_cache").fetchone()["cnt"]
        return CacheStats(
            cache_hits=self.session_hits,
            cache_misses=self.session_misses,
            total_cached_flights_in_db=int(flights_count),
            total_cached_quotes_in_db=int(leg_queries_count) + int(ticket_quotes_count),
        )
