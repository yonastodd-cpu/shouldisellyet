// ShouldISellYet — confirm a waitlist/alert email address (double opt-in).
//
// Reached by clicking the signed link in the one confirm email an
// unconfirmed address ever receives. GET, returns a plain page in the site's
// style — same pattern as `unsubscribe`.
//
// THE LINK IS SIGNED, NOT GUESSABLE: sig = HMAC-SHA256(secret, subscriber id).
// Nobody can confirm an address they don't control by enumerating ids, and
// the id alone (a UUID) leaks nothing. The secret is CONFIRM_SECRET if set,
// else derived from the service key — zero new operator steps, same fallback
// discipline as the rate-limit salt.
//
// WHY THIS EXISTS (do not "simplify" the mechanism away): double opt-in is
// the primary defense against signing up a third party's address to harass
// them — unconfirmed addresses receive nothing further, ever — and it
// protects the Resend sender reputation, which the paid transactional flow
// also depends on. See schema-v19.
//
// GET /confirm?id=<uuid>&sig=<hmac-hex>
//   valid   → stamps confirmed_at (idempotent) and says so
//   invalid → gentle "link looks incomplete" page, always 200

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const SECRET = Deno.env.get("CONFIRM_SECRET") || SERVICE_KEY.slice(-32);
const SITE = "https://shouldisellyet.com";
const ID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function page(heading: string, body: string) {
  return new Response(
    `<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>${heading} — ShouldISellYet</title>
<style>
  body{margin:0;background:#faf8f4;color:#1c2430;line-height:1.7;
       font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       display:grid;place-content:center;min-height:100vh;padding:24px}
  .card{max-width:520px;background:#fff;border:1px solid #e7e2d8;border-radius:14px;padding:28px 32px}
  h1{font-size:22px;margin:0 0 10px}
  p{font-size:15px;color:#3a4450;margin:0 0 12px}
  a{color:#1f3a5f}
  .fine{font-size:13px;color:#8a8578}
</style></head><body><div class="card">
<h1>${heading}</h1>${body}
<p class="fine"><a href="${SITE}/">ShouldISellYet.com</a></p>
</div></body></html>`,
    { status: 200, headers: { "Content-Type": "text/html; charset=utf-8" } },
  );
}

async function hmacHex(msg: string): Promise<string> {
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(SECRET), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(msg));
  return Array.from(new Uint8Array(sig)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

Deno.serve(async (req) => {
  const u = new URL(req.url);
  const id = u.searchParams.get("id") ?? "";
  const sig = (u.searchParams.get("sig") ?? "").toLowerCase();

  if (!ID_RE.test(id) || !/^[0-9a-f]{64}$/.test(sig)) {
    return page("That link looks incomplete",
      `<p>Some email apps cut long links in half. Try copying the whole link from the
       email into your address bar — or just reply to the email and we'll sort it out.</p>`);
  }

  const expect = await hmacHex(id);
  // Constant-time-ish compare: both strings are fixed 64-hex by the guards above.
  let diff = 0;
  for (let i = 0; i < 64; i++) diff |= expect.charCodeAt(i) ^ sig.charCodeAt(i);
  if (diff !== 0) {
    return page("That link looks incomplete",
      `<p>This confirmation link doesn't check out — it may have been truncated.
       Try copying the whole link from the email, or reply to it and we'll sort it out.</p>`);
  }

  try {
    const r = await fetch(
      `${SUPABASE_URL}/rest/v1/subscribers?id=eq.${id}&select=zip,confirmed_at`, {
        method: "PATCH",
        headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}`,
                   "Content-Type": "application/json", Prefer: "return=representation" },
        // Idempotent by nature: re-stamping an already-confirmed row with a
        // fresh click is harmless, and re-clicking an old email must work.
        body: JSON.stringify({ confirmed_at: new Date().toISOString() }),
      });
    const rows = r.ok ? await r.json() : [];
    if (!rows.length) {
      return page("Already taken care of",
        `<p>This signup is no longer on file — it may have expired unconfirmed
         (we delete unconfirmed signups after 7 days). You can join again any
         time from the site.</p>`);
    }
    const zip = rows[0].zip ?? "";
    return page("You're confirmed",
      `<p>We'll email you the moment ${zip ? `the market for <b>${zip}</b>` : "your market"} goes
       live — and never for anything else. Unsubscribe any time from any email we send.</p>`);
  } catch {
    return page("Something hiccuped",
      `<p>We couldn't save the confirmation just now. The link stays valid —
       try it again in a minute.</p>`);
  }
});
