// ShouldISellYet — exchange a Stripe checkout session id for a report token.
//
// Closes the loop Stripe leaves open. A Payment Link's default "after payment"
// behaviour is Stripe's own confirmation page, which is a dead end: the
// customer has paid, has no link to what they bought, and their only move is
// to close the tab and go looking in their email. This lets success.html send
// them straight into the report instead.
//
// THE RACE THIS EXISTS TO HANDLE. The browser redirect and the webhook are two
// independent deliveries. The redirect usually wins, so at the moment
// success.html first asks, the row often does not exist yet. That is normal,
// not an error — hence a distinct `pending` answer the page can poll on,
// rather than a failure it would have to show the customer.
//
// Deploy as edge function `checkout-session`. Disable "Enforce JWT
// verification" — it is called from a browser with no Supabase session.
// No extra secrets: SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are injected.
//
// POST { session_id: "cs_live_..." }
//   200 { ok:true,  token }             — row exists, token minted
//   200 { ok:false, pending:true }      — webhook has not landed yet; poll
//   200 { ok:false, error:"bad session" } — malformed id, never a lookup
//
// WHY A SESSION ID IS AN ACCEPTABLE CREDENTIAL HERE. It is high-entropy, it is
// issued by Stripe to exactly one buyer, and it arrives only in that buyer's
// own redirect. Presenting it is the same class of proof as holding the emailed
// link. It deliberately has NO expiry: the access token it returns has none
// either, so expiring this exchange would look like a control while changing
// nothing an attacker could reach. One honest boundary beats two inconsistent
// ones. Nothing else about the row is returned — not the email, not the plan.

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

// Stripe checkout session ids: cs_live_… / cs_test_…, alphanumeric.
// Bounded so a hostile value can never reach the query string.
const SESSION_RE = /^cs_(live|test)_[A-Za-z0-9]{8,200}$/;

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ ok: false, error: "method not allowed" }, 405);

  let body: Record<string, unknown>;
  try {
    body = await req.json();
  } catch {
    return json({ ok: false, error: "bad json" }, 400);
  }

  const sessionId = String(body.session_id ?? "");
  if (!SESSION_RE.test(sessionId)) return json({ ok: false, error: "bad session" });

  try {
    const r = await fetch(
      `${SUPABASE_URL}/rest/v1/subscribers` +
      `?select=access_token&stripe_session_id=eq.${encodeURIComponent(sessionId)}&limit=1`,
      { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } },
    );
    const rows = r.ok ? await r.json() : [];
    const token = Array.isArray(rows) && rows[0]?.access_token;

    // No row, or a row without a token yet: the webhook is still in flight.
    // Same answer either way — the caller's move is identical.
    if (!token) return json({ ok: false, pending: true });

    return json({ ok: true, token });
  } catch (e) {
    console.error("checkout-session error", e);
    // Report as pending, not as an error. A transient blip should leave the
    // page polling, not tell someone who just paid that something is wrong.
    return json({ ok: false, pending: true });
  }
});
