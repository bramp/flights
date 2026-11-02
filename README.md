# FareSplit — Multi-City Flight & Ticket Partition Optimizer

**FareSplit** is a multi-city flight schedule and ticket-partitioning optimizer. Give it the cities you want to visit, the ranges of dates you're happy to be in each city, how many nights you want to stay, and your per-flight cabin class preferences — and it figures out both **when/what order to fly** and **how to structure your tickets** (1 Single Multi-City Ticket vs. Anchor Open-Jaw + Regional One-Ways vs. Nested Multi-Stop Tickets vs. All One-Ways vs. Intermediate Hub Splits).

---

## Quick Start

### 1. Install Dependencies
Make sure you have Python 3.12+ and [`uv`](https://docs.astral.sh/uv/) installed:
```bash
uv sync
```

### 2. Start the App Server
```bash
uv run uvicorn backend.app.main:app --reload --port 8000
```

### 3. Open the Web UI
Open **[http://127.0.0.1:8000](http://127.0.0.1:8000)** in your browser.

---

## How to Use the App

### 1. Set Your Overall Trip Window & Global Rules (Top Toolbar)
At the top of the planner card:
- **Trip Window (`Start Date → End Date`):** Sets the earliest possible departure date and latest possible return date for the entire trip. These dates define the columns of the interactive date grid below.
- **City Order:**
  - **Flexible (Respect 📌 Pins):** Keeps any pinned city (`📌`) locked in its position while testing better orderings for unpinned cities.
  - **Fixed Sequence:** Visits cities strictly in the top-to-bottom row order shown.
  - **Auto-Order All (TSP):** Automatically finds the best geographic/price ordering across all stops.
- **Baggage (All Flights):** Toggle **🧳 Carry-On** and choose **0, 1, or 2 Checked Bags**. Checked bags automatically add carrier baggage fees on split/LCC tickets and increase the minimum safe self-transfer buffer at intermediate hubs from `4.0h` to `5.5h`.
- **✨ "Auto" Cabin Rule:** Defines how legs set to `✨ Auto` resolve their cabin class based on flight duration (e.g., *Economy under `6.5` hours, else Business*).
- **⚙️ Weights & Hub Rules:** Click to expand sliders for **Value of Your Time (`$/hr`)**, **Protected Stop Penalty**, **Self-Transfer Split Penalty**, and toggling **Intermediate Hub Ticket Splitting**.

---

### 2. Configure Your Stops & Date Ranges on the Timeline Grid
Each row in the matrix represents a location:
- **`START` Row (Origin):**
  - Type a city or IATA code (e.g., `San Francisco` or `SFO`).
  - Click the airport pill (`SFO, OAK, SJC ▾`) to toggle local/metro airports on or off, or add a custom 3-letter airport code.
  - **Departure Date Range:** Click or drag across the green `DEP` cells on the grid to mark the range of dates you're willing to depart.
- **City Stop Rows (`#1`, `#2`, `#3`, …):**
  - **City & Airports:** Search for a city and click the airport dropdown pill (e.g., `LHR, LGW ▾` or `CDG, ORY ▾`) to include or exclude nearby metro airports.
  - **Stay Length (`3–5n`):** Set the minimum and maximum nights you want to stay in that city.
  - **Row Controls (`📌 ↑ ↓ ✕`):** Pin a stop's sequence position (`📌`), move it up/down (`↑`/`↓`), or remove it (`✕`). Use **+ Add City Row** in the toolbar to add more cities.
  - **Allowed Date Range (Blue Heatmap Cells):**
    - **Click and drag** across the date columns on any stop row to paint the window of dates it is OK to be in that city.
    - **Single-click** any cell outside the current window to expand the range to that date, or click inside the window to move the nearest boundary.
- **`END` Row (Return):**
  - Defaults to returning to your Origin city (uncheck *"Return to same city as Origin"* inside **⚙️ Weights & Hub Rules** for open-ended trips).
  - Click or drag across the amber `RET` cells to set your allowed return date window.

---

### 3. Pick Cabin Classes Between Rows
Between every pair of rows is a full-width **Flight Connector Bar** (`✈️ Flight 1: SFO → LHR`):
- Click **`✨ Auto`** to let the duration rule pick the cabin class (the resolved cabin pill next to `Auto` highlights automatically in soft blue so you can see what `Auto` chose).
- Or click **`Economy`**, **`Premium Econ`**, **`Business`**, or **`First`** to lock a specific cabin class for that flight leg.

---

### 4. Compare Ticket Strategies & Inspect Bookings
Click **🔍 Optimize Flights & Ticket Combinations** (or load one of the presets from the top-right **Load Example Trip…** dropdown):
1. **Optimal Stay Overlay on the Grid:** The chosen dates for each stop light up in dark blue (`LHR`, `CDG`, `CIA`) directly inside the timeline grid, alongside `✈️ DEP` and `✈️ RET`.
2. **Ticket Strategy Comparison Table:** Compares all 5 ticketing strategies side-by-side:
   - **Anchor Open-Jaw / Round-Trip + Regional One-Ways** *(often cheapest when mixing long-haul Business with short-haul Economy/LCCs)*
   - **2 Nested Multi-Stop Tickets (Outer + Inner)**
   - **1 Single Multi-City Ticket (1 PNR)** *(baseline with full connection protection)*
   - **Hub-Split via Gateway Hub** *(virtual interlining with a mandatory 4.0h–5.5h self-transfer buffer)*
   - **All Separate One-Way Tickets**
3. **Click Any Strategy Row:** Clicking a row in the comparison table updates the **Ticket Breakdown** below it (showing every separate PNR to book, exact flight numbers, cabin tags, base fare vs. bag fees, and booking instructions) and updates the highlighted stay dates on the grid above.

---

## Caching, Persistence & Live Google Flights Data

- **Browser Cookie & LocalStorage Persistence:** All of your stops, airport selections, date windows, cabin rules, baggage settings, and sliders are automatically saved in a browser cookie (`faresplit_trip_state_v1`) and `localStorage` on every change (`🍪 Saved`). Reloading the page restores your exact state.
- **Two-Level SQLite Flight Cache (`flights_cache.db`):** Every flight leg and multi-slice ticket quote discovered is persisted locally in SQLite. Tweaking stay durations, cabin rules, or trade-off weights re-evaluates in milliseconds without re-querying flights. Use the **Clear** button in the top bar or check **Force refresh (bypass SQLite cache)** to fetch fresh quotes.
- **Live Google Flights (Optional):** By default, the app works out-of-the-box offline using a deterministic airline/alliance pricing engine. To query live Google Flights via SerpApi, start the server with:
  ```bash
  SERPAPI_KEY="your_serpapi_key" uv run uvicorn backend.app.main:app --reload --port 8000
  ```

---

## Running Formatting, Linter, Pre-Commit & Tests

```bash
uv run ruff format .
uv run ruff check .
node --check backend/app/static/app.js
uv run pytest
```

Pre-commit hooks are configured in `.pre-commit-config.yaml` (and installed via `uv run pre-commit install`) so every commit automatically formats, lints, checks JS syntax, and runs the test suite.
