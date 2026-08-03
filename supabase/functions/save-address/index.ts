// ShouldISellYet — write the canonical address back to a subscriber's row.
//
// The address is captured once on subscribe.html, but it can be CORRECTED
// later on the report page (a typo, a unit number, a ZIP the mismatch prompt
// resolved). Without this function that correction would only ever reach the
// browser's localStorage mirror, so the customer's next device would show the
// old address — and "one canonical address" would only be true until the
// first edit.
//
// Same shape as save-watch: the anon key used everywhere else on the site is
// insert-only (see schema.sql) and can never update an existing row, so this
// runs with the service-role key after independently verifying the access
// token. The token is the authorisation — a caller can only ever write to the
// row that token already unlocks.
//
// Deploy as edge function `save-address`. Disable "Enforce JWT verification".
// No secrets needed — SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are auto-injected.
// Requires schema-v6.sql (adds the address_* columns).
//
// POST /save-address
//   { token, street, unit, city, state, zip }
//   200 { ok: true, zip }
//   200 { ok: false, error }

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

const CORS = {
  "Access-Control-Allow-Origin": "*",
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
const STATES = new Set(
  ("AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS " +
   "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY")
    .split(" "),
);

/** Trim, collapse whitespace, and cap length. Free text goes into a database
 *  a human later reads in an ops list — an unbounded field is a paste bomb. */
const clean = (v: unknown, max = 120) =>
  String(v ?? "").trim().replace(/\s+/g, " ").slice(0, max);

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

  const street = clean(body.street);
  const unit = clean(body.unit, 40);
  const city = clean(body.city, 80);
  const state = clean(body.state, 2).toUpperCase();
  const zip = String(body.zip ?? "").replace(/\D/g, "").slice(0, 5);

  // Validated server-side as well as in the browser. `zip` carries a ^\d{5}$
  // check in the schema, so a bad one would fail the write anyway — better to
  // say why than to return a generic save error.
  if (!street) return json({ ok: false, error: "street required" });
  if (!/^\d{5}$/.test(zip)) return json({ ok: false, error: "zip must be 5 digits" });
  if (!city) return json({ ok: false, error: "city required" });
  if (!STATES.has(state)) return json({ ok: false, error: "bad state" });

  try {
    const lookup = await fetch(
      `${SUPABASE_URL}/rest/v1/subscribers?select=id&access_token=eq.${token}` +
        `&status=in.(active,report)&limit=1`,
      { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } },
    );
    const rows = lookup.ok ? await lookup.json() : [];
    if (!Array.isArray(rows) || rows.length === 0) return json({ ok: false, error: "unknown token" });

    const upd = await fetch(`${SUPABASE_URL}/rest/v1/subscribers?id=eq.${rows[0].id}`, {
      method: "PATCH",
      headers: {
        apikey: SERVICE_KEY,
        Authorization: `Bearer ${SERVICE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify({
        address_street: street,
        address_unit: unit || null,
        address_city: city,
        address_state: state,
        zip,
      }),
    });
    if (!upd.ok) return json({ ok: false, error: "save failed" });
    return json({ ok: true, zip });
  } catch (e) {
    console.error("save-address error", e);
    return json({ ok: false, error: "server error" }, 200);
  }
});
