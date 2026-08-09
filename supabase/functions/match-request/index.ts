// ShouldISellYet — "Get Connected" introduction request.
//
// The report's neutral card collects name/contact/consent and POSTs here.
// This function (service role) inserts the match_requests row and emails the
// team, who makes the introduction manually — nothing is auto-forwarded to
// any agent.
//
// Deploy as edge function `match-request`. Disable "Enforce JWT verification".
// Secrets: RESEND_API_KEY (already used by stripe-webhook); optionally
// ALERT_FROM, MATCH_TEAM_TO, MATCH_ARCHIVE_BCC. SUPABASE_URL /
// SUPABASE_SERVICE_ROLE_KEY are auto-injected.
//
// Two emails go out per request, BCC'd to the archive address when one is
// configured (MATCH_ARCHIVE_BCC — see below; it must be a real mailbox):
//   1. the team notification, so someone can act on it
//   2. a confirmation to the requester carrying the same disclosure they saw
// The BCC is the record that each actually sent — a send that never happened
// and a send that silently failed look identical without one.
// TODO (Resend): confirm the sending domain is verified in Resend for
// support@shouldisellyet.com — the insert still succeeds if email fails.
//
// POST /match-request
//   { name, email, phone?, zip, address?, timeline?, note?,
//     consent_text, disclosure_version, disclosure_text, verdict?, source? }
//   200 { ok: true, id }  |  200 { ok: false, error }
//
// Requires schema-v8 (disclosure_* columns). The disclosure is what the person
// is shown on submission — who handles the request, and that a referral fee
// may be involved — and it is stored verbatim alongside the consent text so
// "what was I told" is answerable from the row.

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const RESEND_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const FROM = Deno.env.get("ALERT_FROM") ?? "ShouldISellYet <support@shouldisellyet.com>";
// Where introduction requests land.
const TEAM = Deno.env.get("MATCH_TEAM_TO") ?? "ntrealty314@gmail.com";

// Archive copy — OFF unless explicitly configured, and that default is a
// correction, not caution.
//
// It defaulted to alerts@shouldisellyet.com, which is the FROM address. A
// sending identity is not a mailbox: alerts@ can send mail because Resend
// holds the DKIM key for the domain, but nothing receives there — the domain's
// actual mail is on Titan. So every BCC hard-bounced with "Recipient not
// found", and Resend then SUPPRESSED the address, which is worse than the
// original problem: bounces damage sending reputation for every other email
// the domain sends.
//
// To turn the archive back on, set MATCH_ARCHIVE_BCC to an address that can
// actually RECEIVE — either create a real alerts@ mailbox in Titan (and clear
// the Resend suppression first), or point it at an existing inbox.
//
// CURRENT (2026-08-07): set to hello@shouldisellyet.com, a real Titan mailbox.
// Note this is read at module load, not per request, so changing the secret
// needs a redeploy — a warm worker keeps the value it booted with, which is
// exactly how a "fixed" setting can appear to do nothing.
// Expect TWO archive copies per request: the BCC rides on both the agent
// email and the customer confirmation, on purpose, so the record shows each
// one actually sent rather than only that the request arrived.
const ARCHIVE = Deno.env.get("MATCH_ARCHIVE_BCC") ?? "";
const bcc = ARCHIVE.trim() ? { bcc: [ARCHIVE.trim()] } : {};

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
  const disclosure_version = str("disclosure_version", 60);
  const disclosure_text = str("disclosure_text", 1200);
  const verdict = str("verdict", 20);
  const source = str("source", 40) || "report";

  // ————— bot checks, before validation (silent success-shaped drop) —————
  // This function emails a visitor-supplied address (the sent-confirmation),
  // which makes it the one endpoint where a bot can make a stranger's inbox
  // ring. Honeypot ("website", hidden field no human sees) or a submit under
  // 2s of the modal opening → count it, store nothing, send nothing, and
  // return the success shape so the bot learns nothing. A MISSING
  // rendered_at passes — cached pages predate the field.
  {
    const decoy = str("website", 200);
    const renderedAt = Number(b.rendered_at ?? NaN);
    if (decoy || (Number.isFinite(renderedAt) && renderedAt > 0 && Date.now() - renderedAt < 2000)) {
      try {
        await fetch(`${SUPABASE_URL}/rest/v1/events`, {
          method: "POST",
          headers: { apikey: SERVICE_KEY, Authorization: `Bearer ${SERVICE_KEY}`,
                     "Content-Type": "application/json", Prefer: "return=minimal" },
          body: JSON.stringify({ event: "bot_rejected",
            ts: new Date(Math.floor(Date.now() / 3600000) * 3600000).toISOString(),
            path: "/match-request" }),
        });
      } catch { /* counter is best-effort */ }
      // Mirror the real success shape ({ok, id}) so the drop is
      // indistinguishable; the id is a throwaway UUID.
      return json({ ok: true, id: crypto.randomUUID() });
    }
  }

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
        source, consent_text,
        disclosure_version: disclosure_version || null,
        disclosure_text: disclosure_text || null,
        disclosure_shown_at: disclosure_version ? new Date().toISOString() : null }),
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
  <p style="font-size:12px;color:#98a2b3;margin-top:6px">Disclosure shown (${esc(disclosure_version || "none recorded")}):<br>${esc(disclosure_text || "—").replace(/\n\n/g, "<br>")}</p>
</div>`;
      const r = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: { Authorization: `Bearer ${RESEND_KEY}`, "Content-Type": "application/json" },
        body: JSON.stringify({ from: FROM, to: [TEAM], ...bcc,
          subject: `Introduction requested — ${zip}`, html }),
      });
      if (!r.ok) console.error("resend error", r.status, await r.text());

      // Confirmation to the requester, carrying the SAME disclosure text they
      // saw on screen. A disclosure that exists only in a modal is one the
      // person cannot re-read after they close it — so it goes in writing too.
      // Skipped rather than faked if the client sent no disclosure: an email
      // that invents its own wording would defeat the point of storing it.
      if (disclosure_text) {
        const paras = disclosure_text.split("\n\n")
          .map((s) => `<p style="font-size:15px;line-height:1.65;margin:0 0 12px">${esc(s)}</p>`)
          .join("");
        const confirm = `
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">ShouldISellYet</p>
  <h1 style="font-size:24px;margin:6px 0 14px">Your introduction request is in.</h1>
  ${paras}
  <p style="font-size:12px;color:#98a2b3;line-height:1.5;margin-top:18px">You're getting this because you asked for an introduction on shouldisellyet.com for ${esc(zip)}. Nothing else has been shared. Reply to this email if you'd rather we didn't proceed.</p>
</div>`;
        const c = await fetch("https://api.resend.com/emails", {
          method: "POST",
          headers: { Authorization: `Bearer ${RESEND_KEY}`, "Content-Type": "application/json" },
          body: JSON.stringify({ from: FROM, to: [email], ...bcc,
            subject: "Your introduction request is in", html: confirm }),
        });
        if (!c.ok) console.error("confirmation email failed", c.status, await c.text());
      }
    } else {
      console.error("RESEND_API_KEY not set — match request saved but team email skipped");
    }

    return json({ ok: true, id: row.id });
  } catch (e) {
    console.error("match-request error", e);
    return json({ ok: false, error: "server error" }, 200);
  }
});
