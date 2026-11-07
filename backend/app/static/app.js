/**
 * FareSplit — Interactive Multi-City Flight & Ticket Builder UI
 * Features:
 *  - Client-side cookie + localStorage state persistence
 *  - City/airport search with clickable nearby/metro airport chips
 *  - Flexible date windows + min/max stay nights per stop
 *  - Per-leg cabin class selector + smart duration-based "Auto" cabin rule
 *  - Trip-wide baggage checkbox & optimization trade-off sliders
 */

const COOKIE_NAME = "faresplit_trip_state_v1";
const STORAGE_KEY = "faresplit_trip_state_v1";

const DEFAULT_STOPS_POLICY = {
  short_haul_stops: "nonstop",
  long_haul_stops: "one_stop",
  nonstop_threshold_hours: 4.5,
  max_layover_hours: 6.0,
};

const PRESETS = {
  greece_london: {
    origin_label: "San Francisco",
    origin_airports: ["SFO"],
    destination_label: "San Francisco",
    destination_airports: ["SFO"],
    same_as_origin: true,
    earliest_departure: "2026-12-11",
    latest_departure: "2026-12-12",
    earliest_return: "2026-12-24",
    latest_return: "2026-12-26",
    return_leg_cabin: "auto",
    return_leg_stops: "auto",
    ordering_mode: "flexible",
    stops: [
      {
        id: "stop-ath",
        label: "Athens",
        airports: ["ATH"],
        earliest_arrival: "2026-12-11",
        latest_departure: "2026-12-19",
        min_nights: 3,
        max_nights: 4,
        fixed_order: false,
        outbound_cabin: "auto",
        outbound_stops: "auto",
      },
      {
        id: "stop-jtr",
        label: "Santorini",
        airports: ["JTR"],
        earliest_arrival: "2026-12-11",
        latest_departure: "2026-12-19",
        min_nights: 3,
        max_nights: 4,
        fixed_order: false,
        outbound_cabin: "auto",
        outbound_stops: "auto",
      },
      {
        id: "stop-lon-dec",
        label: "London",
        airports: ["LHR", "LGW"],
        earliest_arrival: "2026-12-17",
        latest_departure: "2026-12-26",
        min_nights: 6,
        max_nights: 7,
        fixed_order: true,
        outbound_cabin: "economy",
        outbound_stops: "auto",
      },
    ],
    baggage: {
      include_carry_on: true,
      checked_bags: 1,
    },
    cabin_policy: {
      default_cabin: "economy",
      long_haul_cabin: "business",
      long_haul_threshold_hours: 6.5,
    },
    stops_policy: { ...DEFAULT_STOPS_POLICY },
    weights: {
      value_of_time_per_hour: 35,
      protected_transfer_penalty: 45,
      self_transfer_penalty: 140,
      separate_ticket_penalty: 20,
      enable_hub_splitting: true,
    },
  },
  europe_loop: {
    origin_label: "San Francisco",
    origin_airports: ["SFO", "OAK", "SJC"],
    destination_label: "San Francisco",
    destination_airports: ["SFO", "OAK", "SJC"],
    same_as_origin: true,
    earliest_departure: "2026-11-10",
    latest_departure: "2026-11-13",
    earliest_return: "2026-11-22",
    latest_return: "2026-11-25",
    return_leg_cabin: "auto",
    return_leg_stops: "auto",
    ordering_mode: "flexible",
    stops: [
      {
        id: "stop-lon",
        label: "London",
        airports: ["LHR", "LGW"],
        earliest_arrival: "2026-11-10",
        latest_departure: "2026-11-17",
        min_nights: 3,
        max_nights: 5,
        fixed_order: true,
        outbound_cabin: "auto",
        outbound_stops: "auto",
      },
      {
        id: "stop-par",
        label: "Paris",
        airports: ["CDG", "ORY"],
        earliest_arrival: "2026-11-13",
        latest_departure: "2026-11-21",
        min_nights: 3,
        max_nights: 4,
        fixed_order: false,
        outbound_cabin: "economy",
        outbound_stops: "auto",
      },
      {
        id: "stop-rom",
        label: "Rome",
        airports: ["FCO", "CIA"],
        earliest_arrival: "2026-11-16",
        latest_departure: "2026-11-25",
        min_nights: 3,
        max_nights: 5,
        fixed_order: false,
        outbound_cabin: "economy",
        outbound_stops: "auto",
      },
    ],
    baggage: {
      include_carry_on: true,
      checked_bags: 1,
    },
    cabin_policy: {
      default_cabin: "economy",
      long_haul_cabin: "business",
      long_haul_threshold_hours: 6.5,
    },
    stops_policy: { ...DEFAULT_STOPS_POLICY },
    weights: {
      value_of_time_per_hour: 35,
      protected_transfer_penalty: 45,
      self_transfer_penalty: 140,
      separate_ticket_penalty: 20,
      enable_hub_splitting: true,
    },
  },
  asia_circuit: {
    origin_label: "San Francisco",
    origin_airports: ["SFO", "SJC"],
    destination_label: "San Francisco",
    destination_airports: ["SFO", "SJC"],
    same_as_origin: true,
    earliest_departure: "2026-11-12",
    latest_departure: "2026-11-15",
    earliest_return: "2026-11-28",
    latest_return: "2026-12-01",
    return_leg_cabin: "business",
    return_leg_stops: "auto",
    ordering_mode: "flexible",
    stops: [
      {
        id: "stop-tyo",
        label: "Tokyo",
        airports: ["HND", "NRT"],
        earliest_arrival: "2026-11-12",
        latest_departure: "2026-11-22",
        min_nights: 4,
        max_nights: 6,
        fixed_order: false,
        outbound_cabin: "business",
        outbound_stops: "auto",
      },
      {
        id: "stop-tpe",
        label: "Taipei",
        airports: ["TPE", "TSA"],
        earliest_arrival: "2026-11-16",
        latest_departure: "2026-11-26",
        min_nights: 3,
        max_nights: 5,
        fixed_order: false,
        outbound_cabin: "economy",
        outbound_stops: "auto",
      },
      {
        id: "stop-bkk",
        label: "Bangkok",
        airports: ["BKK", "DMK"],
        earliest_arrival: "2026-11-20",
        latest_departure: "2026-12-01",
        min_nights: 4,
        max_nights: 6,
        fixed_order: false,
        outbound_cabin: "economy",
        outbound_stops: "auto",
      },
    ],
    baggage: {
      include_carry_on: true,
      checked_bags: 1,
    },
    cabin_policy: {
      default_cabin: "economy",
      long_haul_cabin: "business",
      long_haul_threshold_hours: 6.5,
    },
    stops_policy: { ...DEFAULT_STOPS_POLICY },
    weights: {
      value_of_time_per_hour: 40,
      protected_transfer_penalty: 50,
      self_transfer_penalty: 150,
      separate_ticket_penalty: 20,
      enable_hub_splitting: true,
    },
  },
  global_hub: {
    origin_label: "New York",
    origin_airports: ["JFK", "EWR"],
    destination_label: "New York",
    destination_airports: ["JFK", "EWR"],
    same_as_origin: true,
    earliest_departure: "2026-11-15",
    latest_departure: "2026-11-18",
    earliest_return: "2026-11-30",
    latest_return: "2026-12-03",
    return_leg_cabin: "auto",
    return_leg_stops: "auto",
    ordering_mode: "flexible",
    stops: [
      {
        id: "stop-lon2",
        label: "London",
        airports: ["LHR", "LGW"],
        earliest_arrival: "2026-11-15",
        latest_departure: "2026-11-22",
        min_nights: 3,
        max_nights: 5,
        fixed_order: true,
        outbound_cabin: "auto",
        outbound_stops: "auto",
      },
      {
        id: "stop-ist",
        label: "Istanbul",
        airports: ["IST", "SAW"],
        earliest_arrival: "2026-11-18",
        latest_departure: "2026-11-27",
        min_nights: 3,
        max_nights: 5,
        fixed_order: false,
        outbound_cabin: "economy",
        outbound_stops: "auto",
      },
      {
        id: "stop-sin",
        label: "Singapore",
        airports: ["SIN"],
        earliest_arrival: "2026-11-22",
        latest_departure: "2026-12-03",
        min_nights: 4,
        max_nights: 6,
        fixed_order: false,
        outbound_cabin: "business",
        outbound_stops: "auto",
      },
    ],
    baggage: {
      include_carry_on: true,
      checked_bags: 0,
    },
    cabin_policy: {
      default_cabin: "economy",
      long_haul_cabin: "business",
      long_haul_threshold_hours: 7.0,
    },
    stops_policy: { ...DEFAULT_STOPS_POLICY },
    weights: {
      value_of_time_per_hour: 45,
      protected_transfer_penalty: 50,
      self_transfer_penalty: 140,
      separate_ticket_penalty: 20,
      enable_hub_splitting: true,
    },
  },
};

let airportCatalog = {};
let state = loadPersistedState() || structuredClone(PRESETS.greece_london);
let currentOptimizationResponse = null;
let selectedItineraryId = null;
let resultsStale = false;
let testingMode = false;

