// ShouldISellYet — serve ONE ZIP's reading.
//
// Deploy as edge function `market-reading`. Disable "Enforce JWT verification".
// No extra secrets: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are auto-injected.
//
// GET /market-reading?zip=NNNNN
//   200 { zip, state, reading, asOf, lastUpdated, metrics, priceHistory, dataStatus }
//   200 { …, metrics: {}, priceHistory: [], figuresWithheld: true, notice }
//        when FIGURES_OFF — see the kill-switch block below
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
// The boundary decides WHICH fields may be served. FIGURES_OFF below decides
// WHETHER the market figures among them may be served at all. Two questions,
// two mechanisms; neither is a substitute for the other.
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

// ═══ WHY THIS IS AN ENDPOINT AND NOT A FILE ═══
//
// The vendor's licence permits displaying their statistics; what it does not
// clearly permit is redistributing them as a dataset. Those are not different
// data — they are different SERVING MODELS, and the difference is what this
// function exists to make true.
//
// The site used to ship web/data/z/{zip}.json: 5,000 files named by ZIP code,
// each carrying current metrics and a twelve-month history — roughly 120,000
// raw monthly vendor values, downloadable without authentication and
// collectable by iterating five digits. Every property of that arrangement
// said "dataset": bulk, enumerable, unauthenticated, complete, and served
// whether or not anyone was looking at the page it belonged to.
//
// Serving one ZIP per request, rate-limited, from an origin-pinned endpoint
// does not make scraping impossible and is not meant to. It makes the thing we
// operate a page-display service rather than a distribution channel — which is
// the distinction the licence question turns on. Someone determined can still
// collect it; the point is that we are not the ones handing it out.
//
// Keep it that way: one zip per request, no list form, no wildcard, no index,
// named columns only, and never raw_json.
//
// Static allowlist, not reflection — see verify-access for why a reflected
// origin is unsafe across concurrent requests in one isolate. The localhost
// entries are what let the build's own browser gate exercise this path; a gate
// that cannot reach the endpoint cannot prove the pages still render.
const ALLOWED_ORIGINS = new Set([
  "https://shouldisellyet.com",
  "http://localhost:5177",
  "http://localhost:5178",
  "http://127.0.0.1:5177",
  "http://127.0.0.1:5178",
]);

function corsFor(req: Request) {
  const origin = req.headers.get("origin") ?? "";
  return {
    "Access-Control-Allow-Origin":
      ALLOWED_ORIGINS.has(origin) ? origin : "https://shouldisellyet.com",
    "Access-Control-Allow-Methods": "GET, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, apikey, content-type",
    "Vary": "Origin",
  };
}

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

// ═══ FIGURES_KILL_SWITCH — THE COPY THAT LIVES ON THE SERVER ═══
//
// Mirrors FIGURES_OFF in pipeline/figures_switch.py. Read that module for what
// counts as a figure and why the reading word is not one; this comment is only
// about why the value is duplicated here and what that obliges.
//
// THE TWO MUST MOVE TOGETHER. Deno cannot import Python, and a build-time
// literal cannot reach a running server, so the flag cannot be SHARED — it can
// only be MIRRORED. Four copies now carry one decision:
//
//   pipeline/figures_switch.py   the builders (static ZIP pages, stubs, cards)
//   web/index.html               the homepage checker
//   web/market-render.js         both report surfaces
//   this file                    the live per-ZIP endpoint
//
// pipeline/test_figures_switch.py pins the first three to each other and
// pipeline/test_figures_switch_endpoint.py pins this one to the Python flag,
// because four copies of a decision is fine and four copies that can DIVERGE
// is not. Flipping the switch means editing all four AND DEPLOYING THIS
// FUNCTION: the other three take effect on the next build, this one takes
// effect only when the function itself ships. That asymmetry is the whole
// reason the gap existed — the static pages stopped drawing dials while this
// endpoint went on serving the same numbers as named columns to any browser.
//
//   false  current behaviour, unchanged. The default, so nothing moves until
//          somebody moves it.
//   true   the response keeps zip, reading, asOf, lastUpdated and dataStatus
//          and carries no market figure at all: no metrics block, no price
//          history, and nothing fetched to build either.
export const FIGURES_OFF = false;

