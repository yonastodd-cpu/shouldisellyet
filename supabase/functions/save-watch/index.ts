// ShouldISellYet — save/clear one personal-number watch (walk-away / equity /
// lock-in cost threshold alert) against an existing subscriber. A subscriber
// can watch up to three metrics at once — one toggle per number on the
// report — so this upserts a single entry into the subscriber's `watches`
// array without touching any other metric's watch.
//
// The report page (my-report.html) calls this with the same access token
// verify-access already uses, plus the calculation inputs and the threshold
// the owner chose. This is the ONLY path that writes personal numbers to the
// database — the anon key used everywhere else on the site is insert-only
// (see schema.sql) and can never update an existing row, so this function
// runs with the service-role key after independently verifying the token.
//
// Deploy as edge function `save-watch`. Disable "Enforce JWT verification".
// No secrets needed — SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are auto-injected.
// Requires schema-v4.sql (adds calc_inputs / watches columns).
//
// POST /save-watch
//   Save/update one metric's watch:
//     { token, calcInputs, metric, direction, threshold }
//   Clear one metric's watch (others untouched):
//     { token, metric, clear: true }
//   200 { ok: true, watches: [...] }
//   200 { ok: false, error }

import { rateAllowed } from "../_shared/ratelimit.ts";
import { turnstileOk } from "../_shared/turnstile.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// CORS restricted to the site origin (2026-08-08): the wildcard predated the
// hardening pass. STATIC on purpose — a per-request reflected origin would
// need request-scoped headers, and mutating a module-level object is racy
// across concurrent requests in one isolate (a prod visitor could catch a
// dev origin on the checkout path). Cost of static: browser calls from the
// localhost dev preview can't READ these responses any more — verify these
// flows with curl (no CORS there) or on the deployed site.
const CORS = {
  "Access-Control-Allow-Origin": "https://shouldisellyet.com",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

// "rate" (market 30-year rate) needs no personal inputs — the threshold is a
// percent, and check_watches.py evaluates it against the pipeline's FRED rate.
// "velocity" is the approach-velocity alert: no threshold — it fires when the
// market's gathering STATE escalates past the baseline recorded at save time
// (check_watches compares against zip_velocity each refresh).
const METRICS = new Set(["walkaway", "equity", "lockin", "rate", "rategap", "gain", "velocity"]);
const DIRECTIONS = new Set(["below", "above", "escalates"]);
const TOKEN_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ ok: false, error: "method not allowed" }, 405);

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ ok: false, error: "bad json" }, 400);
  }

  const token = String(body.token ?? "");
  if (!TOKEN_RE.test(token)) return json({ ok: false, error: "bad token" });

  // Layer 2: 5/hour per hashed IP (schema-v18). Token-gated already, so this
  // only caps token-guessing noise and runaway clients.
  if (!await rateAllowed(req, "watch", 5, 3600)) {
    return json({ ok: false, error: "rate_limited" }, 429);
  }

  // Layer 3: Turnstile (see _shared/turnstile.ts for the degrade semantics).
  if (!await turnstileOk(req, String(body.cf_token ?? "").slice(0, 3000), "/save-watch")) {
    return json({ ok: false, error: "verification" });
  }

  const metric = String(body.metric ?? "");
  if (!METRICS.has(metric)) return json({ ok: false, error: "bad metric" });

  const clearing = body.clear === true;
  if (!clearing) {
    if (!DIRECTIONS.has(String(body.direction))) return json({ ok: false, error: "bad direction" });
    if (!Number.isFinite(Number(body.threshold))) return json({ ok: false, error: "bad threshold" });
  }

  try {
    // Verify the token belongs to a real, active/report subscriber, and load
    // its current watches array so we only touch this one metric's entry.
    const lookup = await fetch(
      `${SUPABASE_URL}/rest/v1/subscribers?select=id,zip,watches&access_token=eq.${token}&status=in.(active,report)&limit=1`,
      { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } },
    );
    const rows = lookup.ok ? await lookup.json() : [];
    if (!Array.isArray(rows) || rows.length === 0) return json({ ok: false, error: "unknown token" });

    const sub = rows[0];
    const current = Array.isArray(sub.watches) ? sub.watches : [];
    const others = current.filter((w: Record<string, unknown>) => w.metric !== metric);
    let entry: Record<string, unknown> =
      { metric, direction: body.direction, threshold: Number(body.threshold), crossed: false };
    if (!clearing && metric === "velocity") {
      // Record the CURRENT gathering state as the baseline the alert
      // escalates from. Missing velocity row → baseline "unknown": the first
      // refresh that produces a real state becomes the baseline instead of
      // firing a bogus day-one alert.
      // VELOCITY_ENABLED mirror — see pipeline/velocity_switch.py. The client
      // no longer draws the toggle, but that is a client guard on a SERVER
      // read: a direct POST with a valid token still reached the frozen
      // zip_velocity table and the state word came back in the 200 body.
      const VELOCITY_ENABLED = false;
      let baseline = "unknown";
      try {
        if (!VELOCITY_ENABLED) throw new Error("velocity suppressed");
        const vr = await fetch(
          `${SUPABASE_URL}/rest/v1/zip_velocity?select=payload&zip=eq.${sub.zip}&limit=1`,
          { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } });
        const vrows = vr.ok ? await vr.json() : [];
        if (vrows.length) baseline = vrows[0].payload?.state ?? "unknown";
      } catch (_e) { /* baseline stays unknown */ }
      entry = { metric, direction: "escalates", threshold: 0, crossed: false, baseline };
    }

    // ————— baselineBasis, stamped at write time —————
    // The durable fix check_watches.py's record_baseline_basis() asks for:
    // the baseline median this watch scales from was read off the ZIP's
    // CURRENT published reading, so the basis it was taken on is knowable
    // exactly once — now. Stamp it from zip_release (the server-side release
    // allowlist, schema-v36), which for both tranche and on-demand ZIPs says
    // 'active listings' — the asking-price basis every RentCast-derived
    // number carries. An unreleased ZIP (or a lookup failure) stamps
    // nothing: an unstamped watch routes to check_watches' rebaseline path,
    // which is the safe default, never to a cross-basis scale.
    if (!clearing) {
      try {
        const br = await fetch(
          `${SUPABASE_URL}/rest/v1/zip_release?select=basis&zip=eq.${sub.zip}&limit=1`,
          { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } });
        const brows = br.ok ? await br.json() : [];
        if (Array.isArray(brows) && brows.length && brows[0].basis) {
          entry.baselineBasis = brows[0].basis;
        }
      } catch (_e) { /* unstamped → rebaseline path; never guess a basis */ }
    }
    const watches = clearing ? others : [...others, entry];

    const patch: Record<string, unknown> = { watches };
    if (!clearing) patch.calc_inputs = body.calcInputs ?? null; // refresh shared inputs on every save

    const upd = await fetch(`${SUPABASE_URL}/rest/v1/subscribers?id=eq.${sub.id}`, {
      method: "PATCH",
      headers: {
        apikey: SERVICE_KEY,
        Authorization: `Bearer ${SERVICE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify(patch),
    });
    if (!upd.ok) return json({ ok: false, error: "save failed" });
    return json({ ok: true, watches });
  } catch (e) {
    console.error("save-watch error", e);
    return json({ ok: false, error: "server error" }, 200);
  }
});