function escapeHtml(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function setResultsStale(isStale) {
  resultsStale = isStale;
  const notice = document.getElementById("staleNoticeBadge");
  const optBtn = document.getElementById("optimizeBtn");
  const resContainer = document.getElementById("resultsContainer");

  if (notice) {
    notice.classList.toggle("hidden", !isStale || !currentOptimizationResponse);
  }
  if (optBtn && !optBtn.disabled) {
    optBtn.classList.toggle("stale-pulse", Boolean(isStale && currentOptimizationResponse));
    optBtn.textContent =
      isStale && currentOptimizationResponse
        ? "🔄 Re-Optimize Trip (Inputs Changed)"
        : "🔍 Optimize Flights & Ticket Combinations";
  }
  if (resContainer) {
    resContainer.classList.toggle("results-stale", Boolean(isStale && currentOptimizationResponse));
  }
}

function clampDatesToTripWindow() {
  if (!state.stops_policy) {
    state.stops_policy = { ...DEFAULT_STOPS_POLICY };
  } else if (typeof state.stops_policy.max_layover_hours !== "number") {
    state.stops_policy.max_layover_hours = DEFAULT_STOPS_POLICY.max_layover_hours;
  }
  if (!state.return_leg_stops) {
    state.return_leg_stops = "auto";
  }
  state.stops.forEach((s) => {
    if (!s.outbound_stops) s.outbound_stops = "auto";
  });

  const minIso = state.earliest_departure;
  const maxIso = state.latest_return;
  if (!minIso || !maxIso || maxIso <= minIso) return;

  if (!state.latest_departure || state.latest_departure < minIso) {
    state.latest_departure = minIso;
  } else if (state.latest_departure > maxIso) {
    state.latest_departure = maxIso;
  }

  if (!state.earliest_return || state.earliest_return > maxIso) {
    state.earliest_return = maxIso;
  } else if (state.earliest_return < minIso) {
    state.earliest_return = minIso;
  }

  state.stops.forEach((stop) => {
    if (!stop.earliest_arrival || stop.earliest_arrival < minIso || stop.earliest_arrival > maxIso) {
      stop.earliest_arrival = minIso;
    }
    if (!stop.latest_departure || stop.latest_departure > maxIso || stop.latest_departure < stop.earliest_arrival) {
      stop.latest_departure = maxIso;
    }
  });
}

/* --- Cookie & LocalStorage Persistence --- */
function saveStateToCookieAndStorage() {
  try {
    const serialized = JSON.stringify(state);
    localStorage.setItem(STORAGE_KEY, serialized);
    const encoded = encodeURIComponent(serialized);
    document.cookie = `${COOKIE_NAME}=${encoded}; path=/; max-age=${60 * 60 * 24 * 60}; SameSite=Lax`;
    const ind = document.getElementById("cookieIndicator");
    if (ind) {
      ind.textContent = "🍪 Saved to Cookie";
    }
  } catch (err) {
    console.warn("Could not persist state:", err);
  }
}

function loadPersistedState() {
  try {
    const cookies = document.cookie.split(";").map((c) => c.trim());
    const match = cookies.find((c) => c.startsWith(`${COOKIE_NAME}=`));
    if (match) {
      const raw = decodeURIComponent(match.substring(COOKIE_NAME.length + 1));
      return JSON.parse(raw);
    }
    const fromStorage = localStorage.getItem(STORAGE_KEY);
    if (fromStorage) {
      return JSON.parse(fromStorage);
    }
  } catch (err) {
    console.warn("Failed to parse saved state, using default preset:", err);
  }
  return null;
}

/* --- Airport Metadata & Google Flights-Style Location Picker --- */
let metroCatalog = {};
let gfPortalEl = null;
let activeLocatorSession = null;

async function loadAirportsCatalog() {
  try {
    const resp = await fetch("/api/airports");
    const data = await resp.json();
    airportCatalog = data.all_airports || {};
    metroCatalog = data.metros || {};
  } catch (e) {
    console.warn("Could not load airport catalog:", e);
  }
}

function haversineMiles(lat1, lon1, lat2, lon2) {
  const toRad = (deg) => (deg * Math.PI) / 180;
  const rMiles = 3958.8;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return Math.round(2 * rMiles * Math.asin(Math.min(1, Math.sqrt(a))));
}

function estimateHoursBetween(codeA, codeB) {
  const a = airportCatalog[codeA];
  const b = airportCatalog[codeB];
  if (!a || !b || codeA === codeB) return 3.5;
  if (typeof a.lat === "number" && typeof b.lat === "number") {
    const miles = haversineMiles(a.lat, a.lon, b.lat, b.lon);
    return Math.max(0.8, miles / 515 + 0.65);
  }
  if (a.metro_code === b.metro_code) return 0.5;
  if (a.region === b.region) return 2.8;
  return 9.5;
}

function resolvePreviewCabin(fromCode, toCode, requestedCabin) {
  if (requestedCabin && requestedCabin !== "auto") {
    return { cabin: requestedCabin, autoReason: "Explicit override" };
  }
  const estHrs = estimateHoursBetween(fromCode, toCode);
  const threshold = Number(state.cabin_policy.long_haul_threshold_hours || 6.5);
  if (estHrs >= threshold) {
    return {
      cabin: state.cabin_policy.long_haul_cabin,
      autoReason: `Auto (~${estHrs.toFixed(1)}h ≥ ${threshold}h → Long-Haul)`,
    };
  }
  return {
    cabin: state.cabin_policy.default_cabin,
    autoReason: `Auto (~${estHrs.toFixed(1)}h < ${threshold}h → Short-Haul)`,
  };
}

function formatCabinName(cabin) {
  const map = {
    auto: "Auto",
    economy: "Economy",
    premium_economy: "Premium Econ",
    business: "Business",
    first: "First",
  };
  return map[cabin] || cabin;
}

function formatStopsName(stops) {
  const map = {
    auto: "Auto",
    nonstop: "Nonstop",
    one_stop: "≤1 Stop",
    any: "Any",
  };
  return map[stops] || stops;
}

function resolvePreviewStops(fromCode, toCode, requestedStops) {
  const policy = state.stops_policy || DEFAULT_STOPS_POLICY;
  if (requestedStops && requestedStops !== "auto") {
    return { stops: requestedStops, autoReason: "Explicit override" };
  }
  const estHrs = estimateHoursBetween(fromCode, toCode);
  const threshold = Number(policy.nonstop_threshold_hours || 4.5);
  if (estHrs < threshold) {
    return {
      stops: policy.short_haul_stops || "nonstop",
      autoReason: `Auto (~${estHrs.toFixed(1)}h < ${threshold}h → ${formatStopsName(policy.short_haul_stops || "nonstop")})`,
    };
  }
  return {
    stops: policy.long_haul_stops || "one_stop",
    autoReason: `Auto (~${estHrs.toFixed(1)}h ≥ ${threshold}h → ${formatStopsName(policy.long_haul_stops || "one_stop")})`,
  };
}

/**
 * Group all catalog airports into expandable City/Metro groups (like Google Flights):
 * Each group contains:
 *  - metroCode, cityName, countryName, subtitle
 *  - metroAirports: airports belonging to that city/metro
 *  - nearbyAirports: nearby regional airports (e.g., Greek islands/Thessaloniki for Athens, Naples/Florence for Rome)
 */
function buildAllCityGroups() {
  const byMetro = new Map();

  Object.values(airportCatalog).forEach((info) => {
    const mCode = info.metro_code || info.code;
    if (!byMetro.has(mCode)) {
      byMetro.set(mCode, {
        metroCode: mCode,
        cityName: info.city.split("/")[0].trim(),
        countryName: info.country_name || info.country,
        subtitle: `City in ${info.country_name || info.country}`,
        primaryCode: info.code,
        metroAirports: [],
        nearbyAirports: [],
      });
    }
    const grp = byMetro.get(mCode);
    grp.metroAirports.push(info);
    if (info.is_major_hub && grp.metroAirports.length === 1) {
      grp.primaryCode = info.code;
    }
  });

  // Enrich with METRO_GROUPS ordering & subtitles
  Object.entries(metroCatalog).forEach(([label, meta]) => {
    const primary = airportCatalog[meta.primary];
    if (!primary) return;
    const grp = byMetro.get(primary.metro_code);
    if (!grp) return;
    grp.cityName = label.split("/")[0].trim();
    grp.primaryCode = meta.primary;
    if (meta.subtitle) grp.subtitle = meta.subtitle;
    if (Array.isArray(meta.codes)) {
      const orderMap = new Map(meta.codes.map((c, idx) => [c, idx]));
      grp.metroAirports.sort(
        (a, b) => (orderMap.get(a.code) ?? 99) - (orderMap.get(b.code) ?? 99)
      );
    }
  });

  // Populate nearby regional airports (outside the same metro_code) with distance in miles
  byMetro.forEach((grp) => {
    const anchor = airportCatalog[grp.primaryCode] || grp.metroAirports[0];
    if (!anchor) return;
    const metroSet = new Set(grp.metroAirports.map((a) => a.code));
    const nearbySet = new Set();

    grp.metroAirports.forEach((a) => {
      (a.nearby || []).forEach((nbCode) => {
        if (!metroSet.has(nbCode) && airportCatalog[nbCode]) {
          nearbySet.add(nbCode);
        }
      });
    });

    // Also include any airport within 220 miles if the city only has 1 metro airport (like Athens, Nice, Zurich, etc.)
    if (grp.metroAirports.length <= 2 && typeof anchor.lat === "number") {
      Object.values(airportCatalog).forEach((cand) => {
        if (metroSet.has(cand.code)) return;
        const distMi = haversineMiles(anchor.lat, anchor.lon, cand.lat, cand.lon);
        if (distMi <= 220) {
          nearbySet.add(cand.code);
        }
      });
    }

    grp.nearbyAirports = Array.from(nearbySet)
      .map((code) => {
        const info = airportCatalog[code];
        const distMi =
          typeof anchor.lat === "number" && typeof info.lat === "number"
            ? haversineMiles(anchor.lat, anchor.lon, info.lat, info.lon)
            : 45;
        return { ...info, distanceFromAnchorMi: distMi };
      })
      .sort((a, b) => a.distanceFromAnchorMi - b.distanceFromAnchorMi);
  });

  return Array.from(byMetro.values());
}

function ensureGfPortalElement() {
  if (gfPortalEl) return gfPortalEl;
  gfPortalEl = document.createElement("div");
  gfPortalEl.id = "gfLocationPortal";
  gfPortalEl.className = "gf-picker-portal hidden";
  gfPortalEl.innerHTML = `
    <div class="gf-picker-top">
      <span class="gf-picker-icon">◎</span>
      <div class="gf-chip-slot"></div>
      <input type="text" class="gf-picker-input" placeholder="City, country, or airport (e.g. Athens, London)…" autocomplete="off" />
      <button type="button" class="gf-confirm-btn" title="Confirm selection">✓</button>
    </div>
    <div class="gf-picker-body"></div>
    <div class="gf-picker-footer">
      <span class="gf-footer-summary">Tick city or individual airports</span>
      <button type="button" class="gf-custom-code-btn">+ Custom IATA Code</button>
    </div>
  `;
  document.body.appendChild(gfPortalEl);

  gfPortalEl.addEventListener("click", (e) => e.stopPropagation());

  const inputEl = gfPortalEl.querySelector(".gf-picker-input");
  inputEl.addEventListener("input", () => {
    if (activeLocatorSession) {
      renderGfPortalBody();
    }
  });
  inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Escape" || e.key === "Enter") {
      e.preventDefault();
      closeGfLocationPortal();
    }
  });

  gfPortalEl.querySelector(".gf-confirm-btn").addEventListener("click", () => {
    closeGfLocationPortal();
  });

  gfPortalEl.querySelector(".gf-custom-code-btn").addEventListener("click", () => {
    if (!activeLocatorSession) return;
    const raw = prompt("Enter 3-letter IATA airport code (e.g. ATH, JTR, LGW, SEN):");
    if (raw && raw.trim().length === 3) {
      const code = raw.trim().toUpperCase();
      const loc = activeLocatorSession.getLocation();
      const nextCodes = loc.airports.includes(code) ? loc.airports : [...loc.airports, code];
      const known = airportCatalog[code];
      const nextLabel = known && loc.airports.length === 0 ? known.city : loc.label;
      activeLocatorSession.setLocation(nextLabel, nextCodes);
      renderGfPortalChipAndBody();
    }
  });

  return gfPortalEl;
}

function closeGfLocationPortal() {
  if (!gfPortalEl || gfPortalEl.classList.contains("hidden")) return;
  gfPortalEl.classList.add("hidden");
  activeLocatorSession = null;
  onStateMutated();
}

function positionGfPortal(anchorEl) {
  const portal = ensureGfPortalElement();
  const rect = anchorEl.getBoundingClientRect();
  const viewportH = window.innerHeight;
  const viewportW = window.innerWidth;
  const portalW = Math.min(420, viewportW - 24);
  const maxH = 440;

  let left = Math.max(12, Math.min(rect.left, viewportW - portalW - 12));
  let top = rect.bottom + 6;
  if (top + maxH > viewportH - 12 && rect.top > maxH) {
    top = Math.max(12, rect.top - maxH - 6);
  }
  portal.style.left = `${left}px`;
  portal.style.top = `${top}px`;
}

function renderGfPortalChipAndBody() {
  if (!activeLocatorSession || !gfPortalEl) return;
  const loc = activeLocatorSession.getLocation();
  const chipSlot = gfPortalEl.querySelector(".gf-chip-slot");
  const footerSummary = gfPortalEl.querySelector(".gf-footer-summary");

  if (loc.label) {
    chipSlot.innerHTML = `
      <span class="gf-active-chip">
        <span>${escapeHtml(loc.label)}</span>
        <button type="button" title="Clear and search another city">×</button>
      </span>
    `;
    chipSlot.querySelector("button").addEventListener("click", () => {
      const inp = gfPortalEl.querySelector(".gf-picker-input");
      inp.value = "";
      inp.focus();
      renderGfPortalBody();
    });
  } else {
    chipSlot.innerHTML = "";
  }

  footerSummary.textContent = `Selected: ${loc.airports.join(", ")}`;
  renderGfPortalBody();
}

