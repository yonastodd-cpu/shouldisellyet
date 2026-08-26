// ShouldISellYet — purchase-time on-demand market pull.
//
// WHAT THIS IS. The 17,874 provisioned-but-unreleased ZIPs show the
// rebuilding notice and, until now, could not be sold a report: the
// pre-charge coverage check only knew "we have a record file", not "we have
// data". This function makes any US ZIP purchasable: the checkout page calls
// it BEFORE handing the buyer to Stripe, it pulls fresh market data for the
// ZIP if the private store doesn't already hold it, validates the same
// data-quality floor the live pages use, and only then does the client
// proceed to payment. FAIL → the buyer is told plainly and never charged,
// because the Stripe redirect simply does not happen.
//
// ORDER OF OPERATIONS (each step gates the next; tests pin the order):
//   1. shape-check the ZIP; rate-limit per IP
//   2. STORE FIRST (dedupe): a ZIP with usable stored data answers from the
//      store at zero marginal cost — a pulled ZIP is live for a month, and
//      subsequent buyers in that window must not buy the data twice
//   3. ceiling: count this month's vendor calls in public.ondemand_pulls
//      against ONDEMAND_MONTHLY_CEILING — at the ceiling the answer is
//      "at capacity", never a silent overage
//   4. ONE /markets call (historyRange=12 — the year-over-year comparison
//      rides in the same response and is never bought again)
//   5. validate: the same floor verdict_v2 applies — at least MIN_KNOWN of
//      the three year-over-year signals computable, and a datable payload
//   6. store: market_stats (+raw_json) / market_history / zip_readings /
//      zip_release — the same private-store shape the batch loader writes,
//      so the pulled ZIP IS a live ZIP from this moment
//
// THE READING IS COMPUTED HERE, in a mirror of pipeline/verdict_v2.py's
// engine. Deno cannot import Python, so the SPEC constants below are a
// MIRROR, pinned by pipeline/test_ondemand_pull_fn.py the same way the
// figures switch pins its four copies. Recalibrating verdict_v2 means
// editing this block AND redeploying this function.
//
// RAW_JSON GOES IN, NEVER OUT. This function WRITES the vendor payload into
// the private store (that is the acquisition step, same as the batch
// loader); no select here reads raw_json back and the response body carries
// only ok/reason/our own reading word. The republication boundary stays
// market-reading.
//
// Deploy as edge function `ondemand-pull`. Disable "Enforce JWT verification".
// Secrets: RENTCAST_API_KEY (required for live pulls — unset degrades to
// "at capacity", which sells nothing rather than something unfulfillable),
// ONDEMAND_MONTHLY_CEILING (optional, default below).
//
// POST { zip }
//   200 { ok: true,  served: "store" | "pull" }
//   200 { ok: false, reason: "no_data" | "at_capacity" | "error" | "disabled" }

import { rateAllowed } from "../_shared/ratelimit.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const RENTCAST_KEY = Deno.env.get("RENTCAST_API_KEY") ?? "";

// ═══ ONDEMAND_ENABLED — mirror of pipeline/ondemand_switch.py ═══
// A module literal, not an env read, for the reason velocity_switch.py gives:
// a flag whose copies are set three different ways is a flag that gets
// flipped in two of them. pipeline/test_ondemand_switch.py pins every copy.
export const ONDEMAND_ENABLED = true;

// Hard monthly ceiling on vendor calls (every row in ondemand_pulls is one
// paid call, any status). The default is deliberately conservative — set
// ONDEMAND_MONTHLY_CEILING in the function's secrets to raise it, sized as
// (remaining included quota − the scheduled refresh budget) for the month.
const DEFAULT_CEILING = 150;
function ceiling(): number {
  const v = parseInt(Deno.env.get("ONDEMAND_MONTHLY_CEILING") ?? "", 10);
  return Number.isFinite(v) && v > 0 ? v : DEFAULT_CEILING;
}

// A pulled ZIP is live for a month; inside that window later buyers are
// served from the store. 32 days, not 30: a monthly refresh cadence plus
// slack must not reopen the vendor call two days early.
const FRESH_DAYS = 32;

// ═══ SPEC mirror — pipeline/verdict_v2.SPEC, the scoring half ═══
// Same names, same values; the pinning test parses both files.
const SPEC = {
  basis: "active listings",
  price_fast: -0.05,
  price_slow: -0.02,
  dom_stretch: 0.10,
  inventory_surge: 0.30,
  red: 3,
  yellow: 1,
  price_surge: 0.05,
  dom_shrink: -0.20,
  inventory_drop: -0.15,
  strong_min: 3,
  min_known: 2,
};

