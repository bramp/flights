const { test: base, expect } = require("@playwright/test");

const cacheStats = {
  total_cached_flights_in_db: 12,
  total_cached_quotes_in_db: 2,
  cache_hits: 3,
  cache_misses: 2,
  total_serpapi_calls_logged: 7,
  serpapi_calls_this_run: 1,
};

function optimizationResponse() {
  const leg = {
    origin: "SFO",
    destination: "ATH",
    departure_date: "2026-12-11",
    cabin: "business",
    provider: "mock",
    airline_name: "Test Airways",
    flight_numbers: ["TA123"],
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
      base_fare_usd: 1200,
      baggage_fees_usd: 50,
      pricing_note: "Includes checked baggage.",
      booking_query_summary: "Book SFO to ATH with Test Airways",
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
      base_fare_usd: 1000,
      total_ticket_usd: 1050,
    }],
  };
  return {
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
  await expect(page.locator(".ticket-list")).toContainText("Test Airways (TA123)");
  await expect(page.locator(".leg-preview-list")).toContainText("Athens (ATH)");
  await expect(page.locator("#cacheStatusText")).toHaveText("Cache: 12 flights (3 hits / 2 fetched)");
  await expect(page.locator("#serpQuotaText")).toHaveText("SerpApi: 7 / 250 (+1 run)");
  await expect(page.getByText("Optimization Error", { exact: true })).toHaveCount(0);
});

test("Optimize submits edited inputs, shows loading and clears stale results", async ({ page }) => {
  await page.locator("#providerModeSelect").selectOption("offline");
  await page.locator("#checkedBagsCountSelect").selectOption("2");
  await page.locator("#includeCarryOnCheck").uncheck();
  await page.locator("#forceRefreshCheck").check();
  await expect(page.locator("#staleNoticeBadge")).toBeVisible();
  await expect(page.locator("#resultsContainer")).toHaveClass(/results-stale/);

  let releaseResponse;
  const responseGate = new Promise((resolve) => { releaseResponse = resolve; });
  await page.route("**/api/optimize", async (route) => {
    await responseGate;
    await route.fulfill({ json: optimizationResponse() });
  });
  const requestPromise = page.waitForRequest("**/api/optimize");
  await page.locator("#optimizeBtn").click();
  const request = await requestPromise;
  try {
    expect(request.method()).toBe("POST");
    expect(request.postDataJSON()).toMatchObject({
      origin_airports: ["SFO"],
      destination_airports: ["SFO"],
      provider_mode: "offline",
      force_refresh: true,
      baggage: { include_carry_on: false, checked_bags: 2 },
      stops: expect.arrayContaining([expect.objectContaining({ id: "stop-ath", airports: ["ATH"] })]),
    });
    await expect(page.locator("#optimizeBtn")).toBeDisabled();
    await expect(page.locator("#optimizeBtn")).toContainText("Optimizing");
  } finally {
    releaseResponse();
  }
  await expect(page.locator("#optimizeBtn")).toBeEnabled();
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