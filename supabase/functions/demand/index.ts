// ShouldISellYet — search-demand logging (which ZIPs people ask about).
//
// The homepage decides between three outcomes for every ZIP check: a live
// reading, the rebuilding notice, or the not-covered waitlist card. Nothing
// server-side could see that decision — market-reading is only called when a
// reading exists, and its CDN cache absorbs repeats — so demand for the
// ~17,874 notice ZIPs was invisible. This function is the measurement layer:
// one row per lookup in public.zip_lookups (schema-v41), plus a follow-up
// marking when the SAME tab's lookup led to a purchase click or a notify-me
// capture.
//
// PRIVACY POSTURE — same as track/index.ts, enforced the same ways:
//   * The only request header read is Origin. No IP (beyond the rate
//     limiter's salted daily-rotating hash), no User-Agent, no cookies — and
//     the table has no columns that could store them.
//   * The client is track.js, which sends NOTHING under DNT/GPC. Undercounting
//     is accepted; "we honor Do Not Track" stays true.
//   * Timestamps truncated to the hour.
//   * The row id is a client-generated random UUID held in sessionStorage:
//     it lets a tab mark ITS OWN lookup as followed and nothing else. It
//     names a lookup, never a person, and dies with the tab.
//
// Deploy as edge function `demand`. Disable "Enforce JWT verification".
// No extra secrets — SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY auto-injected.
//
// POST body (text/plain to avoid a preflight; parsed as JSON):
//   { op: "lookup", id, zip, outcome }   outcome: reading_shown |
//                                        notice_shown | invalid_zip
//   { op: "follow", id, kind }           kind: purchase | notify
//   200 {ok:true} | {ok:false,...}

import { rateAllowed } from "../_shared/ratelimit.ts";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// Keep in sync with the zip_lookups outcome CHECK in schema-v42.sql —
// pipeline/test_demand_fn.py fails the build when the lists drift. The
// pull_* and paid_coverage_gap outcomes are written server-side by
// ondemand-pull, never accepted from a browser: a caller who could log pull
// failures could fabricate coverage-gap data.
const OUTCOMES = new Set(["reading_shown", "notice_shown", "invalid_zip"]);

const ORIGINS = new Set([
  "https://shouldisellyet.com",
  "https://www.shouldisellyet.com",
  "http://localhost:5177",          // dev preview
]);

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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

async function rest(path: string, method: string, body: unknown) {
  return await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    method,
    headers: {
      apikey: SERVICE_KEY,
      Authorization: `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=minimal",
    },
    body: JSON.stringify(body),
  });
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

  // Same cap as track: ~two events a minute is far above human browsing and
  // low enough that a loop cannot fill the table.
  if (!await rateAllowed(req, "demand", 120, 3600)) {
    return json({ ok: false }, 429, cors);
  }

  const raw = await req.text();
  if (raw.length > 1024) return json({ ok: false, error: "too large" }, 400, cors);

  let b: Record<string, unknown>;
  try { b = JSON.parse(raw); } catch { return json({ ok: false, error: "bad json" }, 400, cors); }

  const id = String(b.id ?? "");
  if (!UUID_RE.test(id)) return json({ ok: false, error: "bad id" }, 400, cors);

  try {
    if (b.op === "lookup") {
      const zip = String(b.zip ?? "");
      const outcome = String(b.outcome ?? "");
      if (!/^\d{5}$/.test(zip)) return json({ ok: false, error: "bad zip" }, 400, cors);
      if (!OUTCOMES.has(outcome)) return json({ ok: false, error: "bad outcome" }, 400, cors);
      const r = await rest("zip_lookups", "POST", {
        id, zip, outcome,
        // Coarse on purpose — hour truncation, same as events.ts.
        ts: new Date(Math.floor(Date.now() / 3600000) * 3600000).toISOString(),
      });
      // 409 = duplicate id (a replayed send); already stored is success.
      if (r.status !== 201 && r.status !== 409) return json({ ok: false, error: "db" }, 200, cors);
      return json({ ok: true }, 200, cors);
    }

    if (b.op === "follow") {
      const kind = String(b.kind ?? "");
      if (kind !== "purchase" && kind !== "notify") {
        return json({ ok: false, error: "bad kind" }, 400, cors);
      }
      // Only ever sets a boolean to true on a row the tab itself created —
      // the UUID is unguessable, and the worst a forged id can do is nothing.
      const col = kind === "purchase" ? "followed_purchase" : "followed_notify";
      const r = await rest(`zip_lookups?id=eq.${id}`, "PATCH", { [col]: true });
      if (!r.ok) return json({ ok: false, error: "db" }, 200, cors);
      return json({ ok: true }, 200, cors);
    }

    return json({ ok: false, error: "bad op" }, 400, cors);
  } catch (_e) {
    // Never echo the failure — REST errors carry column names.
    return json({ ok: false, error: "db" }, 200, cors);
  }
});
