const { test: base, expect } = require("@playwright/test");

const cacheStats = {
  total_cached_flights_in_db: 12,
  cache_hits: 3,
  cache_misses: 2,
  total_serpapi_calls_logged: 7,
  serpapi_calls_this_run: 1,
};

function optimizationResponse(provider = "mock") {
  const leg = {
    origin: "SFO",
    destination: "ATH",
    departure_date: "2026-12-11",
    cabin: "business",
    provider,
    airline_name: "Test Airways",
    flight_numbers: ["TA123"],
    segments: [
      {
        origin: "SFO",
        destination: "ATH",
        departure_date: "2026-12-11",
        departure_time: "18:35",
        arrival_date: "2026-12-12",
        arrival_time: "21:00",
        airline: "TA",
        airline_name: "Test Airways",
        alliance: "Star Alliance",
        flight_number: "TA123",
        duration_hours: 12,
        cabin: "business",
      },
    ],
    duration_hours: 12,
    stops_count: 0,
    layover_airports: [],
    from_cache: true,
  };
  const recommended = {
    itinerary_id: "single-ticket",
    strategy_label: "Single Multi-City Ticket",
    strategy_description: "All flights on one protected booking.",
    badges: ["Recommended"],
    route_summary: "SFO - ATH - JTR - LHR - SFO",
    stop_visits: [{
      stop_id: "stop-ath",
      label: "Athens",
      arrival_airport: "ATH",
      departure_airport: "ATH",
      arrival_date: "2026-12-12",
      departure_date: "2026-12-15",
      nights: 3,
    }],
    legs: [leg],
    tickets: [{
      label: "Protected multi-city booking",
      airline_or_alliance: "Test Airways",
      legs: [leg],
      total_ticket_usd: 1250,
      fare_estimate: {
        amount_usd: 1200,
        provenance: "estimated",
        assumptions: ["Based on candidate-leg fares; final price is not verified."],
      },
      baggage_fees_usd: 50,
      pricing_note: "Includes checked baggage.",
      booking_query_summary: "Book SFO to ATH with Test Airways",
      google_flights_url: "https://www.google.com/travel/flights/search?tfs=test&hl=en&curr=USD",
    }],
    total_price_usd: 1250,
    total_base_fare_usd: 1200,
    total_baggage_fees_usd: 50,
    total_travel_hours: 24,
    protected_transfers: 1,
    self_transfers: 0,
    savings_vs_single_ticket_usd: 0,
    explanation_bullets: ["All connections protected."],
  };
  const alternative = {
    ...recommended,
    itinerary_id: "split-tickets",
    strategy_label: "Separate One-Way Tickets",
    strategy_description: "Book each flight separately.",
    badges: ["Cheapest"],
    total_price_usd: 1050,
    total_base_fare_usd: 1000,
    savings_vs_single_ticket_usd: 200,
    tickets: [{
      ...recommended.tickets[0],
      label: "Separate outbound booking",
      fare_estimate: {
        amount_usd: 1000,
        provenance: "estimated",
        assumptions: ["Based on candidate-leg fares; final price is not verified."],
      },
      total_ticket_usd: 1050,
    }],
  };
  return {
    api_version: 2,
    recommended,
    strategy_comparison: [recommended, alternative],
    pareto_frontier: [recommended, alternative],
    schedules_evaluated: 4,
    ticket_partitions_evaluated: 8,
    cache_stats: cacheStats,
    warnings: [],
  };
}

const test = base.extend({
  mockBackend: [async ({ page }, use) => {
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.route("**/api/**", async (route) => {
      const { pathname } = new URL(route.request().url());
      const responses = {
        "/api/airports": { all_airports: {}, metros: {} },
        "/api/provider-status": { cache_stats: cacheStats },
        "/api/optimize": optimizationResponse(),
        "/api/cache/clear": {
          total_cached_flights_in_db: 0,
          cache_hits: 0,
          cache_misses: 0,
          total_serpapi_calls_logged: 7,
        },
      };
      if (!(pathname in responses)) {
        errors.push(`Unexpected API request: ${pathname}`);
        await route.abort();
        return;
      }
      await route.fulfill({ json: responses[pathname] });
    });
    await use();
    expect(errors, "No uncaught browser errors or unmocked API requests").toEqual([]);
  }, { auto: true }],
});

