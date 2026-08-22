// ShouldISellYet — one-click marketing unsubscribe.
//
// Reached by clicking a link in an email, so it answers GET and returns a page,
// not JSON. A working unsubscribe is a CAN-SPAM requirement for any message
// carrying promotional content; ours carries it in exactly one place, the
// upsell block inside the report-access email.
//
// WHAT IT DOES NOT DO, deliberately: it does not unsubscribe anyone from the
// product. Verdict alerts, the report link they paid for, and billing notices
// before a renewal all keep sending. Someone clicking "unsubscribe" on an
// upsell is saying "stop selling to me", not "cancel my subscription and stop
// warning me before you charge my card". Conflating those would be a worse
// failure than never having the link.
//
// Deploy as edge function `unsubscribe`. Disable "Enforce JWT verification".
// No secrets needed — SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are injected.
//
// GET /unsubscribe?token=<uuid>   → HTML confirmation, always 200
//
// Keyed on the access token, never on an email in the query string. An
// email-keyed unsubscribe lets anyone opt anyone else out by guessing an
// address, and leaks whether a given address is a customer.

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const SITE = "https://shouldisellyet.com";
const TOKEN_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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

Deno.serve(async (req) => {
  const token = new URL(req.url).searchParams.get("token") ?? "";
  if (!TOKEN_RE.test(token)) {
    return page("That link didn't work", `
<p>The unsubscribe link looks incomplete — some email apps cut long links in half.</p>
<p>Write to <a href="mailto:support@shouldisellyet.com">support@shouldisellyet.com</a> and we'll take care of it by hand.</p>`);
  }

  try {
    const r = await fetch(`${SUPABASE_URL}/rest/v1/subscribers?access_token=eq.${token}`, {
      method: "PATCH",
      headers: {
        apikey: SERVICE_KEY,
        Authorization: `Bearer ${SERVICE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify({
        marketing_opt_out: true,
        marketing_opt_out_at: new Date().toISOString(),
      }),
    });
    const rows = r.ok ? await r.json() : [];
    if (!Array.isArray(rows) || rows.length === 0) {
      return page("We couldn't find that subscription", `
<p>The link may be from an old email, or the account may already be closed.</p>
<p>Write to <a href="mailto:support@shouldisellyet.com">support@shouldisellyet.com</a> and we'll sort it out.</p>`);
    }
  } catch (e) {
    console.error("unsubscribe error", e);
    return page("Something went wrong", `
<p>We couldn't record that just now. Please email
<a href="mailto:support@shouldisellyet.com">support@shouldisellyet.com</a> and we'll do it manually — you won't get another promotional email either way.</p>`);
  }

  // Say plainly what DID and did NOT change. An unsubscribe page that implies
  // the whole service stopped is how people end up surprised twice.
  return page("You're unsubscribed from promotional email", `
<p>We won't send you offers or upgrade prompts again.</p>
<p><b>What still reaches you</b>, because it isn't marketing:</p>
<ul>
  <li>the link to a report you paid for</li>
  <li>alerts when your ZIP's reading changes — the thing you signed up for</li>
  <li>billing notices, including a heads-up before any renewal</li>
</ul>
<p>Want to stop those too? That means cancelling the subscription itself — you can do that yourself from your report page, or email
<a href="mailto:billing@shouldisellyet.com">billing@shouldisellyet.com</a>.</p>`);
});
