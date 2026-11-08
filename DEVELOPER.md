# DEVELOPER.md — Developer Guide & Best Practices

## Prerequisites
- **Python:** 3.12+ (managed via [`uv`](https://docs.astral.sh/uv/))
- **SQLite3:** Built into Python standard library (`sqlite3`)
- **Node.js:** 20+ and npm for the Playwright UX tests

## Quick Start

### 1. Install Dependencies
```bash
uv sync
npm ci
npx playwright install chromium
```

### 2. Run the Application Server
```bash
uv run uvicorn backend.app.main:app --reload --port 8000
```
Then open **http://127.0.0.1:8000** in your browser.

### 3. Run Formatting, Linting & Tests
```bash
uv run ruff format .
uv run ruff check --fix .
node --check backend/app/static/app.js
uv run pytest
npm run test:ux
```

The Playwright suite serves the real frontend on port **8765** and mocks every
`/api/` request. It does not start the FastAPI backend, contact flight providers,
or consume API quota. Keep port 8765 free when running it.

Tests run in desktop and mobile Chromium, covering Optimize submissions and
loading states, results and ticket details, strategy selection, stale results,
HTTP/network errors and retry, trip editing, saved state, reset, and cache clearing.
Uncaught browser errors and unexpected API requests fail the tests. Failed tests
save screenshots and traces under `test-results/`.

The API and real-backend browser tests use temporary SQLite databases and never
clear the application's `flights_cache.db`. Importing the ASGI application does
not create a cache; the default cache is opened when the server starts. Set
`PLAYWRIGHT_TEST_OUTPUT_DIR` to change the browser artifact directory when existing
test results need to be preserved.

Use `npm run test:ux:ui` for the interactive test runner. For a fresh CI machine,
install the browser and OS dependencies with `npx playwright install --with-deps chromium`
after `npm ci`.

### Test-Only Simulation

Normal servers never generate simulated flights, even when live providers fail or
reach their query limit. `provider_mode="offline"` requests are rejected unless
the server explicitly has `FARESPLIT_TESTING=1`.

```bash
FARESPLIT_TESTING=1 uv run uvicorn backend.app.main:app --host 127.0.0.1 --port 8001
```

This reveals a **Simulated data (testing)** checkbox. Simulation is exclusive of
live data and bypasses all flight and quote cache reads/writes. Do not enable this
flag on a deployed server. Tests that need the real simulation engine opt in via
scoped environment fixtures; mocked browser tests do not require the flag.

Cache initialization removes old simulated entries and invalidates legacy ticket
quotes lacking source metadata. Existing live flights and lifetime usage counters
are retained.

### 4. Pre-Commit Hooks
Pre-commit hooks are configured in `.pre-commit-config.yaml` and installed into `.git/hooks/pre-commit`:
```bash
uv run pre-commit install
uv run pre-commit run --all-files
```
Every commit automatically runs:
1. `ruff check --fix` (Python linting & import sorting)
2. `ruff format` (Python code formatting)
3. `node --check` (Frontend JavaScript syntax validation)
4. `pytest -q` (Unit & API test suite)
5. `npm run test:ux` (Mocked-backend desktop & mobile browser tests)

---

## Codebase Structure

```text
flights/
├── README.md                        # End-user guide & quick start
├── DESIGN.md                        # Problem formulation & solver architecture
├── DEVELOPER.md                     # Developer setup, directory layout & tooling
├── AGENTS.md                        # Coding standards for AI agents
├── pyproject.toml                   # Project metadata, dependencies, ruff & pytest config
├── backend/
│   └── app/
│       ├── main.py                  # FastAPI routes, static UI hosting, API endpoints
│       ├── models/
│       │   └── schemas.py           # Pydantic v2 models for inputs, flights, tickets, results
│       ├── data/
│       │   ├── airports.json        # Editable airport records, coordinates & nearby alternatives
│       │   └── airports.py          # Airport loading, metro areas, search & distance helpers
│       ├── cache/
│       │   └── sqlite_cache.py      # SQLite cache (leg_search_cache, granular_flights, ticket_quote_cache)
│       ├── providers/
│       │   ├── base.py              # Abstract FlightSearchProvider + CachedFlightProvider wrapper
│       │   ├── google_flights.py    # Live Google Flights / SerpApi parser & composite provider
│       │   └── pricing_engine.py    # Deterministic test-only flight and fare simulation
│       ├── solver/
│       │   ├── cabin.py             # Per-leg and duration-threshold cabin class resolver
│       │   ├── route_dag.py         # Date-window & flexible city-order schedule generator
│       │   ├── hub_splitter.py      # Intermediate hub splitting & self-transfer buffer evaluator
│       │   ├── partitioner.py       # Set partitioning (Single MC, Open-Jaw, Nested RT, One-Way, Hub Split)
│       │   ├── pareto.py            # Generalized cost scoring & Pareto dominance frontier
│       │   └── optimizer.py         # End-to-end orchestrator
│       └── static/
│           ├── index.html           # Compact timeline matrix & comparison UI
│           ├── styles.css           # Responsive styling
│           └── app.js               # State management, cookie persistence & interactive date grid
└── tests/
    ├── test_airports_and_cabin.py
    ├── test_cache.py
    ├── test_route_dag.py
    ├── test_partitioner.py
    └── test_api.py
```

---

## Key Implementation Details

- **Airport Directory:** Edit `backend/app/data/airports.json` to add or update airports. Each record contains `code` (unique IATA code), `name`, `city`, `country` (two-letter code), `region` (`NA`, `EU`, `ASIA`, `ME`, `OC`, or `SA`), `lat`, `lon`, `metro_code`, `is_major_hub`, and `nearby_codes` (an array of airport codes). Airports in the same metropolitan area share a `metro_code`; nearby alternatives may belong to different metros. Restart the server after editing the file. Display-specific country names, city distances, and metro groupings remain in `airports.py`.
- **SQLite Caching (`backend/app/cache/sqlite_cache.py`):** Stores leg search results in `leg_search_cache`, individual flight legs in `granular_flights`, and multi-slice ticket quotes in `ticket_quote_cache` inside `flights_cache.db`.
- **Flight Searches:** Providers and the cache accept a normalized `LegSearch` with ordered origin/destination airport tuples, date, and cabin. Repeated searches are reused within one optimization run, including when force refresh bypasses SQLite. Persistent search entries also include the provider mode and effective transport layover limit. Pre-existing entries without that scope are retained but are not reused.
- **Search Outcomes:** Providers return a `SearchResult` with options, a `complete`, `partial`, or `failed` status, and explicit issues. Only complete, nonempty live searches are persisted. Budget limits, provider failures, and intentionally skipped airport pairs are reported in optimization warnings. A successful fallback can complete a search; programming errors still propagate. Earlier search cache versions are retained but ignored because they did not prove completeness.
- **Client-Side Persistence (`backend/app/static/app.js`):** Automatically saves user state to the `faresplit_trip_state_v1` browser cookie and `localStorage` on every change.
