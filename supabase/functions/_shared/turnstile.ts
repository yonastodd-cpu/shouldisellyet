// ShouldISellYet — server-side Turnstile verification (layer 3).
//
// Semantics, matched to the client's graceful-degrade design:
//   - TURNSTILE_SECRET unset  → layer off: allow, count nothing.
//   - secret set, token given → verify with siteverify; INVALID → reject.
//   - secret set, token EMPTY → allow, count turnstile_bypass. The server
//     cannot distinguish "script failed to load for a human" from "bot didn't
//     bother" — rejecting would lock humans out (availability over lockout),
//     so the bypass COUNTER is the alarm instead: a rising bypass rate in
//     events_daily means bots have learned to omit the token, and the
//     honeypot + rate limits in front of every bypass are what they still
//     have to beat. Do not "simplify" the counter away — it is the only
//     visibility this trade-off has.

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const SECRET = Deno.env.get("TURNSTILE_SECRET") ?? "";

async function count(path: string) {
  try {
    await fetch(`${SUPABASE_URL}/rest/v1/events`, {
      method: "POST",
      headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}`,
                 "Content-Type": "application/json", Prefer: "return=minimal" },
      body: JSON.stringify({ event: "turnstile_bypass",
        ts: new Date(Math.floor(Date.now() / 3600000) * 3600000).toISOString(), path }),
    });
  } catch { /* counter is best-effort */ }
}

// True = proceed. False = reject (invalid token while the layer is on).
export async function turnstileOk(req: Request, token: string, path: string): Promise<boolean> {
  if (!SECRET) return true;                    // layer not configured yet
  if (!token) { await count(path); return true; }   // degrade — counted
  try {
    const ip = (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim();
    const r = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ secret: SECRET, response: token, ...(ip ? { remoteip: ip } : {}) }),
    });
    const j = await r.json();
    return j.success === true;
  } catch {
    return true;                               // siteverify outage ≠ lockout
  }
}