test.beforeEach(async ({ page }) => {
  await page.goto("/static/index.html");
  await expect(page.locator(".stop-min-n")).toHaveCount(3);
  await page.locator("#optimizeBtn").click();
  await expect(page.locator(".itinerary-hero h2")).toHaveText("Single Multi-City Ticket");
  await expect(page.locator("#optimizeBtn")).toBeEnabled();
});

test("Optimize renders results, tickets, cache and quota", async ({ page }) => {
  await expect(page.getByRole("heading", { name: "Ticket Strategy Comparison", exact: false })).toBeVisible();
  await expect(page.locator(".comparison-table tbody tr")).toHaveCount(2);
  await expect(page.locator(".price-big")).toHaveText("$1250");
  await expect(page.locator(".price-block")).toContainText("Estimated total");
  await expect(page.locator(".ticket-card .badge-subtle").filter({ hasText: "estimated" })).toBeVisible();
  await expect(page.locator(".ticket-list")).toContainText("6:35 PM – 9:00 PM+1");
  await expect(page.locator(".ticket-list")).toContainText("Test Airways (TA123)");
  await expect(page.locator(".leg-preview-list")).toContainText("Athens (ATH)");
  await expect(page.locator("#cacheStatusText")).toHaveText("Cache: 12 flights (3 hits / 2 fetched)");
  await expect(page.locator("#serpQuotaText")).toHaveText("SerpApi: 7 / 250 (+1 run)");
  await expect(page.locator(".booking-query-link").first()).toHaveAttribute(
    "href",
    "https://www.google.com/travel/flights/search?tfs=test&hl=en&curr=USD"
  );
  await expect(page.locator(".btn-gf-book").first()).toHaveAttribute(
    "href",
    "https://www.google.com/travel/flights/search?tfs=test&hl=en&curr=USD"
  );
  await expect(page.getByText("Optimization Error", { exact: true })).toHaveCount(0);
});

for (const transport of ["json", "ndjson"]) {
  test(`an outdated server response (${transport}) explains how to recover`, async ({ page }) => {
    const legacyResponse = optimizationResponse();
    delete legacyResponse.api_version;
    for (const itinerary of new Set([
      legacyResponse.recommended,
      ...legacyResponse.strategy_comparison,
      ...legacyResponse.pareto_frontier,
    ])) {
      for (const ticket of itinerary.tickets) {
        ticket.base_fare_usd = ticket.fare_estimate.amount_usd;
        delete ticket.fare_estimate;
      }
    }
    await page.route("**/api/optimize", (route) => route.fulfill({
      contentType: transport === "json" ? "application/json" : "application/x-ndjson",
      body: transport === "json"
        ? JSON.stringify(legacyResponse)
        : JSON.stringify({ type: "result", data: legacyResponse }) + "\n",
    }));

    await page.locator("#optimizeBtn").click();
    await expect(page.locator("#resultsContainer")).toContainText(
      "Restart the FareSplit server and reload this page."
    );
    await expect(page.locator("#resultsContainer")).not.toContainText("Cannot read properties");
    await expect(page.locator(".ticket-card")).toHaveCount(0);
    await expect(page.locator("#optimizeBtn")).toBeEnabled();

    await page.unroute("**/api/optimize");
    await page.locator("#optimizeBtn").click();
    await expect(page.locator(".ticket-card")).toHaveCount(1);
    await expect(page.getByText("Optimization Error", { exact: true })).toHaveCount(0);
  });
}

