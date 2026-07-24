// ShouldISellYet — Stripe webhook → auto-activate subscribers + welcome email.
//
// Deploy as a Supabase Edge Function named `stripe-webhook`.
// Secrets required (Supabase dashboard → Edge Functions → Secrets):
//   STRIPE_WEBHOOK_SECRET   from the Stripe webhook endpoint you create
//   RESEND_API_KEY          from resend.com
//   ALERT_FROM              e.g. "EquityWatch <alerts@shouldisellyet.com>" (optional)
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected automatically.
//
// Stripe events handled:
//   checkout.session.completed     → upsert subscriber as active (+ welcome email)
//   customer.subscription.deleted  → mark subscriber canceled

import Stripe from "npm:stripe@17";

const stripe = new Stripe("sk_placeholder_not_used_for_verification", {
  apiVersion: "2024-06-20",
});

const WEBHOOK_SECRET = Deno.env.get("STRIPE_WEBHOOK_SECRET") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const RESEND_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const FROM = Deno.env.get("ALERT_FROM") ?? "EquityWatch <alerts@shouldisellyet.com>";
const SITE = "https://shouldisellyet.com";

// ————— Supabase REST helpers (service role) —————

async function sb(path: string, init: RequestInit) {
  const r = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    ...init,
    headers: {
      apikey: SERVICE_KEY,
      Authorization: `Bearer ${SERVICE_KEY}`,
      "Content-Type": "application/json",
      Prefer: "return=representation",
      ...(init.headers ?? {}),
    },
  });
  if (!r.ok) console.error("supabase error", path, r.status, await r.text());
  return r;
}

// ————— Email —————

async function sendEmail(to: string, subject: string, html: string) {
  if (!RESEND_KEY) return;
  const r = await fetch("https://api.resend.com/emails", {
    method: "POST",
    headers: { Authorization: `Bearer ${RESEND_KEY}`, "Content-Type": "application/json" },
    body: JSON.stringify({ from: FROM, to: [to], subject, html }),
  });
  if (!r.ok) console.error("resend error", r.status, await r.text());
}

function welcomeMonitorEmail(zip: string) {
  return {
    subject: `🚦 Your EquityWatch alert for ${zip} is live`,
    html: `
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">🚦 EquityWatch</p>
  <h1 style="font-size:26px;margin:6px 0 12px">Your alert is live.</h1>
  <p style="font-size:16px;line-height:1.6">You've set up an alert for <b>${zip}</b>. The early-warning data — supply, prices, price cuts, time to sell — is checked on every release, and the moment your ZIP's verdict changes color, you'll get an email like this one. No news is good news.</p>
  <p style="font-size:16px;line-height:1.6">Your full EquityWatch property report is included — generate it right now with your address, home value estimate, and mortgage balance. It takes 20 seconds and you can save it as a PDF.</p>
  <p style="margin:24px 0"><a href="${SITE}/my-report.html?zip=${zip}" style="background:#1f3a5f;color:#fff;padding:13px 24px;border-radius:10px;text-decoration:none;font-family:Arial,sans-serif;font-size:15px;font-weight:bold">Generate my report →</a></p>
  <p style="font-size:12px;color:#98a2b3;line-height:1.5">Cancel anytime — just reply "cancel" or use the link in any Stripe billing email. Data from Redfin, a national real estate brokerage (redfin.com). Not financial advice.</p>
</div>`,
  };
}

