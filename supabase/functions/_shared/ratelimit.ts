// ShouldISellYet — shared rate limiting for public edge functions.
//
// Usage, first thing after parsing (limits are per function, so the caller
// names itself):
//
//   import { rateAllowed } from "../_shared/ratelimit.ts";
//   if (!await rateAllowed(req, "signup-waitlist", 3, 86400, email)) {
//     return json({ ok: false, error: "rate_limited" }, 429, cors);
//   }
//
// KEY DESIGN — raw IPs never leave this module and never reach storage. The
// key is sha256(salt + UTC-date + scope + value): the salt is secret, and the
// date component rotates the entire keyspace at midnight UTC, so yesterday's
// keys join to nothing. This mirrors the analytics posture (events stores no
// identifier), which is what lets the privacy page keep saying "no personal
// identifiers" with a straight face. The salt is RL_SALT if set, else a hash
// of the service key — a deploy works with zero new secrets, and setting
// RL_SALT later just rotates everything once.
//
// FAIL-OPEN, deliberately: if the RPC errors (cold start, migration not yet
// applied, transient network), the request is ALLOWED. A rate limiter that
// can take the waitlist down when Postgres hiccups protects nothing worth
// that price; the honeypot and Turnstile layers still stand. Do not "harden"
// this into fail-closed.

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const SALT = Deno.env.get("RL_SALT") || SERVICE_KEY.slice(-32);

async function sha256hex(s: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return Array.from(new Uint8Array(d)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function clientIp(req: Request): string {
  // First hop of x-forwarded-for is the client as seen by the edge.
  return (req.headers.get("x-forwarded-for") ?? "").split(",")[0].trim() || "unknown";
}

async function hit(key: string, windowSeconds: number, max: number): Promise<boolean> {
  try {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/rpc/rate_limit_hit`, {
      method: "POST",
      headers: {
        apikey: SERVICE_KEY,
        Authorization: `Bearer ${SERVICE_KEY}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ p_key: key, p_window_seconds: windowSeconds, p_max: max }),
    });
    if (!r.ok) return true;              // fail-open — see header
    return (await r.json()) === true;
  } catch {
    return true;                         // fail-open — see header
  }
}

// True = under the cap, proceed. Checks the IP key always, and the email key
// when an email is given — both must pass, so rotating IPs doesn't stretch a
// per-address cap and one shared NAT doesn't inherit one visitor's abuse.
export async function rateAllowed(
  req: Request, scope: string, max: number, windowSeconds: number, email?: string,
): Promise<boolean> {
  const day = new Date().toISOString().slice(0, 10);   // rotates the keyspace daily
  const ipKey = await sha256hex(`${SALT}|${day}|${scope}|ip|${clientIp(req)}`);
  if (!await hit(ipKey, windowSeconds, max)) return false;
  const norm = (email ?? "").trim().toLowerCase();
  if (norm) {
    const emailKey = await sha256hex(`${SALT}|${day}|${scope}|em|${norm}`);
    if (!await hit(emailKey, windowSeconds, max)) return false;
  }
  return true;
}