function renderGfPortalBody() {
  if (!activeLocatorSession || !gfPortalEl) return;
  const inputEl = gfPortalEl.querySelector(".gf-picker-input");
  const bodyEl = gfPortalEl.querySelector(".gf-picker-body");
  const q = inputEl.value.trim().toLowerCase();
  const loc = activeLocatorSession.getLocation();
  const selectedSet = new Set(loc.airports);

  const allGroups = buildAllCityGroups();

  // Filter & rank groups
  const matchingGroups = allGroups.filter((grp) => {
    if (!q) return true;
    if (grp.cityName.toLowerCase().includes(q)) return true;
    if (grp.countryName.toLowerCase().includes(q)) return true;
    if (grp.metroCode.toLowerCase().includes(q)) return true;
    if (
      grp.metroAirports.some(
        (a) =>
          a.code.toLowerCase().includes(q) ||
          a.name.toLowerCase().includes(q) ||
          a.city.toLowerCase().includes(q)
      )
    ) {
      return true;
    }
    return false;
  });

  // Sort so the active city group (or exact query match) comes first
  matchingGroups.sort((a, b) => {
    const aHasSelected = a.metroAirports.some((ap) => selectedSet.has(ap.code));
    const bHasSelected = b.metroAirports.some((ap) => selectedSet.has(ap.code));
    if (!q && aHasSelected !== bHasSelected) return aHasSelected ? -1 : 1;
    if (q) {
      const aStarts = a.cityName.toLowerCase().startsWith(q) || a.metroCode.toLowerCase() === q;
      const bStarts = b.cityName.toLowerCase().startsWith(q) || b.metroCode.toLowerCase() === q;
      if (aStarts !== bStarts) return aStarts ? -1 : 1;
    }
    return a.cityName.localeCompare(b.cityName);
  });

  bodyEl.innerHTML = "";

  matchingGroups.slice(0, 12).forEach((grp, idx) => {
    const metroCodes = grp.metroAirports.map((a) => a.code);
    const checkedMetroCount = metroCodes.filter((c) => selectedSet.has(c)).length;
    const allMetroChecked = checkedMetroCount === metroCodes.length && metroCodes.length > 0;
    const someMetroChecked = checkedMetroCount > 0 && !allMetroChecked;

    const groupEl = document.createElement("div");
    groupEl.className = "gf-city-group";

    const isExpanded = idx === 0 || checkedMetroCount > 0 || Boolean(q);

    groupEl.innerHTML = `
      <div class="gf-city-header">
        <input type="checkbox" class="gf-check gf-city-check" ${allMetroChecked ? "checked" : ""} />
        <div class="gf-city-titles">
          <div class="gf-city-name">${escapeHtml(grp.cityName)}, ${escapeHtml(grp.countryName)}</div>
          <div class="gf-city-sub">${escapeHtml(grp.subtitle)}</div>
        </div>
        <span class="gf-chevron">${isExpanded ? "⌃" : "⌄"}</span>
      </div>
      <div class="gf-airport-list ${isExpanded ? "" : "collapsed"}"></div>
    `;

    const cityCheck = groupEl.querySelector(".gf-city-check");
    cityCheck.indeterminate = someMetroChecked;

    // Clicking the City Checkbox selects this city and checks all its metro airports (or toggles between all and primary)
    cityCheck.addEventListener("click", (e) => {
      e.stopPropagation();
    });
    cityCheck.addEventListener("change", () => {
      if (cityCheck.checked) {
        // Switch to this city and select all its metro airports
        activeLocatorSession.setLocation(grp.cityName, [...metroCodes]);
      } else {
        // Keep at least the primary airport of this city selected
        activeLocatorSession.setLocation(grp.cityName, [grp.primaryCode]);
      }
      renderGfPortalChipAndBody();
    });

    // Clicking the city header row expands/collapses or selects this city if none of its airports are selected yet
    groupEl.querySelector(".gf-city-header").addEventListener("click", () => {
      const listEl = groupEl.querySelector(".gf-airport-list");
      const wasCollapsed = listEl.classList.contains("collapsed");
      if (checkedMetroCount === 0) {
        // Immediately switch to this city's primary/metro airports when user clicks a new city
        activeLocatorSession.setLocation(grp.cityName, [...metroCodes]);
        renderGfPortalChipAndBody();
        return;
      }
      listEl.classList.toggle("collapsed", !wasCollapsed);
      groupEl.querySelector(".gf-chevron").textContent = wasCollapsed ? "⌃" : "⌄";
    });

    const listEl = groupEl.querySelector(".gf-airport-list");

    // 1. Primary / Metro Airports for this City
    grp.metroAirports.forEach((ap) => {
      const isChecked = selectedSet.has(ap.code);
      const distMi = ap.city_distance_mi || 12;
      const row = document.createElement("label");
      row.className = "gf-airport-row";
      row.innerHTML = `
        <input type="checkbox" class="gf-check" ${isChecked ? "checked" : ""} />
        <div class="gf-airport-info">
          <div class="gf-airport-title">
            <span>${escapeHtml(ap.name)}</span>
            <span class="gf-airport-code">${escapeHtml(ap.code)}</span>
          </div>
          <div class="gf-airport-dist">${distMi} mi to destination</div>
        </div>
      `;
      const cb = row.querySelector("input");
      cb.addEventListener("change", () => {
        const curLoc = activeLocatorSession.getLocation();
        const belongsToCurrentCity = grp.metroAirports.some((m) =>
          curLoc.airports.includes(m.code)
        ) || grp.nearbyAirports.some((n) => curLoc.airports.includes(n.code));

        let nextAirports;
        let nextLabel = curLoc.label;
        if (!belongsToCurrentCity) {
          // User ticked an airport in a brand new city (e.g. switched from London to Athens ATH)
          nextLabel = grp.cityName;
          nextAirports = [ap.code];
        } else if (cb.checked) {
          nextAirports = curLoc.airports.includes(ap.code)
            ? curLoc.airports
            : [...curLoc.airports, ap.code];
        } else {
          nextAirports = curLoc.airports.filter((c) => c !== ap.code);
          if (nextAirports.length === 0) nextAirports = [ap.code];
        }
        activeLocatorSession.setLocation(nextLabel, nextAirports);
        renderGfPortalChipAndBody();
      });
      listEl.appendChild(row);
    });

    // 2. Nearby Regional Airports (e.g. Mykonos, Santorini, Thessaloniki, Crete when viewing Athens)
    if (grp.nearbyAirports.length > 0) {
      const div = document.createElement("div");
      div.className = "gf-section-divider";
      div.textContent = `Nearby & Regional Airports`;
      listEl.appendChild(div);

      grp.nearbyAirports.forEach((nb) => {
        const isChecked = selectedSet.has(nb.code);
        const row = document.createElement("label");
        row.className = "gf-airport-row";
        row.innerHTML = `
          <input type="checkbox" class="gf-check" ${isChecked ? "checked" : ""} />
          <div class="gf-airport-info">
            <div class="gf-airport-title">
              <span>${escapeHtml(nb.name)}</span>
              <span class="gf-airport-code">${escapeHtml(nb.code)}</span>
            </div>
            <div class="gf-airport-dist">${nb.distanceFromAnchorMi} mi from ${escapeHtml(grp.cityName)} (${escapeHtml(nb.city)})</div>
          </div>
        `;
        const cb = row.querySelector("input");
        cb.addEventListener("change", () => {
          const curLoc = activeLocatorSession.getLocation();
          const belongsToCurrentCity = grp.metroAirports.some((m) =>
            curLoc.airports.includes(m.code)
          ) || grp.nearbyAirports.some((n) => curLoc.airports.includes(n.code));

          let nextAirports;
          let nextLabel = curLoc.label;
          if (!belongsToCurrentCity) {
            nextLabel = grp.cityName;
            nextAirports = [grp.primaryCode, nb.code];
          } else if (cb.checked) {
            nextAirports = curLoc.airports.includes(nb.code)
              ? curLoc.airports
              : [...curLoc.airports, nb.code];
          } else {
            nextAirports = curLoc.airports.filter((c) => c !== nb.code);
            if (nextAirports.length === 0) nextAirports = [grp.primaryCode];
          }
          activeLocatorSession.setLocation(nextLabel, nextAirports);
          renderGfPortalChipAndBody();
        });
        listEl.appendChild(row);
      });
    }

    bodyEl.appendChild(groupEl);
  });
}

function openGoogleFlightsLocator({ anchorEl, getLocation, setLocation }) {
  const portal = ensureGfPortalElement();
  activeLocatorSession = { anchorEl, getLocation, setLocation };
  portal.classList.remove("hidden");
  positionGfPortal(anchorEl);

  const inputEl = portal.querySelector(".gf-picker-input");
  inputEl.value = "";
  renderGfPortalChipAndBody();
  setTimeout(() => inputEl.focus(), 10);
}

function attachRowLocationTrigger(containerEl, { getLocation, setLocation, disabled = false }) {
  const loc = getLocation();
  const visibleCodes = loc.airports.slice(0, 3);
  const extraCount = Math.max(0, loc.airports.length - visibleCodes.length);
  const codesHtml =
    visibleCodes.map((c) => `<span class="gf-code-pill">${escapeHtml(c)}</span>`).join("") +
    (extraCount > 0 ? `<span class="gf-code-pill">+${extraCount}</span>` : "");

  containerEl.innerHTML = `
    <button type="button" class="gf-row-locator-btn" ${disabled ? "disabled" : ""} title="${escapeHtml(loc.label)} (${escapeHtml(loc.airports.join(", "))}) — Click to change city or tick nearby airports">
      <span class="gf-locator-city">${escapeHtml(loc.label || "Select City")}</span>
      <span class="gf-locator-codes">
        ${codesHtml}
        <span style="font-size:0.65rem; color:#64748b; margin-left:2px">▾</span>
      </span>
    </button>
  `;

  const btn = containerEl.querySelector(".gf-row-locator-btn");
  btn.addEventListener("click", (e) => {
    e.stopPropagation();
    if (disabled) return;
    openGoogleFlightsLocator({
      anchorEl: btn,
      getLocation,
      setLocation: (newLabel, newCodes) => {
        setLocation(newLabel, newCodes);
        // Update trigger button text live while portal stays open
        const vis = newCodes.slice(0, 3);
        const ext = Math.max(0, newCodes.length - vis.length);
        btn.querySelector(".gf-locator-city").textContent = newLabel;
        btn.querySelector(".gf-locator-codes").innerHTML =
          vis.map((c) => `<span class="gf-code-pill">${escapeHtml(c)}</span>`).join("") +
          (ext > 0 ? `<span class="gf-code-pill">+${ext}</span>` : "") +
          `<span style="font-size:0.65rem; color:#64748b; margin-left:2px">▾</span>`;
      },
    });
  });
}

document.addEventListener("click", (e) => {
  if (gfPortalEl && !gfPortalEl.classList.contains("hidden")) {
    if (!gfPortalEl.contains(e.target) && !e.target.closest(".gf-row-locator-btn")) {
      closeGfLocationPortal();
    }
  }
});