// Verbatim figures_switch.WITHHELD_LINE. Vendor-neutral for the reason the
// pause notice is: a surface that has stopped showing a source is not the
// place to name it.
//
// It is a SEPARATE field rather than a dataStatus value. dataStatus stays "ok"
// because the reading is ok — a client that cannot tell "withheld" from
// "insufficient_data" paints the rebuilding notice over a perfectly good
// reading, and overloading one status would make every consumer's switch mean
// two different things at once.
const WITHHELD_LINE = "Market figures are not being shown for this reading.";

// cors is PASSED IN, never read from module scope. One isolate serves
// concurrent requests from different origins, and a shared mutable header
// object is how one caller's origin ends up on another caller's response.
function json(body: unknown, cors: Record<string, string>,
              status = 200, cache = false) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      ...(cache ? { "Cache-Control": CACHE } : { "Cache-Control": "no-store" }),
      ...cors,
    },
  });
}

// Year-over-year from the twelve-month series: newest against oldest. The
// pipeline computes the same ratios the same way (verdict_v2.from_market_stats),
// and a page must not be able to tell which produced the number it is showing.
function yoy(hist: Record<string, unknown>[], s: Record<string, unknown>) {
  const num = (v: unknown) => (typeof v === "number" ? v : v == null ? null : Number(v));
  const first = hist.length ? hist[0] : null;
  const ratio = (now: number | null, then: number | null) =>
    now == null || then == null || then === 0 ? null : (now - then) / then;

  const domNow = num(s.active_dom);
  const domThen = first ? num(first.active_dom) : null;
  const out: Record<string, number> = {};
  const set = (k: string, v: number | null) => { if (v != null && isFinite(v)) out[k] = v; };

  set("spy", ratio(num(s.list_median_price), first ? num(first.median_list_price) : null));
  set("dom", domNow);
  set("domy", domNow != null && domThen != null ? domNow - domThen : null);
  set("inv", num(s.total_listings));
  set("invy", ratio(num(s.total_listings), first ? num(first.total_listings) : null));
  return out;
}

// figures_switch.metrics() and .history(), in TypeScript. The withheld value
// is the EMPTY value the two no-reading paths below already return, not a new
// shape: every consumer renders {} metrics and an empty series today, because
// ~17,874 provisioned ZIPs have carried exactly that since the pause. Routing
// the figures through here means the switched-on path is one the clients
// exercise constantly, rather than a branch first executed by a stranger's
// browser on the day somebody flips the flag.
function metricsFor(hist: Record<string, unknown>[], s: Record<string, unknown>) {
  // Guarded here even though the history is empty by then, and that is not
  // belt-and-braces: two of the five figures — dom and inv — are read off the
  // CURRENT row and never touch the series at all. Delete this line and an
  // empty history still yields {"dom":57,"inv":105}, measured and served.
  // Withholding the history is not withholding the metrics.
  return FIGURES_OFF ? {} : yoy(hist, s);
}

function series(hist: Record<string, unknown>[]) {
  // A chart is the figure people forget. Twelve points show no digits on
  // screen and still publish twelve monthly vendor values — and they sit in
  // the network tab whether or not anything draws them.
  return FIGURES_OFF ? [] : hist.map((h: Record<string, unknown>) => ({
    month: h.as_of_month,
    medianListPrice: h.median_list_price,
    daysOnMarket: h.active_dom,
  }));
}