test("Optimize submits edited inputs, shows loading and clears stale results", async ({ page }) => {
  await page.locator("#providerModeSelect").selectOption("fast_flights");
  await page.locator("#checkedBagsCountSelect").selectOption("2");
  await page.locator("#includeCarryOnCheck").uncheck();
  await page.locator("#shortHaulStopsSelect").selectOption("nonstop");
  await page.locator("#longHaulStopsSelect").selectOption("one_stop");
  await page.locator("#toggleWeightsBtn").click();
  await page.locator("#maxLayoverHoursInput").fill("4.5");
  await page.locator("#maxLayoverHoursInput").press("Tab");
  await page.locator(".connector-stops-pills").nth(1).getByRole("button", { name: "Nonstop" }).click();
  await page.locator("#forceRefreshCheck").check();
  await expect(page.locator("#staleNoticeBadge")).toBeVisible();
  await expect(page.locator("#resultsContainer")).toHaveClass(/results-stale/);

  let releaseResponse;
  const responseGate = new Promise((resolve) => { releaseResponse = resolve; });
  await page.route("**/api/optimize", async (route) => {
    await responseGate;
    const ndjsonLines = [
      JSON.stringify({
        type: "progress",
        phase: "query_done",
        current_query: "SFO → ATH (2026-12-11 · Business)",
        queries_completed: 3,
        queries_total: 8,
        schedule_index: 1,
        schedules_total: 4,
        schedule_route: "SFO → ATH → JTR → LHR → SFO",
        strategy_label: "Anchor Open-Jaw + Regional Hops",
        cache_hits: 2,
        live_calls: 1,
        progress_pct: 42,
        last_query: {
          query: "SFO → ATH (2026-12-11 · Business)",
          route: "SFO → ATH",
          date: "2026-12-11",
          cabin: "Business",
          options_count: 5,
          source: "live",
        },
      }),
      JSON.stringify({
        type: "result",
        data: optimizationResponse(),
      }),
    ].join("\n") + "\n";
    await route.fulfill({
      status: 200,
      contentType: "application/x-ndjson",
      body: ndjsonLines,
    });
  });
  const requestPromise = page.waitForRequest("**/api/optimize");
  await page.locator("#optimizeBtn").click();
  const request = await requestPromise;
  try {
    expect(request.method()).toBe("POST");
    expect(request.postDataJSON()).toMatchObject({
      origin_airports: ["SFO"],
      destination_airports: ["SFO"],
      provider_mode: "fast_flights",
      force_refresh: true,
      baggage: { include_carry_on: false, checked_bags: 2 },
      stops_policy: {
        short_haul_stops: "nonstop",
        long_haul_stops: "one_stop",
        nonstop_threshold_hours: 4.5,
        max_layover_hours: 4.5,
      },
      stops: expect.arrayContaining([
        expect.objectContaining({ id: "stop-ath", airports: ["ATH"], outbound_stops: "auto" }),
        expect.objectContaining({ id: "stop-jtr", airports: ["JTR"], outbound_stops: "nonstop" }),
      ]),
    });
    await expect(page.locator("#optimizeBtn")).toBeDisabled();
    await expect(page.locator("#optimizeBtn")).toContainText("Optimizing");
    await expect(page.locator("#optimizeProgress")).toBeVisible();
    await expect(page.locator("#optimizeProgressBar")).toBeVisible();
    await expect(page.locator("#optimizeProgressCounts")).toContainText("queries");
    await expect(page.locator("#optimizeCurrentQuery")).toContainText("SFO → ATH");
  } finally {
    releaseResponse();
  }
  await expect(page.locator("#optimizeBtn")).toBeEnabled();
  await expect(page.locator("#optimizeProgress")).toBeHidden();
  await expect(page.locator("#staleNoticeBadge")).toBeHidden();
  await expect(page.locator("#resultsContainer")).not.toHaveClass(/results-stale/);
  await expect(page.locator(".itinerary-hero h2")).toHaveText("Single Multi-City Ticket");
});

