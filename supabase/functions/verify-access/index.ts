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
//   200 { ok:true, plan, zip, status, address, purchased_at }  — valid token
//   200 { ok:false }                                           — unknown/revoked
// NOTE: prices quoted in the webhook's emails are hardcoded there — keep them
// in sync with web/prices.js when pricing changes.

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

const CORS = {
  "Access-Control-Allow-Origin": "*",
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

  try {
    const r = await fetch(
      `${SUPABASE_URL}/rest/v1/subscribers` +
        `?select=plan,zip,status,address,created_at&access_token=eq.${token}` +
        `&status=in.(active,report)&limit=1`,
      { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } },
    );
    const rows = r.ok ? await r.json() : [];
    if (Array.isArray(rows) && rows.length) {
      const s = rows[0];
      // purchased_at powers the report page's 30-day upgrade-credit countdown
      return json({ ok: true, plan: s.plan, zip: s.zip, status: s.status,
                    address: s.address ?? "", purchased_at: s.created_at ?? null });
    }
    return json({ ok: false });
  } catch (_e) {
    return json({ ok: false }, 200);
  }
});