async function rest(path: string) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` },
  });
  if (!r.ok) throw new Error(`rest ${r.status}`);
  return await r.json();
}

Deno.serve(async (req) => {
  const cors = corsFor(req);
  if (req.method === "OPTIONS") return new Response("ok", { headers: cors });

  const zip = new URL(req.url).searchParams.get("zip") ?? "";
  if (!/^\d{5}$/.test(zip)) return json({ error: "bad zip" }, cors, 400);

  // Same layer-2 limiter every other public function uses. A per-ZIP endpoint
  // is enumerable by nature — 22,874 keys — so this is what stops the whole
  // dataset being walked one request at a time.
  // (req, scope, max, windowSeconds) — the window is REQUIRED; omitting it
  // passes undefined straight into the limiter's arithmetic.
  //
  // 120/hour rather than verify-access's 10/hour: this is the homepage's
  // primary interaction, not a payment-token check. A visitor comparing a few
  // ZIPs must not be throttled, while 22,874 keys still cannot be walked.
  if (!(await rateAllowed(req, "market-reading", 120, 3600))) {
    return json({ error: "slow down" }, cors, 429);
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
        cors, 200, true,
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
        cors, 200, true,
      );
    }
    const s = rows[0];

    // 3. Price history. From market_history (schema-v37), which the loader
    //    normalises out of the vendor payload at load time — NOT from
    //    raw_json. Reaching into the payload here would put it back inside the
    //    one place built to keep it out, and "only a slice" is how that stops
    //    meaning anything.
    //
    //    This returned exactly ONE point before v37, because market_stats
    //    holds one row per month and only the current month had been loaded.
    //    The contract promised twelve; the sparkline would have been a dot.
    //
    //    NOT FETCHED AT ALL when figures are withheld. The series exists only
    //    to become figures, so the query is skipped rather than the result
    //    dropped on the way out: the values never leave the database, and a
    //    logged query string is not evidence of a request that served them.
    const hist = FIGURES_OFF ? [] : await rest(
      `market_history?zip=eq.${zip}&select=as_of_month,median_list_price,` +
        `active_dom,total_listings&order=as_of_month.asc&limit=12`,
    );

    // 4. The reading word, for ZIPs scored at purchase time. Tranche ZIPs
    //    carry their word in the static record and have no row here — for
    //    them `reading` stays null and nothing changes. An on-demand ZIP's
    //    word lives in zip_readings (schema-v41, named columns: our own
    //    level/score/reason codes from verdict-methodology-v2, never the
    //    payload), which is what lets a pulled ZIP render before the next
    //    deploy provisions its static record.
    //
    //    Reason VALUES are figures — the vendor's measurement our rule fired
    //    on — so the kill switch strips them to bare codes, exactly as
    //    figures_switch.strip() does for the static records.
    const reads = await rest(
      `zip_readings?zip=eq.${zip}&select=level,score,reasons,basis&limit=1`,
    );
    const reading = reads.length
      ? {
        l: reads[0].level,
        s: reads[0].score,
        r: FIGURES_OFF
          ? (reads[0].reasons ?? []).map((x: unknown[]) => [x[0]])
          : reads[0].reasons ?? [],
        b: reads[0].basis,
      }
      : null;

    return json({
      zip: s.zip,
      state: null,
      reading,
      asOf: s.as_of_month,
      lastUpdated: s.retrieved_at,
      // EXACTLY WHAT A PAGE RENDERS, AND NOTHING ELSE.
      //
      // The three year-over-year figures are computed here rather than
      // shipped as two raw levels for the client to divide, because a
      // response carrying both endpoints of a series is a smaller dataset but
      // still a dataset. Price-per-sqft and new-listings year-over-year are
      // deliberately absent: no page displays them, and they were shipping in
      // the static files purely because the record shape happened to include
      // them.
      metrics: metricsFor(hist, s),
      priceHistory: series(hist),
      dataStatus: "ok",
      // Appended, never interleaved: with the switch off this spreads nothing
      // and the response is byte-for-byte what it was before the switch
      // existed, which is the property that lets the default stay untouched.
      ...(FIGURES_OFF ? { figuresWithheld: true, notice: WITHHELD_LINE } : {}),
      // Cache only what may be cached. A withheld response stored for a week
      // would outlive turning the switch back OFF; and note the reverse, which
      // no code here can fix — responses cached BEFORE a flip still carry
      // their figures for up to max-age plus the stale window, so throwing
      // this switch means purging the CDN, not only deploying the function.
    }, cors, 200, !FIGURES_OFF);
  } catch (_e) {
    // Never echo the error: a REST failure message can carry column names and
    // row fragments. A page that cannot reach us should render the notice, not
    // a stack trace.
    return json(
      { zip, state: null, reading: null, asOf: null, lastUpdated: null,
        metrics: {}, priceHistory: [], dataStatus: "pending_migration" },
      cors, 200, false,
    );
  }
});
