// ShouldISellYet — "Get Connected" introduction request.
//
// The report's neutral card collects name/contact/consent and POSTs here.
// This function (service role) inserts the match_requests row and emails the
// team, who makes the introduction manually — nothing is auto-forwarded to
// any agent.
//
// Deploy as edge function `match-request`. Disable "Enforce JWT verification".
// Secrets: RESEND_API_KEY (already used by stripe-webhook) and optionally
// ALERT_FROM. SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are auto-injected.
// TODO (Resend): confirm the sending domain is verified in Resend for
// alerts@shouldisellyet.com — the insert still succeeds if email fails.
//
// POST /match-request
//   { name, email, phone?, zip, address?, timeline?, note?,
//     consent_text, verdict?, source? }
//   200 { ok: true, id }  |  200 { ok: false, error }

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const RESEND_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const FROM = Deno.env.get("ALERT_FROM") ?? "EquityWatch <alerts@shouldisellyet.com>";
const TEAM = "naomi@shouldisellyet.com";

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

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") return new Response("ok", { headers: CORS });
  if (req.method !== "POST") return json({ ok: false, error: "method not allowed" }, 405);

  let b: Record<string, unknown>;
  try {
    b = await req.json();
  } catch {
    return json({ ok: false, error: "bad json" }, 400);
  }

  const str = (k: string, max = 500) => String(b[k] ?? "").trim().slice(0, max);
  const name = str("name", 120);
  const email = str("email", 200);
  const phone = str("phone", 40);
  const zip = str("zip", 5);
  const address = str("address", 300);
  const timeline = str("timeline", 40);
  const note = str("note", 1000);
  const consent_text = str("consent_text", 500);
  const verdict = str("verdict", 20);
  const source = str("source", 40) || "report";

  if (!name) return json({ ok: false, error: "name required" });
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) return json({ ok: false, error: "valid email required" });
  if (!/^\d{5}$/.test(zip)) return json({ ok: false, error: "5-digit zip required" });
  if (!consent_text) return json({ ok: false, error: "consent required" });

  try {
    const ins = await fetch(`${SUPABASE_URL}/rest/v1/match_requests`, {
      method: "POST",
      headers: {
        apikey: SERVICE_KEY,
        Authorization: `Bearer ${SERVICE_KEY}`,
        "Content-Type": "application/json",
        Prefer: "return=representation",
      },
      body: JSON.stringify({ name, email, phone: phone || null, zip, address: address || null,
        timeline: timeline || null, note: note || null, verdict: verdict || null,
        source, consent_text }),
    });
    if (!ins.ok) {
      console.error("match_requests insert failed", ins.status, await ins.text());
      return json({ ok: false, error: "save failed" });
    }
    const [row] = await ins.json();

    // Team email — every submitted field, the verdict, the row id, and the
    // next action. Email failure never fails the request; the row is saved.
    if (RESEND_KEY) {
      const fields: Array<[string, string]> = [
        ["Name", name], ["Email", email], ["Phone", phone || "—"],
        ["ZIP", zip], ["Address", address || "—"], ["Timeline", timeline || "—"],
        ["Note", note || "—"], ["Report verdict", verdict || "—"],
        ["Source", source], ["Row ID", row.id],
      ];
      const html = `
<div style="font-family:Georgia,serif;max-width:560px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#8a7a55;font-weight:bold">Get Connected — introduction requested</p>
  <h1 style="font-size:22px;margin:6px 0 12px">Introduction requested — ${esc(zip)}</h1>
  <table style="border-collapse:collapse;font-size:14px">${fields.map(([k, v]) =>
    `<tr><td style="padding:4px 14px 4px 0;color:#667085;vertical-align:top">${k}</td><td style="padding:4px 0"><b>${esc(v)}</b></td></tr>`).join("")}
  </table>
  <p style="font-size:14px;margin-top:16px"><b>Next action:</b> Make the introduction manually, then update the row's status.</p>
  <p style="font-size:12px;color:#98a2b3;margin-top:14px">Consent shown to the user: “${esc(consent_text)}”</p>
</div>`;
      const r = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: { Authorization: `Bearer ${RESEND_KEY}`, "Content-Type": "application/json" },
        body: JSON.stringify({ from: FROM, to: [TEAM], subject: `Introduction requested — ${zip}`, html }),
      });
      if (!r.ok) console.error("resend error", r.status, await r.text());
    } else {
      console.error("RESEND_API_KEY not set — match request saved but team email skipped");
    }

    return json({ ok: true, id: row.id });
  } catch (e) {
    console.error("match-request error", e);
    return json({ ok: false, error: "server error" }, 200);
  }
});