/* --- Date Grid Helpers --- */
function getTripDatesArray(startIso, endIso) {
  const dates = [];
  const start = new Date(`${startIso}T00:00:00`);
  const end = new Date(`${endIso}T00:00:00`);
  if (isNaN(start) || isNaN(end) || end < start) return [startIso];

  const cur = new Date(start);
  let guard = 0;
  while (cur <= end && guard < 62) {
    const yyyy = cur.getFullYear();
    const mm = String(cur.getMonth() + 1).padStart(2, "0");
    const dd = String(cur.getDate()).padStart(2, "0");
    dates.push(`${yyyy}-${mm}-${dd}`);
    cur.setDate(cur.getDate() + 1);
    guard++;
  }
  return dates;
}

function formatShortDateParts(isoStr) {
  const d = new Date(`${isoStr}T00:00:00`);
  const dow = d.toLocaleDateString("en-US", { weekday: "short" });
  const month = d.toLocaleDateString("en-US", { month: "short" });
  const day = d.getDate();
  const isWeekend = d.getDay() === 0 || d.getDay() === 6;
  return { dow, month, day, isWeekend };
}

function getActiveItineraryScheduledMap() {
  const scheduledByStopId = new Map();
  let actualDepartureDate = null;
  let actualReturnDate = null;
  if (!currentOptimizationResponse) {
    return { scheduledByStopId, actualDepartureDate, actualReturnDate };
  }

  const allById = new Map();
  [
    currentOptimizationResponse.recommended,
    ...(currentOptimizationResponse.strategy_comparison || []),
    ...(currentOptimizationResponse.pareto_frontier || []),
  ].forEach((it) => {
    if (it) allById.set(it.itinerary_id, it);
  });
  const activeItin = allById.get(selectedItineraryId) || currentOptimizationResponse.recommended;
  if (!activeItin) {
    return { scheduledByStopId, actualDepartureDate, actualReturnDate };
  }

  if (activeItin.legs && activeItin.legs.length > 0) {
    actualDepartureDate = activeItin.legs[0].departure_date;
    actualReturnDate = activeItin.legs[activeItin.legs.length - 1].departure_date;
  }

  if (activeItin.stop_visits) {
    activeItin.stop_visits.forEach((v) => {
      scheduledByStopId.set(v.stop_id, {
        arrival: v.arrival_date,
        departure: v.departure_date,
        airport: v.arrival_airport,
        nights: v.nights,
      });
    });
  }
  return { scheduledByStopId, actualDepartureDate, actualReturnDate };
}

/**
 * Interactive Date-Range Painting & Click-Toggle Logic (Zero DOM Rebuild During Drag!)
 * - Dragging across cells paints [min(anchor, cur), max(anchor, cur)].
 * - Single-clicking a cell outside the current range expands the range to include it.
 * - Single-clicking inside the range moves the nearest boundary (start or end) to that cell.
 */
let activeDrag = null; // { rowKey, getRange, setRange, trackEl, winClass, tagText, anchorIso, moved }

function applyTrackVisualWindow(trackEl, winStart, winEnd, winClass, tagText, scheduledPredicate, scheduledTextFn) {
  const cells = trackEl.querySelectorAll(".date-cell");
  cells.forEach((cell) => {
    const iso = cell.getAttribute("data-iso");
    const dayNum = iso.slice(8);
    const inWin = iso >= winStart && iso <= winEnd;
    const isStart = iso === winStart;
    const isEnd = iso === winEnd;
    const isSched = scheduledPredicate ? scheduledPredicate(iso) : false;

    cell.classList.remove(
      "in-window",
      "dep-window",
      "ret-window",
      "window-start",
      "window-end",
      "scheduled-active",
      "endpoint-scheduled"
    );

    if (inWin) cell.classList.add(winClass);
    if (isStart) cell.classList.add("window-start");
    if (isEnd) cell.classList.add("window-end");
    if (isSched) {
      cell.classList.add(winClass === "in-window" ? "scheduled-active" : "endpoint-scheduled");
    }

    const tagEl = cell.querySelector(".cell-tag");
    if (tagEl) {
      if (isSched && scheduledTextFn) {
        tagEl.textContent = scheduledTextFn(iso);
      } else if (inWin && (isStart || isEnd)) {
        tagEl.textContent = tagText;
      } else if (inWin) {
        tagEl.textContent = "✓";
      } else {
        tagEl.textContent = "";
      }
    }
    const dayEl = cell.querySelector(".cell-day-num");
    if (dayEl) {
      dayEl.textContent = dayNum;
    }
  });
}

function attachInteractiveDateTrack({
  trackEl,
  rowBadgeTextEl,
  tripDates,
  getRange,
  setRange,
  winClass,
  tagText,
  scheduledPredicate,
  scheduledTextFn,
  tooltipPrefix,
}) {
  trackEl.innerHTML = "";
  const initial = getRange();

  tripDates.forEach((iso) => {
    const { isWeekend } = formatShortDateParts(iso);
    const cell = document.createElement("div");
    cell.className = `date-cell ${isWeekend ? "weekend" : ""}`;
    cell.setAttribute("data-iso", iso);
    cell.title = `${tooltipPrefix} — ${iso}\n• Click any date to expand/adjust range\n• Or click & drag across dates to paint range`;
    cell.innerHTML = `
      <span class="cell-day-num">${iso.slice(8)}</span>
      <span class="cell-tag"></span>
    `;

    cell.addEventListener("mousedown", (e) => {
      if (e.button !== 0) return;
      e.preventDefault();
      activeDrag = {
        trackEl,
        rowBadgeTextEl,
        getRange,
        setRange,
        winClass,
        tagText,
        scheduledPredicate,
        scheduledTextFn,
        anchorIso: iso,
        curIso: iso,
        moved: false,
      };
    });

    cell.addEventListener("mouseenter", () => {
      if (!activeDrag || activeDrag.trackEl !== trackEl) return;
      if (iso !== activeDrag.anchorIso) {
        activeDrag.moved = true;
      }
      activeDrag.curIso = iso;
      const newStart = iso >= activeDrag.anchorIso ? activeDrag.anchorIso : iso;
      const newEnd = iso >= activeDrag.anchorIso ? iso : activeDrag.anchorIso;
      setRange(newStart, newEnd);
      const committed = getRange();
      if (rowBadgeTextEl) {
        rowBadgeTextEl.textContent = `${committed.start.slice(5)}→${committed.end.slice(5)}`;
      }
      applyTrackVisualWindow(
        trackEl,
        committed.start,
        committed.end,
        winClass,
        tagText,
        scheduledPredicate,
        scheduledTextFn
      );
    });

    trackEl.appendChild(cell);
  });

  applyTrackVisualWindow(
    trackEl,
    initial.start,
    initial.end,
    winClass,
    tagText,
    scheduledPredicate,
    scheduledTextFn
  );
}

window.addEventListener("mouseup", () => {
  if (!activeDrag) return;
  const drag = activeDrag;
  activeDrag = null;

  if (!drag.moved) {
    // Single click! Smartly expand or trim the existing range so single-clicking works intuitively
    const { start, end } = drag.getRange();
    const clicked = drag.anchorIso;
    let nextStart = start;
    let nextEnd = end;

    if (clicked < start) {
      nextStart = clicked;
    } else if (clicked > end) {
      nextEnd = clicked;
    } else if (start === end) {
      nextStart = clicked;
      nextEnd = clicked;
    } else {
      // Clicked inside [start, end]: move whichever boundary is closer
      const dStart = Math.abs(new Date(clicked) - new Date(start));
      const dEnd = Math.abs(new Date(end) - new Date(clicked));
      if (dStart <= dEnd) {
        nextStart = clicked;
      } else {
        nextEnd = clicked;
      }
    }

    drag.setRange(nextStart, nextEnd);
    const committed = drag.getRange();
    if (drag.rowBadgeTextEl) {
      drag.rowBadgeTextEl.textContent = `${committed.start.slice(5)}→${committed.end.slice(5)}`;
    }
    applyTrackVisualWindow(
      drag.trackEl,
      committed.start,
      committed.end,
      drag.winClass,
      drag.tagText,
      drag.scheduledPredicate,
      drag.scheduledTextFn
    );
  }

  setResultsStale(true);
  saveStateToCookieAndStorage();
});

/* --- Render Compact Between-Row Cabin & Stops Selector (Full Width) --- */
function createFlightConnectorRow({
  legLabel,
  fromCode,
  toCode,
  isFlexibleTarget,
  currentCabin,
  onSelectCabin,
  currentStops = "auto",
  onSelectStops,
}) {
  const resolved = resolvePreviewCabin(fromCode, toCode, currentCabin);
  const resolvedStops = resolvePreviewStops(fromCode, toCode, currentStops);
  const row = document.createElement("div");
  row.className = "flight-connector-row";

  const cabinOptions = [
    { value: "auto", label: "✨ Auto" },
    { value: "economy", label: "Economy" },
    { value: "premium_economy", label: "Premium Econ" },
    { value: "business", label: "Business" },
    { value: "first", label: "First" },
  ];

  const stopsOptions = [
    { value: "auto", label: "✨ Auto" },
    { value: "nonstop", label: "Nonstop" },
    { value: "one_stop", label: "≤1 Stop" },
    { value: "any", label: "Any" },
  ];

  const routeDisplay = isFlexibleTarget
    ? `✈️ ${escapeHtml(legLabel)}: <strong>→ ${escapeHtml(toCode)}</strong> <span style="font-weight:400; color:#64748b">(inbound leg)</span>`
    : `✈️ ${escapeHtml(legLabel)}: <strong>${escapeHtml(fromCode)} → ${escapeHtml(toCode)}</strong>`;

  const autoNotes = [];
  if (currentCabin === "auto") autoNotes.push(resolved.autoReason);
  if (currentStops === "auto") autoNotes.push(resolvedStops.autoReason);

  row.innerHTML = `
    <span class="connector-route">${routeDisplay}</span>
    <div class="connector-cabin-pills"></div>
    <span class="muted-sep" style="margin-left:0.25rem; font-weight:600">Stops:</span>
    <div class="connector-stops-pills"></div>
    <span class="connector-resolved">${escapeHtml(autoNotes.join(" · "))}</span>
  `;

  const pillsBox = row.querySelector(".connector-cabin-pills");
  cabinOptions.forEach((opt) => {
    const btn = document.createElement("button");
    btn.type = "button";
    const isDirectActive = currentCabin === opt.value;
    const isAutoResolved = currentCabin === "auto" && resolved.cabin === opt.value;
    const classes = ["cabin-pill-btn"];
    if (isDirectActive) classes.push("active");
    if (isAutoResolved) classes.push("auto-resolved");
    btn.className = classes.join(" ");
    btn.textContent = opt.label;
    btn.title = isAutoResolved
      ? `Chosen by Auto rule (${resolved.autoReason}). Click to lock ${opt.label}.`
      : `Set cabin class for ${fromCode} → ${toCode}`;
    btn.addEventListener("click", () => onSelectCabin(opt.value));
    pillsBox.appendChild(btn);
  });

  const stopsBox = row.querySelector(".connector-stops-pills");
  stopsOptions.forEach((opt) => {
    const btn = document.createElement("button");
    btn.type = "button";
    const isDirectActive = currentStops === opt.value;
    const isAutoResolved = currentStops === "auto" && resolvedStops.stops === opt.value;
    const classes = ["cabin-pill-btn", "stops-pill-btn"];
    if (isDirectActive) classes.push("active");
    if (isAutoResolved) classes.push("auto-resolved");
    btn.className = classes.join(" ");
    btn.textContent = opt.label;
    btn.title = isAutoResolved
      ? `Chosen by Auto Stops rule (${resolvedStops.autoReason}). Click to lock ${opt.label}.`
      : `Set maximum stops for ${fromCode} → ${toCode}`;
    if (onSelectStops) {
      btn.addEventListener("click", () => onSelectStops(opt.value));
    }
    stopsBox.appendChild(btn);
  });

  return row;
}