function welcomeReportEmail(zip: string) {
  return {
    subject: `Your EquityWatch report is on the way (${zip})`,
    html: `
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">🚦 EquityWatch</p>
  <h1 style="font-size:26px;margin:6px 0 12px">Got it — one report coming up.</h1>
  <p style="font-size:16px;line-height:1.6">Generate it right now — enter your address, your home value estimate, and your approximate mortgage balance, and your report appears in 20 seconds. Save it as a PDF, regenerate it anytime.</p>
  <p style="margin:24px 0"><a href="${SITE}/my-report.html?paid=1&zip=${zip}" style="background:#1f3a5f;color:#fff;padding:13px 24px;border-radius:10px;text-decoration:none;font-family:Arial,sans-serif;font-size:15px;font-weight:bold">Generate my report →</a></p>
  <p style="font-size:16px;line-height:1.6">Want to stay ahead after this report? Set up an EquityWatch alert — same price monthly — and you'll hear the moment ${zip} changes color.</p>
  <p style="font-size:12px;color:#98a2b3;line-height:1.5">All sales final per our refund policy. Data from Redfin, a national real estate brokerage (redfin.com). Not financial advice.</p>
</div>`,
  };
}

// ————— Event handling —————

async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const email = session.customer_details?.email ?? "";
  if (!email) return console.error("no email on session", session.id);

  const addr = session.customer_details?.address;
  const zip = (addr?.postal_code ?? "").slice(0, 5);
  const address = [addr?.line1, addr?.city, addr?.state].filter(Boolean).join(", ");
  const plan = session.mode === "subscription" ? "monitor" : "report";

  // Activate an existing pending signup for this email, else insert fresh.
  const patch = await sb(
    `subscribers?email=eq.${encodeURIComponent(email)}&status=eq.pending`,
    {
      method: "PATCH",
      body: JSON.stringify({
        status: "active",
        plan,
        source: "stripe",
        ...(zip ? { zip } : {}),
        ...(address ? { address } : {}),
      }),
    },
  );
  const updated = patch.ok ? await patch.json() : [];
  if (!Array.isArray(updated) || updated.length === 0) {
    await sb("subscribers", {
      method: "POST",
      body: JSON.stringify({
        email,
        zip: /^\d{5}$/.test(zip) ? zip : "00000",
        address,
        plan,
        status: "active",
        source: "stripe",
      }),
    });
  }

  const mail = plan === "monitor"
    ? welcomeMonitorEmail(zip || "your ZIP")
    : welcomeReportEmail(zip || "your ZIP");
  await sendEmail(email, mail.subject, mail.html);
  console.log(`activated ${email} (${plan}, ${zip})`);
}

async function handleSubscriptionDeleted(sub: Stripe.Subscription) {
  // Look up the customer's email via the expandable field if present.
  const email = (sub as unknown as { customer_email?: string }).customer_email;
  if (email) {
    await sb(`subscribers?email=eq.${encodeURIComponent(email)}&plan=eq.monitor`, {
      method: "PATCH",
      body: JSON.stringify({ status: "canceled" }),
    });
    console.log(`canceled ${email}`);
    return;
  }
  console.log("subscription deleted; no email on event — cancel manually if needed:", sub.id);
}

// ————— HTTP entry —————

Deno.serve(async (req) => {
  const sig = req.headers.get("stripe-signature");
  if (!sig || !WEBHOOK_SECRET) return new Response("missing signature", { status: 400 });

  let event: Stripe.Event;
  try {
    event = await stripe.webhooks.constructEventAsync(await req.text(), sig, WEBHOOK_SECRET);
  } catch (e) {
    console.error("signature verification failed:", e);
    return new Response("bad signature", { status: 400 });
  }

  try {
    switch (event.type) {
      case "checkout.session.completed":
        await handleCheckoutCompleted(event.data.object as Stripe.Checkout.Session);
        break;
      case "customer.subscription.deleted":
        await handleSubscriptionDeleted(event.data.object as Stripe.Subscription);
        break;
      default:
        // Acknowledge everything else so Stripe doesn't retry.
        break;
    }
  } catch (e) {
    console.error("handler error:", e);
    // Still 200: we log and fix rather than trigger endless Stripe retries.
  }
  return new Response(JSON.stringify({ received: true }), {
    headers: { "Content-Type": "application/json" },
  });
});
