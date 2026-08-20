// ShouldISellYet — serve ONE ZIP's reading.
//
// Deploy as edge function `market-reading`. Disable "Enforce JWT verification".
// No extra secrets: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are auto-injected.
//
// GET /market-reading?zip=NNNNN
//   200 { zip, state, reading, asOf, lastUpdated, metrics, priceHistory, dataStatus }
//
// WHY THIS EXISTS. The browser used to fetch web/data/zips/{ST}.json — a whole
// state's records — to display one ZIP. While the site is paused those files
// carry nothing but {"st":"MD"}, but the moment Phase 4 releases a tranche
// they carry readings again, and a page that downloads 300 ZIPs to show one is
// republishing 299 of them to anyone watching the network tab. This endpoint
// is the per-ZIP replacement.
//
// ═══ THIS FUNCTION IS THE REPUBLICATION BOUNDARY ═══
//
// Every field below is named explicitly. There is no `select *`, and
// market_stats.raw_json — the untouched vendor payload — is never read, let
// alone returned. If a value is not in the SELECT list on line ~90 it cannot
// reach a reader, which is the property that makes this file the one place to
// audit when someone asks what we republish.
//
// dataStatus tells the page what kind of nothing it is looking at:
//   "ok"                 a released ZIP with a reading
//   "pending_migration"  a real ZIP whose tranche has not been released —
//                        renders the standard rebuilding notice
//   "insufficient_data"  released, but the market is too thin to read —
//                        renders an honest no-reading state, stays noindexed
//
// The released check is SERVER-SIDE and reads public.zip_release (schema-v36).
// It is never taken from the request: "may this ZIP be shown" is precisely the
// question a caller must not answer for us.

import { rateAllowed } from "../_shared/ratelimit.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// Static, matching every other function here — see verify-access for why a
// reflected origin is unsafe across concurrent requests in one isolate.
const CORS = {
  "Access-Control-Allow-Origin": "https://shouldisellyet.com",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
};

// A ZIP's reading changes at most monthly, and most of them will not change
// then either. Cache hard: this is 22,874 possible keys against a dataset that
// moves once a month, so the CDN should be doing almost all of the work.
// stale-while-revalidate keeps a tranche release from stampeding the origin.
const CACHE = "public, max-age=86400, stale-while-revalidate=604800";

function json(body: unknown, status = 200, cache = false) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(cache ? { "Cache-Control": CACHE } : { "Cache-Control": "no-store" }),
      ...CORS,
    },
  });
}

async function rest(path: string) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` },
  });
  if (!r.ok) throw new Error(`rest ${r.status}`);
  return await r.json();
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const zip = new URL(req.url).searchParams.get("zip") ?? "";
  if (!/^\d{5}$/.test(zip)) return json({ error: "bad zip" }, 400);

  // Same layer-2 limiter every other public function uses. A per-ZIP endpoint
  // is enumerable by nature — 22,874 keys — so this is what stops the whole
  // dataset being walked one request at a time.
  if (!(await rateAllowed(req, "market-reading", 120))) {
    return json({ error: "slow down" }, 429);
  }

  try {
    // 1. Is this ZIP released? Server-side, never from the caller.
    const rel = await rest(
      `zip_release?zip=eq.${zip}&select=zip,basis,released_at&limit=1`,
    );
    if (!rel.length) {
      // A real ZIP we simply are not publishing yet. Deliberately identical
      // for "not released" and "not a ZIP we cover" — the difference is not
      // the caller's business and telling them would map the release plan.
      return json(
        { zip, state: null, reading: null, asOf: null, lastUpdated: null,
          metrics: {}, priceHistory: [], dataStatus: "pending_migration" },
        200, true,
      );
    }

    // 2. The reading. Named fields only — raw_json is not in this list and
    //    must never be added to it.
    const rows = await rest(
      `market_stats?zip=eq.${zip}&select=zip,as_of_month,retrieved_at,` +
        `list_median_price,list_median_ppsf,active_dom,total_listings,` +
        `new_listings,history_months&order=as_of_month.desc&limit=1`,
    );
    if (!rows.length) {
      return json(
        { zip, state: null, reading: null, asOf: null, lastUpdated: null,
          metrics: {}, priceHistory: [], dataStatus: "insufficient_data" },
        200, true,
      );
    }
    const s = rows[0];

    // 3. Price history, already trimmed to what a sparkline needs. Twelve
    //    points of a median, not a series of measurements.
    const hist = await rest(
      `market_stats?zip=eq.${zip}&select=as_of_month,list_median_price` +
        `&order=as_of_month.asc&limit=12`,
    );

    return json({
      zip: s.zip,
      state: null,
      reading: null,          // filled by the reading engine once wired
      asOf: s.as_of_month,
      lastUpdated: s.retrieved_at,
      metrics: {
        medianListPrice: s.list_median_price,
        medianListPricePerSqFt: s.list_median_ppsf,
        daysOnMarket: s.active_dom,
        totalListings: s.total_listings,
        newListings: s.new_listings,
      },
      priceHistory: hist.map((h: Record<string, unknown>) => ({
        month: h.as_of_month,
        medianListPrice: h.list_median_price,
      })),
      dataStatus: "ok",
    }, 200, true);
  } catch (_e) {
    // Never echo the error: a REST failure message can carry column names and
    // row fragments. A page that cannot reach us should render the notice, not
    // a stack trace.
    return json(
      { zip, state: null, reading: null, asOf: null, lastUpdated: null,
        metrics: {}, priceHistory: [], dataStatus: "pending_migration" },
      200, false,
    );
  }
});