test("selecting a strategy updates the price and ticket breakdown", async ({ page }) => {
  await page.getByRole("row").filter({ hasText: "Separate One-Way Tickets" }).click();
  await expect(page.locator(".itinerary-hero h2")).toHaveText("Separate One-Way Tickets");
  await expect(page.locator(".price-big")).toHaveText("$1050");
  await expect(page.locator(".ticket-list")).toContainText("Separate outbound booking");
  await expect(page.locator("tr.active-row")).toContainText("Separate One-Way Tickets");
});

test("booking link falls back to Google Flights query URL when google_flights_url is absent", async ({ page }) => {
  const fallbackResp = optimizationResponse();
  delete fallbackResp.recommended.tickets[0].google_flights_url;
  delete fallbackResp.alternative?.tickets?.[0]?.google_flights_url;
  fallbackResp.strategy_comparison[1].tickets[0] = {
    ...fallbackResp.strategy_comparison[1].tickets[0],
    google_flights_url: "",
    cabin_summary: "Business",
    legs: [
      { ...fallbackResp.recommended.legs[0], origin: "sfo", destination: "ath" },
      { ...fallbackResp.recommended.legs[0], origin: "lhr", destination: "sfo", departure_date: "2026-12-25" },
    ],
  };
  await page.route("**/api/optimize", (route) => route.fulfill({ json: fallbackResp }));
  await page.locator("#optimizeBtn").click();
  await expect(page.locator(".booking-query-link").first()).toHaveAttribute(
    "href",
    /https:\/\/www\.google\.com\/travel\/flights\?q=Flights%20from%20SFO%20to%20ATH%20on%202026-12-11%20one%20way%20Business/
  );
  await expect(page.locator(".btn-gf-book").first()).toHaveAttribute("target", "_blank");
  await expect(page.locator(".btn-gf-book").first()).toHaveAttribute("rel", "noopener noreferrer");

  await page.getByRole("row").filter({ hasText: "Separate One-Way Tickets" }).click();
  await expect(page.locator(".booking-query-link").first()).toHaveAttribute(
    "href",
    /https:\/\/www\.google\.com\/travel\/flights\?q=Multi-city%20flights%20SFO%20to%20ATH%20on%202026-12-11%2C%20LHR%20to%20SFO%20on%202026-12-25%20Business/
  );
});

for (const failure of ["http", "network"]) {
  test(`${failure} failure displays an error and allows retry`, async ({ page }) => {
    await page.route("**/api/optimize", async (route) => {
      if (failure === "network") {
        await route.abort("failed");
      } else {
        await route.fulfill({ status: 503, json: { detail: "Flight provider unavailable" } });
      }
    }, { times: 1 });
    await page.locator("#optimizeBtn").click();
    await expect(page.getByRole("heading", { name: "Optimization Error" })).toBeVisible();
    if (failure === "http") {
      await expect(page.locator("#resultsContainer")).toContainText("Flight provider unavailable");
    }
    await expect(page.locator("#optimizeBtn")).toBeEnabled();
    await page.locator("#optimizeBtn").click();
    await expect(page.locator(".itinerary-hero h2")).toHaveText("Single Multi-City Ticket");
    await expect(page.getByRole("heading", { name: "Optimization Error" })).toHaveCount(0);
  });
}