/* --- Render Full Compact Timeline Matrix --- */
function renderBuilder() {
  if (!testingMode && state.provider_mode === "offline") {
    state.provider_mode = "auto";
    saveStateToCookieAndStorage();
  }
  clampDatesToTripWindow();

  if (state.same_as_origin) {
    state.destination_label = state.origin_label;
    state.destination_airports = [...state.origin_airports];
  }

  // Toolbar inputs
  const provSelect = document.getElementById("providerModeSelect");
  if (provSelect) {
    provSelect.value = state.provider_mode === "offline" ? "auto" : state.provider_mode || "auto";
    provSelect.disabled = state.provider_mode === "offline";
  }
  document.getElementById("simulationToggle").checked = state.provider_mode === "offline";
  const maxApiInput = document.getElementById("maxApiCallsInput");
  if (maxApiInput) {
    maxApiInput.value = String(state.max_api_calls_per_run || 25);
  }

  document.getElementById("earliestDepartureInput").value = state.earliest_departure;
  document.getElementById("latestReturnInput").value = state.latest_return;
  document.getElementById("orderingModeSelect").value = state.ordering_mode || "flexible";
  document.getElementById("sameAsOriginToggle").checked = Boolean(state.same_as_origin);

  document.getElementById("includeCarryOnCheck").checked = Boolean(state.baggage.include_carry_on);
  document.getElementById("checkedBagsCountSelect").value = String(state.baggage.checked_bags || 0);

  document.getElementById("defaultCabinSelect").value = state.cabin_policy.default_cabin;
  document.getElementById("longHaulCabinSelect").value = state.cabin_policy.long_haul_cabin;
  document.getElementById("longHaulThresholdInput").value = state.cabin_policy.long_haul_threshold_hours;

  const shortStopsEl = document.getElementById("shortHaulStopsSelect");
  if (shortStopsEl) shortStopsEl.value = state.stops_policy.short_haul_stops;
  const longStopsEl = document.getElementById("longHaulStopsSelect");
  if (longStopsEl) longStopsEl.value = state.stops_policy.long_haul_stops;
  const maxLayoverEl = document.getElementById("maxLayoverHoursInput");
  if (maxLayoverEl) maxLayoverEl.value = state.stops_policy.max_layover_hours ?? 6.0;
  const nonstopThreshEl = document.getElementById("nonstopThresholdInput");
  if (nonstopThreshEl) nonstopThreshEl.value = state.stops_policy.nonstop_threshold_hours;

  document.getElementById("valueOfTimeInput").value = state.weights.value_of_time_per_hour;
  document.getElementById("valueOfTimeLabel").textContent = `$${state.weights.value_of_time_per_hour} / hr`;
  document.getElementById("protectedTransferInput").value = state.weights.protected_transfer_penalty;
  document.getElementById("protectedTransferLabel").textContent = `$${state.weights.protected_transfer_penalty} / stop`;
  document.getElementById("selfTransferInput").value = state.weights.self_transfer_penalty;
  document.getElementById("selfTransferLabel").textContent = `$${state.weights.self_transfer_penalty} / split`;
  document.getElementById("enableHubSplittingCheck").checked = Boolean(state.weights.enable_hub_splitting);

  // Build the Heatmap / Timeline Grid
  const matrixEl = document.getElementById("timelineMatrix");
  matrixEl.innerHTML = "";

  const tripDates = getTripDatesArray(state.earliest_departure, state.latest_return);
  const { scheduledByStopId, actualDepartureDate, actualReturnDate } =
    getActiveItineraryScheduledMap();

  if (!state.latest_departure || state.latest_departure < state.earliest_departure) {
    state.latest_departure = tripDates[Math.min(2, tripDates.length - 1)];
  }
  if (!state.earliest_return || state.earliest_return > state.latest_return) {
    state.earliest_return = tripDates[Math.max(0, tripDates.length - 3)];
  }

  // 1. Header Row (Columns = Dates)
  const headerRow = document.createElement("div");
  headerRow.className = "matrix-row matrix-header-row";
  const dateHeadersHtml = tripDates
    .map((iso, i) => {
      const { dow, month, day, isWeekend } = formatShortDateParts(iso);
      const showMonth =
        i === 0 || day === 1
          ? `<span class="dow">${month}</span>`
          : `<span class="dow">${dow}</span>`;
      return `
        <div class="date-col-header ${isWeekend ? "weekend" : ""}" title="${iso}">
          ${showMonth}
          <strong>${day}</strong>
        </div>
      `;
    })
    .join("");

  headerRow.innerHTML = `
    <div class="matrix-left-cell">
      <span>STOP / AIRPORTS &amp; STAY NIGHTS</span>
      <span style="color:#94a3b8; font-weight:400">Click or drag dates →</span>
    </div>
    <div class="matrix-dates-track">${dateHeadersHtml}</div>
  `;
  matrixEl.appendChild(headerRow);

  // 2. Origin Row (Start) — compact single line with Google Flights Location Picker + Departure Date Range
  const originRow = document.createElement("div");
  originRow.className = "matrix-row endpoint-row";
  const depWinStart = state.earliest_departure;
  const depWinEnd = state.latest_departure || state.earliest_departure;

  originRow.innerHTML = `
    <div class="matrix-left-cell">
      <div class="stop-row-top">
        <span class="row-badge start">START</span>
        <div class="origin-locator-slot" style="flex:1; min-width:0; display:flex"></div>
        <span class="origin-range-label" style="font-size:0.7rem; font-weight:600; color:#166534; white-space:nowrap">
          ${depWinStart.slice(5)}→${depWinEnd.slice(5)}
        </span>
      </div>
    </div>
    <div class="matrix-dates-track origin-dates-track"></div>
  `;

  attachRowLocationTrigger(originRow.querySelector(".origin-locator-slot"), {
    getLocation: () => ({
      label: state.origin_label,
      airports: state.origin_airports,
    }),
    setLocation: (newLabel, newCodes) => {
      state.origin_label = newLabel;
      state.origin_airports = newCodes;
      if (state.same_as_origin) {
        state.destination_label = newLabel;
        state.destination_airports = [...newCodes];
      }
      setResultsStale(true);
      saveStateToCookieAndStorage();
    },
  });

  attachInteractiveDateTrack({
    trackEl: originRow.querySelector(".origin-dates-track"),
    rowBadgeTextEl: originRow.querySelector(".origin-range-label"),
    tripDates,
    getRange: () => ({
      start: state.earliest_departure,
      end: state.latest_departure || state.earliest_departure,
    }),
    setRange: (_newStart, newEnd) => {
      state.latest_departure = newEnd >= state.earliest_departure ? newEnd : state.earliest_departure;
    },
    winClass: "dep-window",
    tagText: "DEP",
    scheduledPredicate: (iso) => !resultsStale && iso === actualDepartureDate,
    scheduledTextFn: () => "✈️ DEP",
    tooltipPrefix: `Origin (${state.origin_label}) Departure Window`,
  });

  matrixEl.appendChild(originRow);

  // 3. Interleaved Flight Connector + Stop Rows
  state.stops.forEach((stop, idx) => {
    const prevCode = idx === 0 ? state.origin_airports[0] : state.stops[idx - 1].airports[0];
    const currCode = stop.airports[0] || "LHR";
    const isFlexibleTarget =
      state.ordering_mode === "auto_tsp" ||
      (state.ordering_mode === "flexible" && !stop.fixed_order);

    // Flight Connector Row BEFORE Stop `idx`
    const connector = createFlightConnectorRow({
      legLabel: `Flight ${idx + 1}`,
      fromCode: prevCode,
      toCode: currCode,
      isFlexibleTarget,
      currentCabin: stop.outbound_cabin || "auto",
      onSelectCabin: (val) => {
        stop.outbound_cabin = val;
        onStateMutated();
      },
      currentStops: stop.outbound_stops || "auto",
      onSelectStops: (val) => {
        stop.outbound_stops = val;
        onStateMutated();
      },
    });
    matrixEl.appendChild(connector);

    // Stop Row — single-line layout with Google Flights Location Picker Trigger
    const stopRow = document.createElement("div");
    stopRow.className = "matrix-row";

    const sched = scheduledByStopId.get(stop.id);

    stopRow.innerHTML = `
      <div class="matrix-left-cell">
        <div class="stop-row-top">
          <span class="row-badge">#${idx + 1}</span>
          <div class="stop-locator-slot" style="flex:1; min-width:0; display:flex"></div>
          <div class="nights-inline" title="Min and Max nights to stay in ${escapeHtml(stop.label)}">
            <input type="number" class="stop-min-n" min="1" max="60" value="${stop.min_nights}" />
            <span>–</span>
            <input type="number" class="stop-max-n" min="1" max="60" value="${stop.max_nights}" />
            <span>n</span>
          </div>
          <div class="row-mini-actions">
            <button type="button" class="mini-btn ${stop.fixed_order ? "pinned" : ""}" data-act="pin" title="Pin city order vs allow optimizer to reorder">📌</button>
            <button type="button" class="mini-btn" data-act="up" ${idx === 0 ? "disabled" : ""} title="Move row up">↑</button>
            <button type="button" class="mini-btn" data-act="down" ${idx === state.stops.length - 1 ? "disabled" : ""} title="Move row down">↓</button>
            <button type="button" class="mini-btn" data-act="del" ${state.stops.length <= 1 ? "disabled" : ""} title="Remove stop">✕</button>
          </div>
        </div>
      </div>
      <div class="matrix-dates-track stop-dates-track"></div>
    `;

    attachRowLocationTrigger(stopRow.querySelector(".stop-locator-slot"), {
      getLocation: () => ({
        label: stop.label,
        airports: stop.airports,
      }),
      setLocation: (newLabel, newCodes) => {
        stop.label = newLabel;
        stop.airports = newCodes;
        setResultsStale(true);
        saveStateToCookieAndStorage();
      },
    });

    // Min/max nights
    stopRow.querySelector(".stop-min-n").addEventListener("change", (e) => {
      stop.min_nights = Math.max(1, parseInt(e.target.value || "1", 10));
      if (stop.max_nights < stop.min_nights) stop.max_nights = stop.min_nights;
      onStateMutated();
    });
    stopRow.querySelector(".stop-max-n").addEventListener("change", (e) => {
      stop.max_nights = Math.max(stop.min_nights, parseInt(e.target.value || "1", 10));
      onStateMutated();
    });

    // Row actions
    stopRow.querySelector('[data-act="pin"]').addEventListener("click", () => {
      stop.fixed_order = !stop.fixed_order;
      onStateMutated();
    });
    stopRow.querySelector('[data-act="up"]').addEventListener("click", () => {
      if (idx > 0) {
        [state.stops[idx - 1], state.stops[idx]] = [state.stops[idx], state.stops[idx - 1]];
        onStateMutated();
      }
    });
    stopRow.querySelector('[data-act="down"]').addEventListener("click", () => {
      if (idx < state.stops.length - 1) {
        [state.stops[idx + 1], state.stops[idx]] = [state.stops[idx], state.stops[idx + 1]];
        onStateMutated();
      }
    });
    stopRow.querySelector('[data-act="del"]').addEventListener("click", () => {
      if (state.stops.length > 1) {
        state.stops.splice(idx, 1);
        onStateMutated();
      }
    });

    // Attach smooth, zero-rebuild click & drag date range selector
    attachInteractiveDateTrack({
      trackEl: stopRow.querySelector(".stop-dates-track"),
      rowBadgeTextEl: null,
      tripDates,
      getRange: () => ({
        start: stop.earliest_arrival || state.earliest_departure,
        end: stop.latest_departure || state.latest_return,
      }),
      setRange: (newStart, newEnd) => {
        stop.earliest_arrival = newStart;
        stop.latest_departure = newEnd;
      },
      winClass: "in-window",
      tagText: "OK",
      scheduledPredicate: (iso) =>
        Boolean(!resultsStale && sched && iso >= sched.arrival && iso < sched.departure),
      scheduledTextFn: () => sched.airport,
      tooltipPrefix: `${stop.label} Allowed Stay Window`,
    });

    matrixEl.appendChild(stopRow);
  });

  // 4. Final Return Flight Connector Row + Return Destination Row (with Return Date Range!)
  const lastStop = state.stops[state.stops.length - 1];
  const lastFromCode = lastStop ? lastStop.airports[0] : state.origin_airports[0];
  const destCode = state.destination_airports[0] || state.origin_airports[0];

  const returnConnector = createFlightConnectorRow({
    legLabel: `Return Flight`,
    fromCode: lastFromCode,
    toCode: destCode,
    isFlexibleTarget: false,
    currentCabin: state.return_leg_cabin || "auto",
    onSelectCabin: (val) => {
      state.return_leg_cabin = val;
      onStateMutated();
    },
    currentStops: state.return_leg_stops || "auto",
    onSelectStops: (val) => {
      state.return_leg_stops = val;
      onStateMutated();
    },
  });
  matrixEl.appendChild(returnConnector);

  const destRow = document.createElement("div");
  destRow.className = "matrix-row endpoint-row";
  const retWinStart = state.earliest_return || state.latest_return;
  const retWinEnd = state.latest_return;

  destRow.innerHTML = `
    <div class="matrix-left-cell">
      <div class="stop-row-top">
        <span class="row-badge end">END</span>
        <div class="dest-locator-slot" style="flex:1; min-width:0; display:flex"></div>
        <span class="dest-range-label" style="font-size:0.7rem; font-weight:600; color:#92400e; white-space:nowrap">
          ${retWinStart.slice(5)}→${retWinEnd.slice(5)}
        </span>
      </div>
    </div>
    <div class="matrix-dates-track dest-dates-track"></div>
  `;

  attachInteractiveDateTrack({
    trackEl: destRow.querySelector(".dest-dates-track"),
    rowBadgeTextEl: destRow.querySelector(".dest-range-label"),
    tripDates,
    getRange: () => ({
      start: state.earliest_return || state.latest_return,
      end: state.latest_return,
    }),
    setRange: (newStart, _newEnd) => {
      state.earliest_return = newStart <= state.latest_return ? newStart : state.latest_return;
    },
    winClass: "ret-window",
    tagText: "RET",
    scheduledPredicate: (iso) => !resultsStale && iso === actualReturnDate,
    scheduledTextFn: () => "✈️ RET",
    tooltipPrefix: `Final Return (${state.destination_label}) Window`,
  });

  attachRowLocationTrigger(destRow.querySelector(".dest-locator-slot"), {
    getLocation: () => ({
      label: state.destination_label,
      airports: state.destination_airports,
    }),
    setLocation: (newLabel, newCodes) => {
      if (state.same_as_origin) return;
      state.destination_label = newLabel;
      state.destination_airports = newCodes;
      setResultsStale(true);
      saveStateToCookieAndStorage();
    },
    disabled: Boolean(state.same_as_origin),
  });

  matrixEl.appendChild(destRow);
}