const ALLOWED_ORIGINS = new Set([
  "https://shouldisellyet.com",
  "https://www.shouldisellyet.com",
  "http://localhost:5177",
  "http://localhost:5178",
]);

function corsFor(req: Request) {
  const origin = req.headers.get("origin") ?? "";
  return {
    "Access-Control-Allow-Origin":
      ALLOWED_ORIGINS.has(origin) ? origin : "https://shouldisellyet.com",
    "Access-Control-Allow-Methods": "POST, OPTIONS",
    "Access-Control-Allow-Headers": "content-type",
    "Vary": "Origin",
  };
}

function json(body: unknown, cors: Record<string, string>, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", "Cache-Control": "no-store", ...cors },
  });
}

async function rest(path: string, init?: RequestInit) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    ...init,
    headers: {
      apikey: SERVICE_KEY,
      Authorization: `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
      ...(init?.method && init.method !== "GET" ? { Prefer: "resolution=merge-duplicates,return=minimal" } : {}),
      ...((init?.headers as Record<string, string>) ?? {}),
    },
  });
  return r;
}

// Best-effort demand-table row for pull failures — coverage-gap data points.
// The id is server-random here (no tab to correlate with).
async function logDemand(zip: string, outcome: "pull_failed" | "pull_capacity") {
  try {
    await rest("zip_lookups", {
      method: "POST",
      headers: { Prefer: "return=minimal" },
      body: JSON.stringify({
        id: crypto.randomUUID(),
        zip, outcome,
        ts: new Date(Math.floor(Date.now() / 3600000) * 3600000).toISOString(),
      }),
    });
  } catch { /* logging is optional; the answer is not */ }
}

async function recordPull(zip: string, status: "pulled" | "no_data" | "error") {
  try {
    await rest("ondemand_pulls", {
      method: "POST",
      headers: { Prefer: "return=minimal" },
      body: JSON.stringify({ zip, month: new Date().toISOString().slice(0, 7), status }),
    });
  } catch { /* the ledger insert failing must not orphan a paid call silently */ }
}

// ————— the verdict engine, mirrored (pipeline/verdict_v2.py) —————

type Num = number | null;

function yoy(now: Num, yearAgo: Num): Num {
  if (now == null || yearAgo == null || yearAgo <= 0) return null;
  return (now - yearAgo) / yearAgo;
}

function num(v: unknown): Num {
  return typeof v === "number" && isFinite(v) ? v : null;
}

interface MarketM {
  list_price_yoy: Num;
  active_dom: Num;
  active_dom_yoy: Num;
  listings_yoy: Num;
  total_listings: Num;
}

function evaluate(m: MarketM) {
  const known = [m.list_price_yoy, m.active_dom_yoy, m.listings_yoy]
    .filter((v) => v != null).length;
  if (known < SPEC.min_known) {
    return { level: "green", score: 0, reasons: [["insufficient_data", 0, known]], known };
  }
  const flags: [string, number, number][] = [];
  if (m.list_price_yoy != null) {
    if (m.list_price_yoy < SPEC.price_fast) flags.push(["price_falling_fast", 3, m.list_price_yoy]);
    else if (m.list_price_yoy < SPEC.price_slow) flags.push(["price_falling", 2, m.list_price_yoy]);
  }
  if (m.active_dom_yoy != null && m.active_dom_yoy > SPEC.dom_stretch) {
    flags.push(["dom_stretching", 1, m.active_dom_yoy]);
  }
  if (m.listings_yoy != null && m.listings_yoy > SPEC.inventory_surge) {
    flags.push(["inventory_surge", 1, m.listings_yoy]);
  }
  const score = flags.reduce((a, [, p]) => a + p, 0);
  if (!flags.length) {
    const strong: [string, number, number][] = [];
    if (m.list_price_yoy != null && m.list_price_yoy >= SPEC.price_surge) strong.push(["prices_surging", 0, m.list_price_yoy]);
    if (m.active_dom_yoy != null && m.active_dom_yoy <= SPEC.dom_shrink) strong.push(["homes_selling_fast", 0, m.active_dom_yoy]);
    if (m.listings_yoy != null && m.listings_yoy <= SPEC.inventory_drop) strong.push(["inventory_tightening", 0, m.listings_yoy]);
    if (strong.length >= SPEC.strong_min) return { level: "strong", score: 0, reasons: strong, known };
  }
  const level = score >= SPEC.red ? "red" : score >= SPEC.yellow ? "yellow" : "green";
  const rounded = flags.map(([c, p, v]) => [c, p, Math.round(v * 10000) / 10000]);
  return { level, score, reasons: rounded, known };
}

// ————— payload parsing, mirrored (fetch_rentcast.parse_market /
//        load_market_stats.month_of + history_rows) —————

function parsePayload(obj: Record<string, unknown>) {
  const sale = (obj?.saleData ?? {}) as Record<string, unknown>;
  const hist = (sale?.history ?? {}) as Record<string, Record<string, unknown>>;
  const months = Object.keys(hist).sort();
  // The vendor's own date, then the newest history month — never the clock.
  const asOfRaw = String(sale?.lastUpdatedDate ?? "").slice(0, 7);
  const asOf = /^\d{4}-\d{2}$/.test(asOfRaw) ? asOfRaw
    : (months.length && /^\d{4}-\d{2}$/.test(months[months.length - 1]) ? months[months.length - 1] : null);
  // verdict_v2.from_market_stats: months[-13] when 13+ months, else the
  // oldest month when 12+, else no comparison at all.
  const prior = months.length >= 13 ? hist[months[months.length - 13]]
    : months.length >= 12 ? hist[months[0]] : null;
  const then = (k: string) => num(prior?.[k]);
  const m: MarketM = {
    list_price_yoy: yoy(num(sale.medianPrice), then("medianPrice")),
    active_dom: num(sale.averageDaysOnMarket),
    active_dom_yoy: yoy(num(sale.averageDaysOnMarket), then("averageDaysOnMarket")),
    listings_yoy: yoy(num(sale.totalListings), then("totalListings")),
    total_listings: num(sale.totalListings),
  };
  return { sale, hist, months, asOf, m };
}

Deno.serve(async (req) => {
  const cors = corsFor(req);
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });
  if (req.method !== "POST") return json({ ok: false, reason: "error" }, cors, 405);

  if (!ONDEMAND_ENABLED) return json({ ok: false, reason: "disabled" }, cors);

  let body: Record<string, unknown>;
  try { body = await req.json(); } catch { return json({ ok: false, reason: "error" }, cors, 400); }

  const zip = String(body.zip ?? "");
  if (!/^\d{5}$/.test(zip)) return json({ ok: false, reason: "error" }, cors, 400);

  // Layer 2: per-IP. 10/hour covers a real buyer re-checking a couple of
  // ZIPs; the vendor-call path below carries its own tighter cap so the
  // PRE-PAYMENT pull cannot be farmed by iterating ZIPs from one address.
  if (!await rateAllowed(req, "ondemand", 10, 3600)) {
    return json({ ok: false, reason: "error" }, cors, 429);
  }

  try {
    // ————— 2. STORE FIRST — the checkout path checks the private store
    // BEFORE any vendor call. A released ZIP, or one pulled within the
    // freshness window, answers here at zero marginal cost.
    const [relRows, statRows] = await Promise.all([
      rest(`zip_release?zip=eq.${zip}&select=zip,basis&limit=1`).then((r) => r.ok ? r.json() : []),
      rest(`market_stats?zip=eq.${zip}&select=zip,retrieved_at&order=as_of_month.desc&limit=1`)
        .then((r) => r.ok ? r.json() : []),
    ]);
    const released = Array.isArray(relRows) && relRows.length > 0;
    const stat = Array.isArray(statRows) && statRows.length ? statRows[0] : null;
    const fresh = stat && (Date.now() - Date.parse(stat.retrieved_at)) < FRESH_DAYS * 86400000;

    if (stat && (released || fresh)) {
      // Data exists and is servable. Heal a missing release row (a pull whose
      // release insert failed) so the API serves what the store holds.
      if (!released) {
        await rest("zip_release?on_conflict=zip", {
          method: "POST",
          headers: { Prefer: "resolution=ignore-duplicates,return=minimal" },
          body: JSON.stringify([{ zip, tranche: "ondemand", basis: SPEC.basis }]),
        });
      }
      return json({ ok: true, served: "store" }, cors);
    }

    // ————— 3. ceiling — counted in the database, never assumed. Every row
    // is one paid vendor call regardless of status.
    const month = new Date().toISOString().slice(0, 7);
    const cr = await rest(`ondemand_pulls?month=eq.${month}&select=id`, {
      headers: { Prefer: "count=exact", Range: "0-0" },
    });
    const range = cr.headers.get("content-range") ?? "";
    const used = parseInt(range.split("/")[1] ?? "", 10);
    if (!Number.isFinite(used)) {
      // Can't prove we're under the ceiling → don't spend. "At capacity" is
      // the honest degrade; a silent overage is the one forbidden outcome.
      await logDemand(zip, "pull_capacity");
      return json({ ok: false, reason: "at_capacity" }, cors);
    }
    if (used >= ceiling() || !RENTCAST_KEY) {
      await logDemand(zip, "pull_capacity");
      return json({ ok: false, reason: "at_capacity" }, cors);
    }

    // Tighter farm-guard on the path that actually spends money: 3 vendor
    // pulls per IP per hour. A buyer needs exactly one.
    if (!await rateAllowed(req, "ondemand-pull", 3, 3600)) {
      return json({ ok: false, reason: "error" }, cors, 429);
    }

    // ————— 4. one /markets call —————
    const q = new URLSearchParams({ zipCode: zip, dataType: "All", historyRange: "12" });
    const vr = await fetch(`https://api.rentcast.io/v1/markets?${q}`, {
      headers: { "X-Api-Key": RENTCAST_KEY, "Accept": "application/json" },
    });
    if (vr.status === 404) {
      // A real answer: the vendor has no market data for this ZIP.
      await recordPull(zip, "no_data");
      await logDemand(zip, "pull_failed");
      return json({ ok: false, reason: "no_data" }, cors);
    }
    if (!vr.ok) {
      await recordPull(zip, "error");
      return json({ ok: false, reason: "error" }, cors);
    }
    const payload = await vr.json();
    const retrievedAt = new Date().toISOString();

    // ————— 5. validate — the same floor the live pages hold. Below
    // min_known the site renders "not enough recent data" and refuses a
    // rating, so selling a report on it would be selling the refusal.
    const { hist, months, asOf, m } = parsePayload(payload ?? {});
    const verdict = evaluate(m);
    if (!asOf || verdict.known < SPEC.min_known) {
      await recordPull(zip, "no_data");
      await logDemand(zip, "pull_failed");
      return json({ ok: false, reason: "no_data" }, cors);
    }

    // ————— 6. store — same rows the batch loader writes, so downstream
    // (market-reading, the monthly refresh, the weekly promotion sweep)
    // cannot tell an on-demand ZIP from a tranche ZIP.
    const sale = (payload?.saleData ?? {}) as Record<string, unknown>;
    const statRow = {
      zip, as_of_month: asOf, source: "rentcast", retrieved_at: retrievedAt,
      list_median_price: num(sale.medianPrice),
      list_average_price: num(sale.averagePrice),
      list_median_ppsf: num(sale.medianPricePerSquareFoot),
      active_dom: num(sale.averageDaysOnMarket),
      total_listings: num(sale.totalListings),
      new_listings: num(sale.newListings),
      history_months: months.length,
      raw_json: payload,
    };
    const histRows = months.slice(-12).flatMap((mo) => {
      const rec = hist[mo] ?? {};
      const price = num(rec.medianPrice);
      if (price == null) return [];   // a gap is honest, a zero is not
      return [{
        zip, source: "rentcast", as_of_month: mo,
        median_list_price: price,
        active_dom: num(rec.averageDaysOnMarket),
        total_listings: num(rec.totalListings),
      }];
    });

    const writes = [
      rest("market_stats?on_conflict=zip,as_of_month,source", {
        method: "POST", body: JSON.stringify([statRow]),
      }),
      histRows.length ? rest("market_history?on_conflict=zip,source,as_of_month", {
        method: "POST", body: JSON.stringify(histRows),
      }) : Promise.resolve(new Response(null, { status: 204 })),
      rest("zip_readings?on_conflict=zip,source", {
        method: "POST",
        body: JSON.stringify([{
          zip, source: "rentcast",
          level: verdict.level, score: verdict.score, reasons: verdict.reasons,
          basis: SPEC.basis, as_of_month: asOf, computed_at: retrievedAt,
        }]),
      }),
      // ignore-duplicates: never relabel a tranche ZIP's release row.
      rest("zip_release?on_conflict=zip", {
        method: "POST",
        headers: { Prefer: "resolution=ignore-duplicates,return=minimal" },
        body: JSON.stringify([{ zip, tranche: "ondemand", basis: SPEC.basis }]),
      }),
    ];
    const results = await Promise.all(writes);
    await recordPull(zip, "pulled");
    if (!results[0].ok) {
      // The one write that matters most failed: the data was bought but not
      // kept. Answer honestly — a charge against unstored data cannot be
      // refreshed or re-served.
      return json({ ok: false, reason: "error" }, cors);
    }
    return json({ ok: true, served: "pull" }, cors);
  } catch (_e) {
    // Never echo the failure — vendor and REST errors carry detail that is
    // not the caller's business.
    return json({ ok: false, reason: "error" }, cors);
  }
});
