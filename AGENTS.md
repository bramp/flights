# AGENTS.md — AI Coding Agent Guidelines

## Project Overview
This repository implements **FareSplit**, the multi-city flight schedule and ticket-partitioning optimizer described in [DESIGN.md](DESIGN.md).
See [DEVELOPER.md](DEVELOPER.md) for the directory structure and development commands, and [README.md](README.md) for user-facing behavior.

## Coding Standards & Best Practices
1. **Strict Type Annotations:** Use Python 3.12+ type syntax (`list[str]`, `dict[str, Any]`, `X | None`) across all functions and classes.
2. **Pure Solver Logic:** Keep solver algorithms (`route_dag.py`, `hub_splitter.py`, `partitioner.py`, `pareto.py`, `optimizer.py`) decoupled from HTTP/FastAPI concerns and unit-tested.
3. **Cache-First Discipline:** Every external flight or multi-slice quote lookup must go through `CachedFlightProvider` / `FlightCache` (`sqlite_cache.py`).
4. **No Hidden-City Ticketing:** Never generate throwaway or hidden-city tickets; every leg of every booked ticket must be flown in sequence by the passenger.
5. **Git Hygiene:**
   - Never run `git add .` — always stage explicit files relevant to the change.
   - Do not commit unless explicitly requested by the user.
6. **Verification & Formatting:** Always run `uv run ruff format .`, `uv run ruff check .`, `node --check backend/app/static/app.js`, and `uv run pytest` after making code changes (also enforced automatically via `.pre-commit-config.yaml`).
