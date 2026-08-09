// ShouldISellYet — verify a report access token.
//
// The report page (my-report.html) calls this with ?token=... before it will
// render. The token is minted by the stripe-webhook function on payment and
// delivered via the post-checkout redirect and the welcome email. Because the
// check runs server-side with the service-role key, the token can't be forged
// and the subscribers table is never exposed to the browser.
//
// Deploy as edge function `verify-access`. Disable "Enforce JWT verification".
// No extra secrets needed — SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are auto-injected.
//
// GET  /verify-access?token=<uuid>
//   200 { ok:true, plan, zip, status, purchased_at, watches,
//         address_street, address_unit, address_city, address_state }  — valid token
//   200 { ok:false }                                                   — unknown/revoked
// The address_* fields are the canonical structured address (schema-v6) — the
// report page prefills its intake from them, so a buyer never retypes it and
// it works on a device that has never seen them. `address` (the deprecated
// freeform column) is still returned for rows written before v6.
// `watches` (from schema-v4.sql) lets the report page restore each metric's
// toggle to its last-saved state instead of always starting unchecked.
// NOTE: prices quoted in the webhook's emails come from its own PRICES block
// (edge functions can't import web/prices.js) — keep the two in sync when
// pricing changes; pipeline/test_prices.py checks that they agree.

import { rateAllowed } from "../_shared/ratelimit.ts";

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
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "authorization, apikey, content-type",
};

function json(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json", ...CORS },
  });
}

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });

  const token = new URL(req.url).searchParams.get("token") ?? "";
  // basic shape check — uuid-ish, avoids pointless queries
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(token)) {
    return json({ ok: false });
  }

  // Layer 2: 10/hour per hashed IP (schema-v18). Tokens are 128-bit UUIDs so
  // enumeration is hopeless anyway; this caps the noise and the quota burn.
  if (!await rateAllowed(req, "verify", 10, 3600)) {
    return json({ ok: false, error: "rate_limited" }, 429);
  }

  try {
    const r = await fetch(
      `${SUPABASE_URL}/rest/v1/subscribers` +
        `?select=plan,zip,status,address,address_street,address_unit,address_city,` +
        `address_state,created_at,watches&access_token=eq.${token}` +
        `&status=in.(active,report)&limit=1`,
      { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } },
    );
    const rows = r.ok ? await r.json() : [];
    if (Array.isArray(rows) && rows.length) {
      const s = rows[0];

      // Approach velocity for THIS zip — the paid layer (schema-v20). Served
      // only here, only after the token validated: this response is the sole
      // read path, so an unauthenticated fetch of report data cannot contain
      // velocity fields. Absent rows (table not yet seeded, or an unscored
      // ZIP) yield null and the report renders its "computed on the next data
      // refresh" note — a missing number is shown as missing, never invented.
      let velocity = null;
      try {
        const vr = await fetch(
          `${SUPABASE_URL}/rest/v1/zip_velocity?select=period,payload&zip=eq.${s.zip}&limit=1`,
          { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } },
        );
        const vrows = vr.ok ? await vr.json() : [];
        if (Array.isArray(vrows) && vrows.length) {
          velocity = { period: vrows[0].period, ...vrows[0].payload };
        }
      } catch (_e) { /* velocity is additive; the report must not fail on it */ }

      // purchased_at powers the report page's 30-day upgrade-credit countdown
      return json({ ok: true, plan: s.plan, zip: s.zip, status: s.status,
                    address_street: s.address_street ?? "",
                    address_unit: s.address_unit ?? "",
                    address_city: s.address_city ?? "",
                    address_state: s.address_state ?? "",
                    address: s.address ?? "",   // deprecated, pre-v6 rows only
                    purchased_at: s.created_at ?? null,
                    watches: s.watches ?? [],
                    velocity });
    }
    return json({ ok: false });
  } catch (_e) {
    return json({ ok: false }, 200);
  }
});