function onStateMutated() {
  setResultsStale(true);
  saveStateToCookieAndStorage();
  renderBuilder();
}

/* --- Optimization Progress Bar & Live Query Feed --- */
let recentCompletedQueries = [];

function estimateInitialQueryPlan(payload) {
  const stops = payload.stops || [];
  const legCount = stops.length + 1;
  const maxSchedules =
    payload.provider_mode === "serpapi" || payload.provider_mode === "fast_flights" ? 4 : 8;
  const plannedQueries = [];

  let curDate = payload.earliest_departure;
  for (let i = 0; i < stops.length; i++) {
    const prevAirports = i === 0 ? payload.origin_airports : stops[i - 1].airports;
    const nextAirports = stops[i].airports;
    const fromCode = (prevAirports && prevAirports[0]) || "ORIG";
    const toCode = (nextAirports && nextAirports[0]) || "DEST";
    const resolved = resolvePreviewCabin(fromCode, toCode, stops[i].outbound_cabin);
    plannedQueries.push({
      route: `${prevAirports.join(", ")} → ${nextAirports.join(", ")}`,
      date: curDate,
      cabin: formatCabinName(resolved.cabin),
      label: `${prevAirports.join(", ")} → ${nextAirports.join(", ")} (${curDate} · ${formatCabinName(resolved.cabin)})`,
    });
    const d = new Date(`${curDate}T00:00:00Z`);
    if (!isNaN(d)) {
      d.setUTCDate(d.getUTCDate() + Number(stops[i].min_nights || 3));
      curDate = d.toISOString().slice(0, 10);
    }
  }

  const lastAirports = stops.length > 0 ? stops[stops.length - 1].airports : payload.origin_airports;
  const destAirports = payload.destination_airports;
  const retResolved = resolvePreviewCabin(
    (lastAirports && lastAirports[0]) || "ORIG",
    (destAirports && destAirports[0]) || "DEST",
    payload.return_leg_cabin
  );
  const retDate = payload.earliest_return || payload.latest_return;
  plannedQueries.push({
    route: `${lastAirports.join(", ")} → ${destAirports.join(", ")}`,
    date: retDate,
    cabin: formatCabinName(retResolved.cabin),
    label: `${lastAirports.join(", ")} → ${destAirports.join(", ")} (${retDate} · ${formatCabinName(retResolved.cabin)})`,
  });

  const hubExtra = payload.weights && payload.weights.enable_hub_splitting ? 4 : 0;
  const estimatedTotal = Math.max(legCount, legCount * 2 + hubExtra);
  return {
    schedulesTotal: maxSchedules,
    queriesTotal: estimatedTotal,
    plannedQueries,
  };
}

function showInitialOptimizationProgress(payload) {
  recentCompletedQueries = [];
  const panel = document.getElementById("optimizeProgress");
  if (!panel) return;
  panel.classList.remove("hidden");

  const plan = estimateInitialQueryPlan(payload);
  const firstQuery = plan.plannedQueries[0]
    ? `🔍 Querying ${plan.plannedQueries[0].label}…`
    : "Preparing flight queries…";

  const phaseEl = document.getElementById("optimizeProgressPhase");
  const curQueryEl = document.getElementById("optimizeCurrentQuery");
  const countsEl = document.getElementById("optimizeProgressCounts");
  const pctEl = document.getElementById("optimizeProgressPct");
  const fillEl = document.getElementById("optimizeProgressFill");
  const barEl = document.getElementById("optimizeProgressBar");
  const schedEl = document.getElementById("progressScheduleText");
  const hitsEl = document.getElementById("progressCacheHitsText");
  const liveEl = document.getElementById("progressLiveCallsText");
  const recentEl = document.getElementById("progressRecentQueries");

  if (phaseEl) {
    phaseEl.textContent = "Generating candidate schedules & evaluating ticket splits…";
  }
  if (curQueryEl) {
    curQueryEl.textContent = firstQuery;
  }
  if (countsEl) {
    countsEl.textContent = `0 / ${plan.queriesTotal} queries`;
  }
  if (pctEl) {
    pctEl.textContent = "5%";
  }
  if (fillEl) {
    fillEl.style.width = "5%";
  }
  if (barEl) {
    barEl.setAttribute("aria-valuenow", "5");
  }
  if (schedEl) {
    schedEl.textContent = `📅 Schedule: 1 / ${plan.schedulesTotal}`;
  }
  if (hitsEl) {
    hitsEl.textContent = "⚡ Cache hits: 0";
  }
  if (liveEl) {
    liveEl.textContent = "🌐 Live queries: 0";
  }
  if (recentEl) {
    recentEl.innerHTML = plan.plannedQueries
      .slice(0, 4)
      .map(
        (q, idx) =>
          `<span class="progress-query-chip ${idx === 0 ? "active" : ""}">${idx === 0 ? "🔄" : "⏳"} ${escapeHtml(q.route)} (${escapeHtml(q.date.slice(5))})</span>`
      )
      .join("");
  }
}

function updateOptimizationProgressUI(ev) {
  const panel = document.getElementById("optimizeProgress");
  if (!panel) return;
  panel.classList.remove("hidden");

  const pct = Math.max(0, Math.min(100, Number(ev.progress_pct ?? 5)));
  const doneQ = Number(ev.queries_completed ?? 0);
  const totalQ = Math.max(doneQ, Number(ev.queries_total ?? 1));
  const schedIdx = Number(ev.schedule_index ?? 1);
  const schedTotal = Math.max(schedIdx, Number(ev.schedules_total ?? 1));

  const phaseEl = document.getElementById("optimizeProgressPhase");
  const curQueryEl = document.getElementById("optimizeCurrentQuery");
  const countsEl = document.getElementById("optimizeProgressCounts");
  const pctEl = document.getElementById("optimizeProgressPct");
  const fillEl = document.getElementById("optimizeProgressFill");
  const barEl = document.getElementById("optimizeProgressBar");
  const schedEl = document.getElementById("progressScheduleText");
  const hitsEl = document.getElementById("progressCacheHitsText");
  const liveEl = document.getElementById("progressLiveCallsText");
  const recentEl = document.getElementById("progressRecentQueries");

  if (phaseEl) {
    if (ev.strategy_label) {
      phaseEl.textContent = `Schedule ${schedIdx}/${schedTotal}${ev.schedule_route ? ` (${ev.schedule_route})` : ""} — ${ev.strategy_label}`;
    } else {
      phaseEl.textContent = `Optimizing Multi-City Schedules (${schedIdx}/${schedTotal})…`;
    }
  }

  if (curQueryEl && ev.current_query) {
    const prefix = ev.phase === "query_start" ? "🔍 Querying " : ev.phase === "query_done" ? "✓ Queried " : "⚙️ ";
    curQueryEl.textContent = `${prefix}${ev.current_query}`;
  }

  if (countsEl) {
    countsEl.textContent = `${doneQ} / ${totalQ} queries`;
  }
  if (pctEl) {
    pctEl.textContent = `${pct}%`;
  }
  if (fillEl) {
    fillEl.style.width = `${pct}%`;
  }
  if (barEl) {
    barEl.setAttribute("aria-valuenow", String(pct));
  }
  if (schedEl) {
    schedEl.textContent = `📅 Schedule: ${schedIdx} / ${schedTotal}`;
  }
  if (hitsEl) {
    hitsEl.textContent = `⚡ Cache hits: ${ev.cache_hits ?? 0}`;
  }
  if (liveEl) {
    liveEl.textContent = `🌐 Live queries: ${ev.live_calls ?? 0}`;
  }

  if (ev.last_query) {
    recentCompletedQueries.unshift(ev.last_query);
    recentCompletedQueries = recentCompletedQueries.slice(0, 4);
  }

  if (recentEl) {
    const chips = [];
    if (ev.phase === "query_start" && ev.current_query) {
      chips.push(
        `<span class="progress-query-chip active">🔄 ${escapeHtml(ev.current_query)}</span>`
      );
    }
    recentCompletedQueries.slice(0, 4 - chips.length).forEach((q) => {
      const icon = q.source === "cache" ? "⚡" : q.source === "live" ? "🌐" : "🧪";
      const cls = q.source === "cache" ? "cache" : q.source === "live" ? "live" : "";
      chips.push(
        `<span class="progress-query-chip ${cls}">${icon} ${escapeHtml(q.route)} (${escapeHtml((q.date || "").slice(5))} · ${q.options_count ?? 0} flights)</span>`
      );
    });
    if (chips.length > 0) {
      recentEl.innerHTML = chips.join("");
    }
  }
}

