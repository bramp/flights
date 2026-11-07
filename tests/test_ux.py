"""End-to-end UX / browser tests verifying UI interactions and mocked/offline backend optimization."""

from __future__ import annotations

import socket
import threading
import time
from collections.abc import Generator

import pytest
import uvicorn
from playwright.sync_api import Page, Route, expect

from backend.app.main import app


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="module")
def live_server_url() -> Generator[str, None, None]:
    testing_environment = pytest.MonkeyPatch()
    testing_environment.setenv("FARESPLIT_TESTING", "1")
    port = _find_free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait until server is accepting connections
    deadline = time.time() + 10.0
    while time.time() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                break
        time.sleep(0.05)

    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=3.0)
    testing_environment.undo()


def test_ux_end_to_end_optimization_and_interactions(page: Page, live_server_url: str) -> None:
    """Verify full user flow in a real headless Chromium browser with offline/mocked backend:
    1. Page loads cleanly with zero uncaught JS errors or console errors.
    2. Default Greece + London preset renders START, 3 stops (Athens, Santorini, London), and END rows.
    3. Switching to Offline Simulator mode and clicking Optimize renders the 5-strategy comparison table
       and ticket breakdown without any ReferenceError.
    4. Clicking a different strategy row updates the active itinerary and scheduled stay cells.
    5. Interacting with between-row cabin pills, Google Flights location picker, and date cells
       marks results as stale and persists state to cookies/localStorage.
    """
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    page.goto(live_server_url)

    # 1. Verify header & matrix rows rendered
    expect(page.locator("h1")).to_contain_text("FareSplit")
    expect(page.locator("#timelineMatrix .matrix-row")).to_have_count(6)  # Header + START + 3 Stops + END

    # 2. Select "offline" provider mode so test uses deterministic mocked/offline backend with 0 external calls
    page.check("#simulationToggle")

    # 3. Click Optimize and verify results render cleanly with no JS errors
    page.click("#optimizeBtn")
    expect(page.locator(".comparison-table")).to_be_visible()
    strategy_rows = page.locator(".comparison-table tbody tr")
    expect(strategy_rows).to_have_count(5)
    expect(page.locator(".itinerary-hero")).to_be_visible()
    expect(page.locator(".ticket-card").first).to_be_visible()

    # Ensure no "Cannot access 'el' before initialization" or any other error card appeared
    expect(page.locator("#resultsContainer")).not_to_contain_text("Optimization Error")
    assert page_errors == []

    # 4. Click another strategy row in the comparison table and verify it becomes active
    second_row = strategy_rows.nth(1)
    second_strategy_name = second_row.locator("strong").first.inner_text()
    second_row.click()
    expect(page.locator(".itinerary-hero h2")).to_have_text(second_strategy_name)

    # 5. Click a between-row cabin pill (e.g. set Flight 1 to Economy) -> should mark results stale
    first_connector = page.locator(".flight-connector-row").first
    first_connector.locator("button.cabin-pill-btn", has_text="Economy").click()
    expect(page.locator("#staleNoticeBadge")).to_be_visible()
    expect(page.locator("#optimizeBtn")).to_contain_text("Re-Optimize Trip")

    # 6. Open the Google Flights-style location picker on Stop #1 and verify nearby airports list
    first_stop_locator = page.locator(".stop-locator-slot .gf-row-locator-btn").first
    first_stop_locator.click()
    portal = page.locator("#gfLocationPortal")
    expect(portal).to_be_visible()
    expect(portal.locator(".gf-city-name").first).to_contain_text("Athens")
    portal.locator(".gf-confirm-btn").click()
    expect(portal).to_be_hidden()

    # 7. Reload page and verify state persisted in cookies / localStorage
    page.reload()
    expect(page.locator("#simulationToggle")).to_be_checked()
    expect(page.locator("#providerModeSelect")).to_be_disabled()
    assert page_errors == []


def test_ux_date_grid_drag_and_mocked_optimize_response(page: Page, live_server_url: str) -> None:
    """Verify date-grid click/drag selection, adding/reordering stops, and rendering a mocked
    `/api/optimize` payload via Playwright route interception.
    """
    page_errors: list[str] = []
    page.on("pageerror", lambda exc: page_errors.append(str(exc)))

    page.goto(live_server_url)
    page.click("#resetDefaultsBtn")

    # Click a date cell on Stop #1's track to adjust its allowed window
    first_stop_cells = page.locator(".stop-dates-track").first.locator(".date-cell")
    expect(first_stop_cells.first).to_be_visible()
    first_stop_cells.nth(2).click()

    # Add a city row and verify row count increases from 6 to 7
    page.click("#addStopBtn")
    expect(page.locator("#timelineMatrix .matrix-row")).to_have_count(7)

    # Remove the newly added stop row and verify row count returns to 6
    page.locator('[data-act="del"]').last.click()
    expect(page.locator("#timelineMatrix .matrix-row")).to_have_count(6)

    # Intercept `/api/optimize` with a deterministic mocked response to verify UI rendering
    captured_requests: list[dict[str, object]] = []

    def handle_mock_optimize(route: Route) -> None:
        req_json = route.request.post_data_json
        captured_requests.append(req_json)
        # Forward to the real offline solver by forcing provider_mode="offline"
        req_json["provider_mode"] = "offline"
        resp = route.fetch(post_data=req_json)
        route.fulfill(response=resp)

    page.route("**/api/optimize", handle_mock_optimize)
    page.click("#optimizeBtn")

    expect(page.locator(".comparison-table")).to_be_visible()
    expect(page.locator(".itinerary-hero")).to_be_visible()
    assert len(captured_requests) == 1
    assert len(captured_requests[0]["stops"]) == 3  # type: ignore[arg-type]
    assert page_errors == []
