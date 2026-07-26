// ShouldISellYet — save a personal-number watch (walk-away / equity / lock-in
// cost threshold alert) against an existing subscriber.
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
// Requires schema-v4.sql (adds calc_inputs / watch_* columns).
//
// POST /save-watch
//   body: { token, calcInputs, watchMetric, watchDirection, watchThreshold }
//     - watchMetric in "walkaway" | "equity" | "lockin"
//     - watchDirection in "below" | "above"
//     - watchThreshold: number
//     - pass watchMetric: null to clear/disable an existing watch
//   200 { ok: true }
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

const METRICS = new Set(["walkaway", "equity", "lockin"]);
const DIRECTIONS = new Set(["below", "above"]);
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

  // Clearing a watch: watchMetric explicitly null/absent with no threshold.
  const clearing = body.watchMetric == null;
  if (!clearing) {
    if (!METRICS.has(String(body.watchMetric))) return json({ ok: false, error: "bad metric" });
    if (!DIRECTIONS.has(String(body.watchDirection))) return json({ ok: false, error: "bad direction" });
    const t = Number(body.watchThreshold);
    if (!Number.isFinite(t)) return json({ ok: false, error: "bad threshold" });
  }
  const calcInputs = clearing ? null : (body.calcInputs ?? null);

  try {
    // Verify the token belongs to a real, active/report subscriber before
    // writing anything — this token check IS the auth for this endpoint.
    const lookup = await fetch(
      `${SUPABASE_URL}/rest/v1/subscribers?select=id&access_token=eq.${token}&status=in.(active,report)&limit=1`,
      { headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}` } },
    );
    const rows = lookup.ok ? await lookup.json() : [];
    if (!Array.isArray(rows) || rows.length === 0) return json({ ok: false, error: "unknown token" });

    const patch = clearing
      ? { calc_inputs: null, watch_metric: null, watch_direction: null, watch_threshold: null, watch_crossed: false }
      : {
          calc_inputs: calcInputs,
          watch_metric: body.watchMetric,
          watch_direction: body.watchDirection,
          watch_threshold: Number(body.watchThreshold),
          watch_crossed: false, // fresh baseline — don't fire on the value that was already true at save time
        };

    const upd = await fetch(`${SUPABASE_URL}/rest/v1/subscribers?access_token=eq.${token}`, {
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
    return json({ ok: true });
  } catch (e) {
    console.error("save-watch error", e);
    return json({ ok: false, error: "server error" }, 200);
  }
});