function hideOptimizationProgress() {
  const panel = document.getElementById("optimizeProgress");
  if (panel) {
    panel.classList.add("hidden");
  }
}

/* --- Run Optimization & Render Results --- */
async function runOptimization() {
  const btn = document.getElementById("optimizeBtn");
  btn.disabled = true;
  btn.classList.remove("stale-pulse");
  btn.textContent = "⏳ Optimizing Schedules & Ticket Splits…";

  const payload = {
    origin_label: state.origin_label,
    origin_airports: state.origin_airports,
    destination_label: state.destination_label,
    destination_airports: state.destination_airports,
    earliest_departure: state.earliest_departure,
    latest_departure: state.latest_departure || state.earliest_departure,
    earliest_return: state.earliest_return || state.latest_return,
    latest_return: state.latest_return,
    return_leg_cabin: state.return_leg_cabin,
    return_leg_stops: state.return_leg_stops || "auto",
    ordering_mode: state.ordering_mode,
    stops: state.stops,
    baggage: state.baggage,
    cabin_policy: state.cabin_policy,
    stops_policy: state.stops_policy || DEFAULT_STOPS_POLICY,
    weights: state.weights,
    provider_mode: state.provider_mode || "auto",
    max_api_calls_per_run: Number(state.max_api_calls_per_run || 25),
    force_refresh: document.getElementById("forceRefreshCheck").checked,
  };

  showInitialOptimizationProgress(payload);

  try {
    const resp = await fetch("/api/optimize", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-Stream-Progress": "1",
      },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      let detail = resp.statusText || `HTTP ${resp.status}`;
      const errText = await resp.text().catch(() => "");
      if (errText) {
        try {
          const errData = JSON.parse(errText);
          if (errData && errData.detail) {
            detail =
              typeof errData.detail === "string"
                ? errData.detail
                : JSON.stringify(errData.detail);
          }
        } catch {
          detail = errText;
        }
      }
      throw new Error(detail);
    }

    const contentType = resp.headers.get("content-type") || "";
    let data = null;

    if (contentType.includes("application/x-ndjson") && resp.body) {
      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const rawLine of lines) {
          const line = rawLine.trim();
          if (!line) continue;
          const msg = JSON.parse(line);
          if (msg.type === "progress") {
            updateOptimizationProgressUI(msg);
          } else if (msg.type === "error") {
            throw new Error(msg.detail || "Optimization failed");
          } else if (msg.type === "result") {
            data = msg.data;
          }
        }
      }

      if (buffer.trim()) {
        const msg = JSON.parse(buffer.trim());
        if (msg.type === "progress") {
          updateOptimizationProgressUI(msg);
        } else if (msg.type === "error") {
          throw new Error(msg.detail || "Optimization failed");
        } else if (msg.type === "result") {
          data = msg.data;
        }
      }
    } else {
      data = await resp.json();
    }

    if (!data) {
      throw new Error("Optimization completed without returning results.");
    }

    currentOptimizationResponse = data;
    selectedItineraryId = data.recommended.itinerary_id;
    setResultsStale(false);
    updateCacheStatusUI(data.cache_stats);
    renderBuilder();
    renderOptimizationResults(data);
  } catch (err) {
    document.getElementById("resultsContainer").innerHTML = `
      <div class="card" style="border-color:#dc2626">
        <h3 style="color:#dc2626; margin-top:0">Optimization Error</h3>
        <p>${escapeHtml(err.message)}</p>
      </div>
    `;
  } finally {
    hideOptimizationProgress();
    btn.disabled = false;
    setResultsStale(resultsStale);
  }
}

function updateCacheStatusUI(stats) {
  if (!stats) return;
  const el = document.getElementById("cacheStatusText");
  if (el) {
    el.textContent = `Cache: ${stats.total_cached_flights_in_db} flights (${stats.cache_hits} hits / ${stats.cache_misses} fetched)`;
  }
  const serpEl = document.getElementById("serpQuotaText");
  if (serpEl) {
    const runDelta = stats.serpapi_calls_this_run ? ` (+${stats.serpapi_calls_this_run} run)` : "";
    serpEl.textContent = `SerpApi: ${stats.total_serpapi_calls_logged || 0} / 250${runDelta}`;
  }
}

function getTicketGoogleFlightsUrl(ticket) {
  if (ticket && ticket.google_flights_url && /^https?:\/\//i.test(ticket.google_flights_url)) {
    return ticket.google_flights_url;
  }
  const legs = (ticket && ticket.legs) || [];
  const cabinLabel =
    (ticket && ticket.cabin_summary) || (legs[0] ? formatCabinName(legs[0].cabin) : "Economy");
  if (legs.length === 1) {
    const l = legs[0];
    const q = `Flights from ${String(l.origin).toUpperCase()} to ${String(l.destination).toUpperCase()} on ${l.departure_date} one way ${formatCabinName(l.cabin)}`;
    return `https://www.google.com/travel/flights?q=${encodeURIComponent(q)}&hl=en&curr=USD`;
  }
  if (
    legs.length === 2 &&
    String(legs[0].origin).toUpperCase() === String(legs[1].destination).toUpperCase() &&
    String(legs[0].destination).toUpperCase() === String(legs[1].origin).toUpperCase()
  ) {
    const q = `Flights from ${String(legs[0].origin).toUpperCase()} to ${String(legs[0].destination).toUpperCase()} on ${legs[0].departure_date} return ${legs[1].departure_date} ${cabinLabel}`;
    return `https://www.google.com/travel/flights?q=${encodeURIComponent(q)}&hl=en&curr=USD`;
  }
  if (legs.length >= 2) {
    const slices = legs
      .map(
        (l) =>
          `${String(l.origin).toUpperCase()} to ${String(l.destination).toUpperCase()} on ${l.departure_date}`
      )
      .join(", ");
    const q = `Multi-city flights ${slices} ${cabinLabel}`.trim();
    return `https://www.google.com/travel/flights?q=${encodeURIComponent(q)}&hl=en&curr=USD`;
  }
  return "https://www.google.com/travel/flights?hl=en&curr=USD";
}

function renderOptimizationResults(data) {
  const container = document.getElementById("resultsContainer");
  const allById = new Map();
  [data.recommended, ...data.strategy_comparison, ...data.pareto_frontier].forEach((it) => {
    if (it) allById.set(it.itinerary_id, it);
  });
  const activeItin = allById.get(selectedItineraryId) || data.recommended;

  const warningsHtml =
    data.warnings && data.warnings.length
      ? `<div class="card" style="background:#fffbeb; border-color:#f59e0b; font-size:0.82rem;">
          ⚠️ ${data.warnings.map((w) => escapeHtml(w)).join("<br/>")}
        </div>`
      : "";

  const strategyRowsHtml = data.strategy_comparison
    .map((itin) => {
      const isSelected = itin.itinerary_id === activeItin.itinerary_id;
      const diffSingle = itin.savings_vs_single_ticket_usd;
      const diffText =
        diffSingle > 0
          ? `<span class="savings-pos">Save $${diffSingle.toFixed(0)}</span>`
          : diffSingle < 0
          ? `<span class="savings-neg">+$${Math.abs(diffSingle).toFixed(0)}</span>`
          : `<span>Baseline</span>`;

      const badges = (itin.badges || [])
        .map((b) => `<span class="award-badge">${escapeHtml(b)}</span>`)
        .join(" ");

      return `
        <tr class="${isSelected ? "active-row" : ""}" data-itin-id="${escapeHtml(itin.itinerary_id)}">
          <td>
            <strong>${escapeHtml(itin.strategy_label)}</strong>
            <div>${badges}</div>
          </td>
          <td><strong>$${itin.total_price_usd.toFixed(0)}</strong></td>
          <td>${diffText}</td>
          <td>${itin.total_travel_hours.toFixed(1)}h</td>
          <td>${itin.tickets.length} ticket${itin.tickets.length > 1 ? "s" : ""}</td>
          <td>${itin.protected_transfers} prot / ${itin.self_transfers} self</td>
        </tr>
      `;
    })
    .join("");

  const ticketsHtml = activeItin.tickets
    .map((t) => {
      const legsRows = t.legs
        .map(
          (l) => `
          <div class="ticket-leg-row">
            <div>
              <span class="badge-subtle" style="margin-left:0.3rem" title="Data source provider">${escapeHtml(l.provider === "pricing_engine" ? "Simulated estimate" : l.provider)}</span>
              <strong>${escapeHtml(l.origin)} → ${escapeHtml(l.destination)}</strong>
              <span>(${escapeHtml(l.departure_date)})</span>
              <span class="cabin-tag ${escapeHtml(l.cabin)}">${escapeHtml(formatCabinName(l.cabin))}</span>
            </div>
            <div>
              ${escapeHtml(l.airline_name)} (${escapeHtml(l.flight_numbers.join(", "))}) · ${l.duration_hours}h ·
              ${l.stops_count === 0 ? "Nonstop" : `${l.stops_count} stop (${escapeHtml(l.layover_airports.join(","))}${l.layover_hours ? ` · ${Number(l.layover_hours).toFixed(1)}h layover` : ""})`}
              ${l.from_cache ? ' <span title="Loaded from SQLite cache">⚡</span>' : ""}
            </div>
          </div>
        `
        )
        .join("");

      const gfUrl = getTicketGoogleFlightsUrl(t);
      return `
        <div class="ticket-card">
          <div class="ticket-card-header">
            <div>
              <strong>${escapeHtml(t.label)}</strong>
              <span class="badge-subtle" style="margin-left:0.4rem">${escapeHtml(t.airline_or_alliance)}</span>
            </div>
            <div>
              <strong>$${t.total_ticket_usd.toFixed(0)}</strong>
              <span class="price-sub">(Fare $${t.base_fare_usd.toFixed(0)} + Bags $${t.baggage_fees_usd.toFixed(0)})</span>
            </div>
          </div>
          <div style="font-size:0.78rem; color:#475569; margin-bottom:0.35rem;">${escapeHtml(t.pricing_note)}</div>
          ${legsRows}
          <div class="booking-cmd">
            <span>📋 <strong>How to book:</strong> <a href="${escapeHtml(gfUrl)}" target="_blank" rel="noopener noreferrer" class="booking-query-link">${escapeHtml(t.booking_query_summary)}</a></span>
            <a href="${escapeHtml(gfUrl)}" target="_blank" rel="noopener noreferrer" class="btn-gf-book">
              ✈️ Open in Google Flights ↗
            </a>
          </div>
        </div>
      `;
    })
    .join("");

  const visitsHtml = activeItin.stop_visits
    .map(
      (v) =>
        `<span class="leg-preview-pill">🏙️ <strong>${escapeHtml(v.label)}</strong> (${escapeHtml(v.arrival_airport)}): ${escapeHtml(v.arrival_date)} → ${escapeHtml(v.departure_date)} (${v.nights}n)</span>`
    )
    .join("");

  container.innerHTML = `
    ${warningsHtml}

    <!-- Strategy Comparison Table -->
    <div class="card">
      <div class="card-header" style="margin-bottom:0.6rem">
        <div>
          <h2>Ticket Strategy Comparison (1 Ticket vs. Multi-Ticket vs. Hub Split)</h2>
          <p class="card-hint">
            Evaluated ${data.schedules_evaluated} date/order schedules &amp; ${data.ticket_partitions_evaluated} ticket combinations. Click any strategy below to inspect its exact tickets.
          </p>
        </div>
      </div>
      <div class="comparison-table-wrap">
        <table class="comparison-table">
          <thead>
            <tr>
              <th>Ticket Partition Strategy</th>
              <th>Total Cost</th>
              <th>vs. 1 Ticket</th>
              <th>Travel Time</th>
              <th>Tickets</th>
              <th>Transfers</th>
            </tr>
          </thead>
          <tbody>
            ${strategyRowsHtml}
          </tbody>
        </table>
      </div>
    </div>

    <!-- Selected Itinerary Deep Dive -->
    <div class="itinerary-hero">
      <div class="badge-row">
        ${(activeItin.badges || []).map((b) => `<span class="award-badge">${escapeHtml(b)}</span>`).join("")}
      </div>
      <div class="hero-top">
        <div>
          <h2 style="margin:0 0 0.25rem">${escapeHtml(activeItin.strategy_label)}</h2>
          <div style="font-size:0.88rem; font-weight:600; color:#1e40af">${escapeHtml(activeItin.route_summary)}</div>
          <p class="card-hint">${escapeHtml(activeItin.strategy_description)}</p>
        </div>
        <div class="price-block">
          <div class="price-big">$${activeItin.total_price_usd.toFixed(0)}</div>
          <div class="price-sub">
            Base $${activeItin.total_base_fare_usd.toFixed(0)} + Bags $${activeItin.total_baggage_fees_usd.toFixed(0)}
          </div>
        </div>
      </div>

      <div class="metrics-strip">
        <div class="metric-tile">
          <span>Total Travel Time</span>
          <strong>${activeItin.total_travel_hours} hrs</strong>
        </div>
        <div class="metric-tile">
          <span>Tickets to Book</span>
          <strong>${activeItin.tickets.length} PNR${activeItin.tickets.length > 1 ? "s" : ""}</strong>
        </div>
        <div class="metric-tile">
          <span>Protected Stops</span>
          <strong>${activeItin.protected_transfers}</strong>
        </div>
        <div class="metric-tile">
          <span>Self-Transfers</span>
          <strong>${activeItin.self_transfers}${
            activeItin.min_self_transfer_buffer_hours
              ? ` (≥${activeItin.min_self_transfer_buffer_hours}h)`
              : ""
          }</strong>
        </div>
      </div>

      <div style="margin-bottom:0.65rem">
        <strong style="font-size:0.78rem; color:#475569">Scheduled City Stays:</strong>
        <div class="leg-preview-list">${visitsHtml}</div>
      </div>

      <ul style="margin:0.5rem 0 0.85rem; padding-left:1.2rem; font-size:0.81rem; color:#334155">
        ${(activeItin.explanation_bullets || []).map((b) => `<li>${escapeHtml(b)}</li>`).join("")}
      </ul>

      <h3 style="margin:0.5rem 0 0.35rem; font-size:0.92rem">Ticket Breakdown (${activeItin.tickets.length} Separate Booking${activeItin.tickets.length > 1 ? "s" : ""})</h3>
      <div class="ticket-list">
        ${ticketsHtml}
      </div>
    </div>
  `;

  container.querySelectorAll("tr[data-itin-id]").forEach((row) => {
    row.addEventListener("click", () => {
      selectedItineraryId = row.getAttribute("data-itin-id");
      renderBuilder();
      renderOptimizationResults(currentOptimizationResponse);
    });
  });
}

