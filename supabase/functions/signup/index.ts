// ShouldISellYet — guarded subscriber signup (waitlist + pre-checkout capture).
//
// WHY THIS EXISTS. Until 2026-08-08 the site inserted subscriber rows straight
// into /rest/v1/subscribers with the anon key (INSERT-only RLS). That capped
// the damage — nothing could be read or updated — but it was a scriptable
// junk-row and PII-injection vector with zero bot defense: any curl loop could
// fill the table with strangers' email addresses. Every subscriber write from
// the browser now comes through here instead, and the anon INSERT policy is
// revoked (schema-v17). The row shape is unchanged, so the Stripe webhook's
// pending-row match (email + status=pending) is unaffected.
//
// BOT DEFENSE, layer 1 of 3 (this function; rate limiting and Turnstile layer
// on in schema-v18/T3):
//   - honeypot: the form carries a visually-hidden "website" input no human
//     sees. Filled → bot.
//   - timing: the form stamps rendered_at (epoch ms) when it appears. A
//     submit under 2 seconds later is not a person. A MISSING rendered_at is
//     allowed through — cached pages from before this deploy don't carry the
//     field, and locking out humans to catch bots that would still hit the
//     other layers is the wrong trade.
// Both reject SILENTLY: success-shaped response, nothing stored, so a bot
// author sees no signal to adapt to. Each drop increments the bot_rejected
// counter in events (no content stored — counting is not tracking). The
// counter insert is best-effort: if the events enum migration hasn't been
// applied yet, or the insert fails for any reason, the response is unaffected.
//
// Deploy as edge function `signup`. Disable "Enforce JWT verification".
// No secrets needed — SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY auto-injected.
//
// POST /signup
//   { email, zip, plan: waitlist|monitor|report, source?,
//     address?, address_street?, address_unit?, address_city?, address_state?,
//     website?          — honeypot, must be empty
//     rendered_at?      — epoch ms the form appeared
//   }
//   200 { ok: true }    — stored (or silently dropped as a bot)
//   200 { ok: false }   — validation failed; the form shows its usual error

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

// Same Origin allowlist discipline as track: browsers can't spoof Origin, so
// this cheaply filters junk before any parsing happens.
const ORIGINS = new Set([
  "https://shouldisellyet.com",
  "https://www.shouldisellyet.com",
  "http://localhost:5177",
]);

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

// Best-effort counter. Failure must never affect the response — see header.
async function countBot(kind: "bot_rejected" | "turnstile_bypass", path: string) {
  try {
    await fetch(`${SUPABASE_URL}/rest/v1/events`, {
      method: "POST",
      headers: {
        apikey: SERVICE_KEY,
        Authorization: `Bearer ${SERVICE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify({
        event: kind,
        ts: new Date(Math.floor(Date.now() / 3600000) * 3600000).toISOString(),
        path,
      }),
    });
  } catch { /* counting is optional; storing the signup is not */ }
}

Deno.serve(async (req) => {
  const origin = req.headers.get("origin") ?? "";
  const allowed = ORIGINS.has(origin);
  const cors = allowed ? origin : "https://shouldisellyet.com";

  if (req.method === "OPTIONS") return json({ ok: true }, 200, cors);
  if (req.method !== "POST") return json({ ok: false, error: "method" }, 405, cors);
  if (!allowed) return json({ ok: false }, 403, cors);

  const raw = await req.text();
  if (raw.length > 4096) return json({ ok: false, error: "too large" }, 400, cors);

  let b: Record<string, unknown>;
  try { b = JSON.parse(raw); } catch { return json({ ok: false, error: "bad json" }, 400, cors); }

  const str = (k: string, max: number) => String(b[k] ?? "").trim().slice(0, max);

  // ————— bot checks, before any validation noise —————
  const decoy = str("website", 200);
  const renderedAt = Number(b.rendered_at ?? NaN);
  const tooFast = Number.isFinite(renderedAt) && Date.now() - renderedAt < 2000;
  if (decoy || tooFast) {
    await countBot("bot_rejected", "/signup");
    return json({ ok: true }, 200, cors);   // success-shaped, nothing stored
  }

  // ————— validation mirrors the subscribers column checks —————
  const email = str("email", 200).toLowerCase();
  const zip = str("zip", 5);
  const plan = str("plan", 10);
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return json({ ok: false, error: "valid email required" }, 200, cors);
  if (!/^\d{5}$/.test(zip)) return json({ ok: false, error: "5-digit zip required" }, 200, cors);
  if (!["waitlist", "monitor", "report"].includes(plan)) return json({ ok: false, error: "bad plan" }, 200, cors);

  const row: Record<string, unknown> = {
    email, zip, plan,
    source: str("source", 40) || null,
    address: str("address", 300) || null,
    address_street: str("address_street", 200) || null,
    address_unit: str("address_unit", 60) || null,
    address_city: str("address_city", 120) || null,
    address_state: str("address_state", 2) || null,
  };

  try {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/subscribers`, {
      method: "POST",
      headers: {
        apikey: SERVICE_KEY,
        Authorization: `Bearer ${SERVICE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=minimal",
      },
      body: JSON.stringify(row),
    });
    return json({ ok: r.ok }, 200, cors);
  } catch {
    return json({ ok: false, error: "storage" }, 200, cors);
  }
});
