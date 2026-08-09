// ShouldISellYet — Stripe customer portal session.
//
// Self-serve cancellation. Auto-renewal statutes generally require that a
// subscription bought online can be cancelled online, without emailing anyone
// or waiting for a human — "reply 'cancel'" does not satisfy that, and it was
// the only route this product offered.
//
// The portal is Stripe's own hosted page: cancel, update card, download
// invoices. We only mint a session and redirect.
//
// Deploy as edge function `portal-session`. Disable "Enforce JWT verification".
// Secrets:
//   STRIPE_SECRET_KEY   ⚠️ NEW — a real live-mode secret key. This is the only
//                       function that calls the Stripe API; stripe-webhook only
//                       verifies signatures and holds a placeholder.
// SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are auto-injected.
//
// POST /portal-session  { token }
//   200 { ok:true, url }              — open it
//   200 { ok:false, error, reason? }  — nothing sensitive leaks either way
//
// AUTHORISATION is the report access token, the same unguessable v4 UUID that
// unlocks the report — never an email. An email-keyed endpoint would let anyone
// who guesses an address open that person's billing portal, which is precisely
// the account-takeover this design avoids.

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const STRIPE_KEY = Deno.env.get("STRIPE_SECRET_KEY") ?? "";
const SITE = "https://shouldisellyet.com";

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

  if (!STRIPE_KEY) {
    // TODO (operator): set STRIPE_SECRET_KEY. Until then the UI falls back to
    // the email route rather than showing a dead button — a cancel control
    // that silently does nothing is worse than one that is honestly absent.
    console.error("STRIPE_SECRET_KEY not set — portal unavailable");
    return json({ ok: false, error: "portal not configured", reason: "unconfigured" });
  }

  try {
    const r = await fetch(
      `${SUPABASE_URL}/rest/v1/subscribers?select=stripe_customer_id,status` +
        `&access_token=eq.${token}&limit=1`,
      { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } },
    );
    const rows = r.ok ? await r.json() : [];
    const customer = Array.isArray(rows) && rows.length ? rows[0].stripe_customer_id : null;
    if (!customer) {
      // A real report buyer with no subscription lands here. Distinguish it so
      // the page can say "you don't have a subscription" instead of "error".
      return json({ ok: false, error: "no subscription found", reason: "no_customer" });
    }

    const form = new URLSearchParams({
      customer,
      return_url: `${SITE}/my-report.html?token=${token}`,
    });
    const s = await fetch("https://api.stripe.com/v1/billing_portal/sessions", {
      method: "POST",
      headers: {
        Authorization: `Bearer ${STRIPE_KEY}`,
        "Content-Type": "application/x-www-form-urlencoded",
      },
      body: form.toString(),
    });
    const session = await s.json();
    if (!s.ok || !session.url) {
      // The usual cause is the portal not being enabled in the Stripe
      // dashboard, which returns a specific and readable message — log it
      // rather than collapsing every failure into "try again".
      console.error("stripe portal error", s.status, JSON.stringify(session).slice(0, 400));
      return json({ ok: false, error: "could not open the billing portal" });
    }
    return json({ ok: true, url: session.url });
  } catch (e) {
    console.error("portal-session error", e);
    return json({ ok: false, error: "server error" });
  }
});