test("trip presets, row editing, persistence and reset work", async ({ page }) => {
  await page.locator("#presetSelect").selectOption("asia_circuit");
  await expect(page.locator("#timelineMatrix")).toContainText("Tokyo");
  await expect(page.locator("#earliestDepartureInput")).toHaveValue("2026-11-12");
  await page.getByRole("button", { name: "Add City Row", exact: false }).click();
  await expect(page.getByTitle("Remove stop", { exact: true })).toHaveCount(4);
  await page.getByTitle("Remove stop", { exact: true }).last().click();
  await expect(page.getByTitle("Remove stop", { exact: true })).toHaveCount(3);
  await page.locator(".stop-min-n").first().fill("5");
  await page.locator(".stop-min-n").first().press("Tab");
  await page.locator("#checkedBagsCountSelect").selectOption("2");

  await page.reload();
  await expect(page.locator("#timelineMatrix")).toContainText("Tokyo");
  await expect(page.locator(".stop-min-n").first()).toHaveValue("5");
  await expect(page.locator("#checkedBagsCountSelect")).toHaveValue("2");
  await expect(page.locator("#optimizeBtn")).toBeEnabled();
  await page.getByRole("button", { name: "Reset Form" }).click();
  await expect(page.locator("#timelineMatrix")).toContainText("Athens");
  await expect(page.locator("#earliestDepartureInput")).toHaveValue("2026-12-11");
  await expect(page.locator("#checkedBagsCountSelect")).toHaveValue("1");
});

test("clearing the cache updates its status without losing results", async ({ page }) => {
  const requestPromise = page.waitForRequest("**/api/cache/clear");
  await page.getByRole("button", { name: "Clear", exact: true }).click();
  expect((await requestPromise).method()).toBe("POST");
  await expect(page.locator("#cacheStatusText")).toHaveText("Cache: 0 flights (0 hits / 0 fetched)");
  await expect(page.locator("#serpQuotaText")).toHaveText("SerpApi: 7 / 250");
  await expect(page.locator(".itinerary-hero h2")).toHaveText("Single Multi-City Ticket");
});

test("simulation controls are unavailable outside testing", async ({ page }) => {
  await expect(page.locator("#simulationControl")).toBeHidden();
  await expect(page.locator('#providerModeSelect option[value="offline"]')).toHaveCount(0);
});

test("saved simulation settings cannot re-enable simulation outside testing", async ({ page }) => {
  await page.locator("#providerModeSelect").selectOption("fast_flights");
  await page.evaluate(() => {
    const saved = JSON.parse(localStorage.getItem("faresplit_trip_state_v1"));
    saved.provider_mode = "offline";
    localStorage.setItem("faresplit_trip_state_v1", JSON.stringify(saved));
  });
  await page.context().clearCookies();
  await page.reload();
  await expect(page.locator("#providerModeSelect")).toHaveValue("auto");
  await expect(page.locator("#simulationToggle")).not.toBeChecked();
  const requestPromise = page.waitForRequest("**/api/optimize");
  await page.locator("#optimizeBtn").click();
  expect((await requestPromise).postDataJSON().provider_mode).toBe("auto");
  await expect(page.locator(".itinerary-hero")).toBeVisible();
});

test("testing-only toggle switches between simulation and live requests", async ({ page }) => {
  await page.route("**/api/provider-status", (route) => route.fulfill({
    json: { testing_mode: true, cache_stats: cacheStats },
  }));
  await page.route("**/api/optimize", (route) => route.fulfill({
    json: optimizationResponse(route.request().postDataJSON().provider_mode === "offline" ? "pricing_engine" : "fast_flights"),
  }));
  await page.reload();
  await expect(page.locator("#simulationControl")).toBeVisible();
  await page.locator("#simulationToggle").check();
  await expect(page.locator("#providerModeSelect")).toBeDisabled();
  let requestPromise = page.waitForRequest("**/api/optimize");
  await page.locator("#optimizeBtn").click();
  expect((await requestPromise).postDataJSON().provider_mode).toBe("offline");
  await expect(page.locator(".ticket-list")).toContainText("Simulated estimate");

  await page.locator("#simulationToggle").uncheck();
  await expect(page.locator("#providerModeSelect")).toBeEnabled();
  requestPromise = page.waitForRequest("**/api/optimize");
  await page.locator("#optimizeBtn").click();
  expect((await requestPromise).postDataJSON().provider_mode).toBe("auto");
  await expect(page.locator(".ticket-list")).toContainText("fast_flights");
  await expect(page.locator(".ticket-list")).not.toContainText("Simulated estimate");
});