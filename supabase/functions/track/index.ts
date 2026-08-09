// ShouldISellYet — anonymous first-party event counter.
//
// The privacy policy says: "We collect anonymous, first-party usage counts
// (like how many ZIP checks happen) with no cookies, no advertising trackers,
// and no personal identifiers. We honor Do Not Track." This function is that
// sentence, enforced. What keeps it true:
//
//   * The ONLY request header this function reads is Origin (for the browser
//     gate below). It never touches X-Forwarded-For, User-Agent, or cookies —
//     and the events table has no column that could store them anyway.
//   * The client sends nothing when DNT/GPC is signalled (track.js), so by
//     the time a request arrives here, consent-by-silence already happened.
//   * Timestamps are truncated to the hour. Daily charts don't need more,
//     and precise times are a correlation surface.
//   * path is cut at the first ? or # — a my-report.html?token=… URL must
//     never leak its token into analytics.
//
// Deploy as edge function `track`. Disable "Enforce JWT verification".
// No extra secrets — SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are injected.
//
// POST body (text/plain to avoid a CORS preflight per pageview; parsed as
// JSON regardless): {event, zip?, plan?, source?, path?, ref?, ns?}
//   200 {ok:true}                    stored
//   400 {ok:false,error:"…"}         malformed / unknown event
//   403 {ok:false}                   Origin not ours — browsers can't spoof
//                                    Origin, so this cheaply filters junk;
//                                    curl can fake it, which is fine: the
//                                    table holds nothing worth faking into.

import { rateAllowed } from "../_shared/ratelimit.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// Keep in sync with schema-v11.sql — pipeline/test_track_events.py fails the
// build if these lists drift apart.
const EVENTS = new Set([
  "page_view",
  "zip_check",
  "purchase_click_report",
  "purchase_click_monitor",
  "share_click",
  "match_request_opened",
]);

const ORIGINS = new Set([
  "https://shouldisellyet.com",
  "https://www.shouldisellyet.com",
  "http://localhost:5177",          // dev preview
]);

const OUR_HOSTS = new Set(["shouldisellyet.com", "www.shouldisellyet.com", "localhost"]);

function json(body: unknown, status: number, origin: string) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": "application/json",
      "Access-Control-Allow-Origin": origin,
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "content-type",
    },
  });
}

// Domain only, never a path. Accepts either a bare hostname (what track.js
// sends) or a full URL someone else might send, and reduces both.
function refDomain(v: unknown): string | null {
  let s = String(v ?? "").trim().toLowerCase();
  if (!s) return null;
  s = s.replace(/^[a-z]+:\/\//, "");
  s = s.split(/[/?#:]/)[0];
  if (!s || OUR_HOSTS.has(s)) return null;   // self-referrals are noise
  return s.slice(0, 80);
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin") ?? "";
  const allowed = ORIGINS.has(origin);
  const cors = allowed ? origin : "https://shouldisellyet.com";

  if (req.method === "OPTIONS") {
    return new Response("ok", {
      headers: {
        "Access-Control-Allow-Origin": cors,
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "content-type",
      },
    });
  }
  if (req.method !== "POST") return json({ ok: false, error: "method" }, 405, cors);
  if (!allowed) return json({ ok: false }, 403, cors);

  // Layer 2: 120/hour per hashed IP (schema-v18) — roughly two events a
  // minute, far above any human browsing pattern, low enough that a replay
  // loop cannot burn the events quota.
  if (!await rateAllowed(req, "track", 120, 3600)) {
    return json({ ok: false }, 429, cors);
  }

  const raw = await req.text();
  if (raw.length > 2048) return json({ ok: false, error: "too large" }, 400, cors);

  let b: Record<string, unknown>;
  try {
    b = JSON.parse(raw);
  } catch {
    return json({ ok: false, error: "bad json" }, 400, cors);
  }

  const event = String(b.event ?? "");
  if (!EVENTS.has(event)) return json({ ok: false, error: "unknown event" }, 400, cors);

  const zip = /^\d{5}$/.test(String(b.zip ?? "")) ? String(b.zip) : null;
  const planRaw = String(b.plan ?? "");
  const plan = ["annual", "monthly", "report"].includes(planRaw) ? planRaw : null;
  const utm = String(b.source ?? "").trim().slice(0, 60) || null;
  const priceMode = ["monthly_led", "annual_led"].includes(String(b.price_mode ?? ""))
    ? String(b.price_mode) : null;

  // Pathname only. Cut at ? and # so tokens and query params can't arrive
  // even if a caller sends a full URL.
  let path = String(b.path ?? "").split(/[?#]/)[0].slice(0, 160);
  if (path && !path.startsWith("/")) path = "/" + path;

  const row = {
    event,
    // Coarse on purpose — see header comment.
    ts: new Date(Math.floor(Date.now() / 3600000) * 3600000).toISOString(),
    is_new_session: b.ns === true,
    utm_source: utm,
    price_mode: priceMode,
    referrer: refDomain(b.ref),
    zip,
    plan,
    path: path || null,
  };

  try {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/events`, {
      method: "POST",
      headers: {
        apikey: SERVICE_KEY,
        Authorization: `Bearer ${SERVICE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify(row),
    });
    if (r.status !== 201) {
      console.error("insert failed", r.status, (await r.text()).slice(0, 200));
      return json({ ok: false, error: "db" }, 200, cors);
    }
  } catch (e) {
    console.error("track error", e);
    return json({ ok: false, error: "db" }, 200, cors);
  }

  return json({ ok: true }, 200, cors);
});