/* --- Initialize Event Listeners --- */
async function initApp() {
  await loadAirportsCatalog();

  const toggleWeightsBtn = document.getElementById("toggleWeightsBtn");
  if (toggleWeightsBtn) {
    toggleWeightsBtn.addEventListener("click", () => {
      document.getElementById("weightsDrawer").classList.toggle("hidden");
    });
  }

  document.getElementById("sameAsOriginToggle").addEventListener("change", (e) => {
    state.same_as_origin = e.target.checked;
    onStateMutated();
  });

  document.getElementById("earliestDepartureInput").addEventListener("change", (e) => {
    state.earliest_departure = e.target.value;
    onStateMutated();
  });

  document.getElementById("latestReturnInput").addEventListener("change", (e) => {
    state.latest_return = e.target.value;
    onStateMutated();
  });

  document.getElementById("orderingModeSelect").addEventListener("change", (e) => {
    state.ordering_mode = e.target.value;
    onStateMutated();
  });

  document.getElementById("addStopBtn").addEventListener("click", () => {
    const fallbackPool = [
      { label: "Amsterdam", airports: ["AMS", "EIN"] },
      { label: "Barcelona", airports: ["BCN", "GRO"] },
      { label: "Zurich", airports: ["ZRH", "BSL"] },
      { label: "Seoul", airports: ["ICN", "GMP"] },
      { label: "Singapore", airports: ["SIN"] },
    ];
    const pick = fallbackPool[state.stops.length % fallbackPool.length];
    state.stops.push({
      id: `stop-${Date.now()}`,
      label: pick.label,
      airports: [...pick.airports],
      earliest_arrival: state.earliest_departure,
      latest_departure: state.latest_return,
      min_nights: 3,
      max_nights: 5,
      fixed_order: false,
      outbound_cabin: "auto",
      outbound_stops: "auto",
    });
    onStateMutated();
  });

  // Baggage & Cabin & Stops & Sliders
  document.getElementById("includeCarryOnCheck").addEventListener("change", (e) => {
    state.baggage.include_carry_on = e.target.checked;
    onStateMutated();
  });

  document.getElementById("checkedBagsCountSelect").addEventListener("change", (e) => {
    state.baggage.checked_bags = parseInt(e.target.value, 10) || 0;
    onStateMutated();
  });

  document.getElementById("defaultCabinSelect").addEventListener("change", (e) => {
    state.cabin_policy.default_cabin = e.target.value;
    onStateMutated();
  });

  document.getElementById("longHaulCabinSelect").addEventListener("change", (e) => {
    state.cabin_policy.long_haul_cabin = e.target.value;
    onStateMutated();
  });

  document.getElementById("longHaulThresholdInput").addEventListener("change", (e) => {
    const val = parseFloat(e.target.value);
    if (!isNaN(val) && val >= 1) {
      state.cabin_policy.long_haul_threshold_hours = val;
      onStateMutated();
    }
  });

  const shortHaulStopsEl = document.getElementById("shortHaulStopsSelect");
  if (shortHaulStopsEl) {
    shortHaulStopsEl.addEventListener("change", (e) => {
      state.stops_policy.short_haul_stops = e.target.value;
      onStateMutated();
    });
  }

  const longHaulStopsEl = document.getElementById("longHaulStopsSelect");
  if (longHaulStopsEl) {
    longHaulStopsEl.addEventListener("change", (e) => {
      state.stops_policy.long_haul_stops = e.target.value;
      onStateMutated();
    });
  }

  const nonstopThresholdEl = document.getElementById("nonstopThresholdInput");
  if (nonstopThresholdEl) {
    nonstopThresholdEl.addEventListener("change", (e) => {
      const val = parseFloat(e.target.value);
      if (!isNaN(val) && val >= 0.5) {
        state.stops_policy.nonstop_threshold_hours = val;
        onStateMutated();
      }
    });
  }

  const maxLayoverHoursEl = document.getElementById("maxLayoverHoursInput");
  if (maxLayoverHoursEl) {
    maxLayoverHoursEl.addEventListener("change", (e) => {
      const val = parseFloat(e.target.value);
      if (!isNaN(val) && val >= 1.0) {
        state.stops_policy.max_layover_hours = Math.min(24.0, val);
        onStateMutated();
      }
    });
  }

  document.getElementById("valueOfTimeInput").addEventListener("input", (e) => {
    state.weights.value_of_time_per_hour = parseFloat(e.target.value);
    document.getElementById("valueOfTimeLabel").textContent = `$${state.weights.value_of_time_per_hour} / hr`;
  });
  document.getElementById("valueOfTimeInput").addEventListener("change", () => {
    setResultsStale(true);
    saveStateToCookieAndStorage();
  });

  document.getElementById("protectedTransferInput").addEventListener("input", (e) => {
    state.weights.protected_transfer_penalty = parseFloat(e.target.value);
    document.getElementById("protectedTransferLabel").textContent = `$${state.weights.protected_transfer_penalty} / stop`;
  });
  document.getElementById("protectedTransferInput").addEventListener("change", () => {
    setResultsStale(true);
    saveStateToCookieAndStorage();
  });

  document.getElementById("selfTransferInput").addEventListener("input", (e) => {
    state.weights.self_transfer_penalty = parseFloat(e.target.value);
    document.getElementById("selfTransferLabel").textContent = `$${state.weights.self_transfer_penalty} / split`;
  });
  document.getElementById("selfTransferInput").addEventListener("change", () => {
    setResultsStale(true);
    saveStateToCookieAndStorage();
  });

  document.getElementById("enableHubSplittingCheck").addEventListener("change", (e) => {
    state.weights.enable_hub_splitting = e.target.checked;
    onStateMutated();
  });
  document.getElementById("simulationToggle").addEventListener("change", (e) => {
    state.provider_mode = testingMode && e.target.checked ? "offline" : "auto";
    onStateMutated();
  });

  const provSelect = document.getElementById("providerModeSelect");
  if (provSelect) {
    provSelect.addEventListener("change", (e) => {
      state.provider_mode = e.target.value;
      onStateMutated();
    });
  }

  const maxApiInput = document.getElementById("maxApiCallsInput");
  if (maxApiInput) {
    maxApiInput.addEventListener("change", (e) => {
      const val = parseInt(e.target.value, 10);
      if (!isNaN(val) && val >= 1) {
        state.max_api_calls_per_run = Math.min(250, val);
        onStateMutated();
      }
    });
  }

  // Preset & Reset
  document.getElementById("presetSelect").addEventListener("change", (e) => {
    const key = e.target.value;
    if (key && PRESETS[key]) {
      const prevMode = state.provider_mode || "auto";
      state = structuredClone(PRESETS[key]);
      state.provider_mode = prevMode;
      onStateMutated();
    }
    e.target.value = "";
  });

  document.getElementById("resetDefaultsBtn").addEventListener("click", () => {
    const prevMode = state.provider_mode || "auto";
    state = structuredClone(PRESETS.greece_london);
    state.provider_mode = prevMode;
    onStateMutated();
  });

  document.getElementById("clearCacheBtn").addEventListener("click", async () => {
    const resp = await fetch("/api/cache/clear", { method: "POST" });
    const stats = await resp.json();
    updateCacheStatusUI(stats);
  });

  document.getElementById("optimizeBtn").addEventListener("click", () => {
    runOptimization();
  });

  try {
    const statusResp = await fetch("/api/provider-status");
    if (statusResp.ok) {
      const statusData = await statusResp.json();
      testingMode = statusData.testing_mode === true;
      updateCacheStatusUI(statusData.cache_stats);
    }
  } catch (_err) {
    // Ignore status fetch error on init
  }
  document.getElementById("simulationControl").classList.toggle("hidden", !testingMode);
  renderBuilder();
}

document.addEventListener("DOMContentLoaded", initApp);
