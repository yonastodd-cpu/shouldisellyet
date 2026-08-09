// ShouldISellYet — Stripe webhook → auto-activate subscribers + welcome email.
//
// Deploy as a Supabase Edge Function named `stripe-webhook`.
// Secrets required (Supabase dashboard → Edge Functions → Secrets):
//   STRIPE_WEBHOOK_SECRET   from the Stripe webhook endpoint you create
//   RESEND_API_KEY          from resend.com
//   ALERT_FROM              e.g. "ShouldISellYet <support@shouldisellyet.com>" (optional)
//                           MUST be a real mailbox: every email here invites a
//                           reply. alerts@ was never one and Resend suppressed it.
// SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are injected automatically.
//
// Stripe events handled:
//   checkout.session.completed        → upsert subscriber as active (+ access email)
//   customer.subscription.created     → store renewal date + billing interval
//   customer.subscription.updated     → same, so a plan change stays accurate
//   customer.subscription.deleted     → mark subscriber canceled
//
// The two subscription events must be enabled on the Stripe webhook endpoint,
// or current_period_end is never recorded and the renewal reminder has nothing
// to read.
//
// Requires schema-v6 (address_* columns) and schema-v7 (stripe_session_id,
// report_email_sent_at). Deploy the SQL BEFORE this function: without
// stripe_session_id every delivery looks new, which is the duplicate-row bug
// v7 exists to fix.

import Stripe from "npm:stripe@17";

const stripe = new Stripe("sk_placeholder_not_used_for_verification", {
  apiVersion: "2024-06-20",
});

const WEBHOOK_SECRET = Deno.env.get("STRIPE_WEBHOOK_SECRET") ?? "";
const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const RESEND_KEY = Deno.env.get("RESEND_API_KEY") ?? "";
const FROM = Deno.env.get("ALERT_FROM") ?? "ShouldISellYet <support@shouldisellyet.com>";
const SITE = "https://shouldisellyet.com";

// ————— Postal address (CAN-SPAM) —————
// Any message carrying promotional content must show a valid physical mailing
// address. Exactly one of ours does: the report-access email's upsell block.
//
// ⚠️ PLACEHOLDER. Set MAILING_ADDRESS in the Edge Function secrets to a real
// registered-agent address or PO box. Until it is set, the upsell block is
// SUPPRESSED rather than sent without an address — shipping promotional mail
// with a fake address is the violation itself, and a missing upsell costs a
// conversion while a bad address costs a penalty.
const MAILING_ADDRESS = Deno.env.get("MAILING_ADDRESS") ?? "";

// ————— Prices —————
// An edge function can't import web/prices.js (different runtime, not served
// from this origin), so these are a deliberate mirror, not a second source of
// truth. pipeline/test_prices.py parses both files and fails the build if they
// disagree — so change web/prices.js first, then match it here.
const PRICES = {
  ANNUAL: 29,
  MONTHLY: 3.99,
  REPORT: 5.99,
  UPGRADE: 23,
  UPGRADE_WINDOW_DAYS: 30,
};
const usd = (n: number) => "$" + (Number.isInteger(n) ? n : n.toFixed(2));

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

/** Rows from a request, or [] on any failure. */
async function rows(r: Response): Promise<Record<string, unknown>[]> {
  if (!r.ok) return [];
  try {
    const j = await r.json();
    return Array.isArray(j) ? j : [];
  } catch (_e) { return []; }
}

async function sbGet(path: string) {
  return await rows(await sb(path, { method: "GET" }));
}

const enc = encodeURIComponent;

// ————— Email —————

/** true only if Resend accepted the message — the caller uses this to decide
 *  whether the "already sent" mark it placed should stand or be released. */
async function sendEmail(to: string, subject: string, html: string): Promise<boolean> {
  if (!RESEND_KEY) {
    // TODO: set RESEND_API_KEY in the Edge Function secrets. Returning false
    // (rather than pretending success) keeps the send unclaimed, so nothing is
    // silently marked delivered while email is unconfigured.
    console.error("RESEND_API_KEY not set — no email sent to", to);
    return false;
  }
  try {
    const r = await fetch("https://api.resend.com/emails", {
      method: "POST",
      headers: { Authorization: `Bearer ${RESEND_KEY}`, "Content-Type": "application/json" },
      body: JSON.stringify({ from: FROM, to: [to], subject, html }),
    });
    if (!r.ok) { console.error("resend error", r.status, await r.text()); return false; }
    return true;
  } catch (e) {
    console.error("resend threw", e);
    return false;
  }
}

// ————— Links —————
// The access link is the token, not the email. `access_token` is a v4 UUID —
// ~122 bits of randomness, unguessable, and revocable by nulling one column.
// The brief allowed a signed email token instead; a bare or signed email in a
// URL is strictly worse here (emails are guessable, enumerable, and can't be
// revoked without changing the customer's address), so the existing token
// stands and no signing was added.
function reportLink(zip: string, token: string, utm = "") {
  const u = utm ? `&utm_source=${utm}` : "";
  return `${SITE}/my-report.html?token=${token}&zip=${zip}${u}`;
}

function unsubscribeLink(token: string) {
  return `${SUPABASE_URL}/functions/v1/unsubscribe?token=${token}`;
}

function upgradeLink(zip: string, utm = "") {
  const z = /^\d{5}$/.test(zip) ? `&zip=${zip}` : "";
  const u = utm ? `&utm_source=${utm}` : "";
  return `${SITE}/subscribe.html?plan=monitor&upgrade=report-credit${z}${u}`;
}

/** Whole days left in the upgrade window, floored at 0. */
function daysRemaining(purchasedAt: string | null): number {
  if (!purchasedAt) return PRICES.UPGRADE_WINDOW_DAYS;
  const t = Date.parse(purchasedAt);
  if (!Number.isFinite(t)) return PRICES.UPGRADE_WINDOW_DAYS;
  const elapsed = Math.floor((Date.now() - t) / 86_400_000);
  return Math.max(0, PRICES.UPGRADE_WINDOW_DAYS - elapsed);
}

const esc = (s: string) =>
  s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

// ————— Preheader —————
// The inbox shows three things: sender, subject, and then whatever text it
// scrapes first from the body. Without this, that third slot got the visible
// brand header — so a row read "ShouldISellYet · Your alert for 20874 is
// live · MyMarketCheckup Your alert is live…", saying the name three times
// and the news once.
//
// This block is hidden in the rendered email but IS the first text a client
// finds, so it becomes the preview line. The trailing run of zero-width
// non-joiners is the standard trick to stop clients padding the preview with
// whatever markup follows.
const preheader = (text: string) =>
  `<div style="display:none;font-size:1px;color:#faf8f4;line-height:1px;` +
  `max-height:0;max-width:0;opacity:0;overflow:hidden">${text}` +
  "&#8204;&nbsp;".repeat(60) + "</div>";

function welcomeMonitorEmail(zip: string, token: string) {
  const link = reportLink(zip, token);
  return {
    // Subject says WHAT and WHERE, without the brand — the sender field
    // already carries that, and repeating it spends the only characters
    // that fit on a phone.
    subject: `${zip} is now being watched`,
    html: `${preheader(
      `Your report is ready inside. From here on, we only email ${zip} when the market actually moves.`)}
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">🚦 MyMarketCheckup</p>
  <h1 style="font-size:26px;margin:6px 0 12px">You're watching ${zip}.</h1>
  <p style="font-size:16px;line-height:1.6">From now on we check the early-warning data for your ZIP on every release — supply, prices, price cuts, time to sell — and email you the moment the picture changes. Most months you'll hear nothing, and that is the good outcome.</p>
  <p style="font-size:16px;line-height:1.6">Your full property report is ready now. Open it below, add your home value and mortgage balance, and it builds in seconds — save it as a PDF, come back anytime.</p>
  <p style="margin:24px 0"><a href="${link}" style="background:#1f3a5f;color:#fff;padding:13px 24px;border-radius:10px;text-decoration:none;font-family:Arial,sans-serif;font-size:15px;font-weight:bold">Open my report →</a></p>
  <p style="font-size:12.5px;color:#5c6673;line-height:1.5"><b>Bookmark that link</b> — it's your private access to the report and it works only for you.</p>
  <p style="font-size:12px;color:#98a2b3;line-height:1.5;margin-top:18px">Renews automatically until you cancel. <b>Cancel anytime yourself</b> — open your report above and use "Manage or cancel subscription", or use the link in any Stripe billing email. Canceling stops future charges; your access runs to the end of the period you've paid for. Not financial advice.</p>
</div>`,
  };
}

// The post-purchase report email.
//
// No market figures appear in it, so there is no Redfin citation — the
// attribution rule attaches to displayed data, and adding it here would be
// noise on a page that shows none. See docs/ATTRIBUTION.md.
function welcomeReportEmail(zip: string, token: string, city: string,
                           purchasedAt: string | null, optedOut = false) {
  const link = reportLink(zip, token, "report_email");
  const upgrade = upgradeLink(zip, "report_email");
  const days = daysRemaining(purchasedAt);
  const place = city ? `${esc(city)} (${zip})` : zip;
  const btn = "background:#1f3a5f;color:#fff;padding:13px 24px;border-radius:10px;" +
    "text-decoration:none;font-family:Arial,sans-serif;font-size:15px;font-weight:bold;display:inline-block";

  // Two branches. Normally the report price is credited toward the annual
  // plan; if the window has already lapsed by send time — a webhook that sat
  // in a retry queue for a month, or a hand-replayed event — the credit is
  // gone and promising it would be a lie the checkout would then refuse to
  // honour. That case gets the plain annual pitch instead.
  // The upsell is the ONLY promotional content this system sends. It is
  // dropped entirely when the reader has opted out, or when no mailing address
  // is configured — see MAILING_ADDRESS. Everything else in this email is the
  // report they paid for, and still sends either way.
  const promo = !optedOut && MAILING_ADDRESS.trim() !== "";
  const offer = days > 0
    ? `<p style="font-size:16px;line-height:1.6">Because you bought this report, your <b>${usd(PRICES.REPORT)} counts toward the annual plan</b>: upgrade in the next ${days} day${days === 1 ? "" : "s"} for <b>${usd(PRICES.UPGRADE)}</b> (normally ${usd(PRICES.ANNUAL)}/yr).</p>`
    : `<p style="font-size:16px;line-height:1.6">MyMarketCheckup is <b>${usd(PRICES.ANNUAL)}/yr</b> — ${usd(PRICES.ANNUAL / 12)}/mo, billed annually — or ${usd(PRICES.MONTHLY)}/mo billed monthly. Cancel anytime.</p>`;

  return {
    subject: `Your ${place} report is ready`,
    html: `${preheader(
      `Open it on any device — the four market signals for ${zip}, your value trend, equity and walk-away number.`)}
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">🚦 MyMarketCheckup</p>
  <p style="font-size:16px;line-height:1.6">Here's your link — it works on any device and it's yours to keep:</p>
  <p style="margin:22px 0"><a href="${link}" style="${btn}">View my report →</a></p>
  <p style="font-size:16px;line-height:1.6">It covers ${place}: the four market signals, your home's value trend, and — if you've added your numbers — your equity, walk-away number, and what today's rates mean for you.</p>
  ${promo ? `
  <p style="font-size:16px;line-height:1.6">One thing a report can't do is watch. Markets turn quietly — inventory creeps up, price cuts spread — and the whole point is hearing it early. <b>MyMarketCheckup</b> monitors ${zip} continuously and emails you the moment the verdict changes, plus a refreshed report monthly.</p>
  ${offer}
  <p style="margin:22px 0"><a href="${upgrade}" style="${btn}">Turn on instant notifications →</a></p>` : ""}
  <p style="font-size:12.5px;color:#5c6673;line-height:1.5"><b>Bookmark your report link</b> — it's your private access and it works only for you.</p>
  <p style="font-size:16px;line-height:1.6">Questions? Just reply.<br>— ShouldISellYet.com</p>
  <p style="font-size:12px;color:#98a2b3;line-height:1.5;margin-top:18px">General market information, not financial, legal, or real-estate advice, and not an appraisal of your home. All sales final per our <a href="${SITE}/refunds.html" style="color:#98a2b3">refund policy</a>.</p>${promo ? `
  <p style="font-size:12px;color:#98a2b3;line-height:1.5;margin-top:14px">${esc(MAILING_ADDRESS)}<br>
  Don't want upgrade offers? <a href="${unsubscribeLink(token)}" style="color:#98a2b3">Unsubscribe from promotional email</a>. You'll still get your report link, your ZIP's alerts, and any billing notices.</p>` : ""}
</div>`,
  };
}

// ————— Event handling —————

const ROW_COLS = "id,zip,access_token,address_city,created_at,report_email_sent_at,marketing_opt_out";

async function handleCheckoutCompleted(session: Stripe.Checkout.Session) {
  const email = session.customer_details?.email ?? "";
  if (!email) return console.error("no email on session", session.id);

  const addr = session.customer_details?.address;
  // Prefer the ZIP the visitor was looking at (passed as client_reference_id);
  // fall back to the billing-address postal code.
  const refZip = (session.client_reference_id ?? "").replace(/\D/g, "").slice(0, 5);
  const zip = /^\d{5}$/.test(refZip) ? refZip : (addr?.postal_code ?? "").slice(0, 5);
  const plan = session.mode === "subscription" ? "monitor" : "report";

  // The customer id has to be captured HERE. handleSubscriptionUpserted also
  // writes it, but it finds its row BY that same column — so on a first
  // subscription there is nothing to match and it never gets written at all.
  // That chicken-and-egg left every subscriber with a null stripe_customer_id,
  // which is the only thing portal-session looks up: the "manage or cancel"
  // button answered "we don't see an active subscription" for everyone, and
  // self-serve cancellation silently did not exist. The checkout session
  // carries the id outright, so taking it here breaks the cycle.
  //
  // Subscription mode only. Stripe mints a customer for one-time payments too,
  // and storing it would send report buyers into a billing portal with nothing
  // in it, replacing an honest "a one-time report has nothing to cancel" with
  // a confusing empty page.
  const customerId = typeof session.customer === "string"
    ? session.customer
    : session.customer?.id;
  const subCustomer = session.mode === "subscription" && customerId
    ? { stripe_customer_id: customerId }
    : {};

  // ——— 1. Is this delivery a retry of a purchase we already handled? ———
  // Stripe retries until it gets a 2xx and can deliver the same event twice
  // regardless. Keyed on the session id, a retry is recognisable; keyed on
  // anything we generate ourselves it isn't.
  let row = (await sbGet(
    `subscribers?select=${ROW_COLS}&stripe_session_id=eq.${enc(session.id)}&limit=1`))[0];

  if (!row) {
    const token = crypto.randomUUID();   // report access token
    // ——— 2. Activate the pending signup this purchase belongs to ———
    // One specific row, found first, rather than a filtered bulk PATCH: with
    // two pending rows for the same email a bulk update would try to write
    // the same session id to both and the unique index would reject the whole
    // statement, dropping us into the insert branch and creating a third row.
    const pending = (await sbGet(
      `subscribers?select=id&email=eq.${enc(email)}&status=eq.pending` +
      `&order=created_at.desc&limit=1`))[0];

    if (pending) {
      // The address columns are NOT touched here, on purpose. The pending row
      // already holds the structured address the customer entered on the
      // subscribe page — the property they want watched. Stripe's is the
      // BILLING address, often a different place (a second home, a PO box, a
      // parent's house). Overwriting would silently retarget the report.
      row = (await rows(await sb(`subscribers?id=eq.${enc(String(pending.id))}`, {
        method: "PATCH",
        body: JSON.stringify({
          status: "active", plan, source: "stripe",
          confirmed_at: new Date().toISOString(),   // payment verifies the address (schema-v19)
          access_token: token, stripe_session_id: session.id,
          // Payment confirmation time, distinct from the pending row's
          // created_at — the funnel windows on this (schema-v13).
          purchased_at: new Date().toISOString(),
          ...subCustomer,
          ...(zip ? { zip } : {}),
        }),
      })))[0];
    }

    if (!row) {
      // No pending row — the customer reached Stripe some other way, so the
      // billing address is genuinely all we have. Map it into the structured
      // columns rather than the deprecated freeform one, so the report reads
      // it through the same path as everything else. The report page lets them
      // correct it, and the ZIP mismatch guard catches a billing/property split.
      row = (await rows(await sb("subscribers", {
        method: "POST",
        body: JSON.stringify({
          email,
          zip: /^\d{5}$/.test(zip) ? zip : "00000",
          address_street: addr?.line1 ?? null,
          address_unit: addr?.line2 ?? null,
          address_city: addr?.city ?? null,
          address_state: addr?.state ?? null,
          plan, status: "active", source: "stripe",
          confirmed_at: new Date().toISOString(),   // payment verifies the address (schema-v19)
          access_token: token, stripe_session_id: session.id,
          purchased_at: new Date().toISOString(),
          ...subCustomer,
        }),
      })))[0];

      // The insert can legitimately fail on the unique session index — a
      // concurrent delivery of the same event won the race. That's success,
      // not an error: re-read its row and carry on to the send claim, which
      // will correctly decide the email is already handled.
      if (!row) {
        row = (await sbGet(
          `subscribers?select=${ROW_COLS}&stripe_session_id=eq.${enc(session.id)}&limit=1`))[0];
      }
    }
  }

  if (!row) return console.error("could not resolve a subscriber row for", session.id);

  // ——— 3. Claim the send, THEN send ———
  // A row existing doesn't mean its email went out (Resend could have been
  // down on the first delivery), so this is a separate conditional update:
  // whoever flips report_email_sent_at from null sends, everyone else skips.
  //
  // Claim-before-send is the right order — claiming after would leave a window
  // where a concurrent delivery sends a second copy. The cost is that a failed
  // send would look delivered, so the claim is RELEASED below if Resend
  // refuses. Net effect: exactly-once when the send works, and at-least-once
  // when it doesn't, which is the correct way round. Never-sent is a worse
  // outcome for the customer than a rare duplicate.
  const rowId = enc(String(row.id));
  const claimed = await rows(await sb(
    `subscribers?id=eq.${rowId}&report_email_sent_at=is.null`, {
      method: "PATCH",
      body: JSON.stringify({ report_email_sent_at: new Date().toISOString() }),
    }));
  if (!claimed.length) {
    console.log(`post-purchase email already sent for ${session.id} — skipping`);
    return;
  }

  const rowZip = String(row.zip ?? zip ?? "");
  const token = String(row.access_token ?? "");
  const mail = plan === "monitor"
    ? welcomeMonitorEmail(rowZip || "your ZIP", token)
    : welcomeReportEmail(rowZip || "your ZIP", token,
                         String(row.address_city ?? ""),
                         (row.created_at as string) ?? null,
                         row.marketing_opt_out === true);

  if (await sendEmail(email, mail.subject, mail.html)) {
    console.log(`activated ${email} (${plan}, ${rowZip})`);
  } else {
    await sb(`subscribers?id=eq.${rowId}`, {
      method: "PATCH",
      body: JSON.stringify({ report_email_sent_at: null }),
    });
    console.error(`send failed for ${session.id} — claim released, retry will resend`);
  }
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


/** Store the renewal date and billing interval from the subscription payload.
 *
 *  Read off customer.subscription.created / .updated rather than fetched from
 *  the Stripe API on purpose: those events already carry current_period_end,
 *  so the renewal reminder stays accurate WITHOUT this function needing a
 *  Stripe secret key. The key it holds is a placeholder used only for
 *  signature verification.
 *
 *  Matched by stripe_customer_id first and email second. The customer id is
 *  stable; an email can change, and a subscription event carries no email at
 *  all unless expanded — so the id is the reliable key and the email lookup is
 *  only a fallback for rows written before the id was recorded.
 *
 *  Returns false when no row could be matched. Stripe usually delivers
 *  customer.subscription.created BEFORE checkout.session.completed, so on a
 *  first subscription this genuinely can arrive before the row it belongs to
 *  exists. Swallowing that loses current_period_end until the NEXT
 *  subscription event — a full year away on an annual plan — which silently
 *  disables the renewal reminder for exactly the customers it protects. The
 *  caller turns false into a non-2xx so Stripe redelivers it, by which time
 *  the checkout handler has written the row.
 */
async function handleSubscriptionUpserted(sub: Stripe.Subscription): Promise<boolean> {
  // Two homes for the period end, depending on the account's Stripe API
  // version: classic top-level current_period_end, or (2025+ versions) on
  // each subscription item. Found the hard way: a real subscription stored
  // billing_interval but a NULL current_period_end — the event carried the
  // date only on the item. Check both, prefer the classic field.
  const item0 = sub.items?.data?.[0] as unknown as { current_period_end?: number } | undefined;
  const periodEnd =
    (sub as unknown as { current_period_end?: number }).current_period_end ??
    item0?.current_period_end;
  const interval = sub.items?.data?.[0]?.price?.recurring?.interval;   // "year" | "month"
  const patch: Record<string, unknown> = {
    stripe_subscription_id: sub.id,
    ...(periodEnd ? { current_period_end: new Date(periodEnd * 1000).toISOString() } : {}),
    ...(interval ? { billing_interval: interval === "year" ? "annual" : "monthly" } : {}),
  };
  const customerId = typeof sub.customer === "string" ? sub.customer : sub.customer?.id;
  if (customerId) {
    patch.stripe_customer_id = customerId;
    const byId = await rows(await sb(
      `subscribers?stripe_customer_id=eq.${enc(customerId)}`,
      { method: "PATCH", body: JSON.stringify(patch) }));
    if (byId.length) {
      console.log(`subscription ${sub.id}: period end + interval stored (by customer id)`);
      return true;
    }
  }
  const email = (sub as unknown as { customer_email?: string }).customer_email;
  if (!email) {
    console.log(`subscription ${sub.id}: no customer row matched and no email on the event`);
    return false;
  }
  const byEmail = await rows(await sb(`subscribers?email=eq.${enc(email)}&plan=eq.monitor`,
                                      { method: "PATCH", body: JSON.stringify(patch) }));
  if (!byEmail.length) {
    console.log(`subscription ${sub.id}: email ${email} matched no monitor row`);
    return false;
  }
  console.log(`subscription ${sub.id}: period end + interval stored (by email)`);
  return true;
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

  // Set when a handler could not find the row its event belongs to — see
  // handleSubscriptionUpserted. The only case we deliberately ask Stripe to
  // redeliver, because waiting is the actual fix.
  let retryLater = false;

  try {
    switch (event.type) {
      case "checkout.session.completed":
        await handleCheckoutCompleted(event.data.object as Stripe.Checkout.Session);
        break;
      case "customer.subscription.created":
      case "customer.subscription.updated":
        retryLater = !await handleSubscriptionUpserted(event.data.object as Stripe.Subscription);
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

  // The one deliberate exception to the 200-always rule. A subscription event
  // that arrived before its checkout row is not an error we can fix by logging
  // — the data simply is not there yet, and Stripe's backoff redelivery is the
  // right and only repair. Bounded by Stripe itself: it retries for ~3 days
  // and then stops, so a subscription created outside this flow (straight from
  // the dashboard, say) costs a few logged retries rather than a lost renewal
  // date on a real customer.
  if (retryLater) {
    return new Response(JSON.stringify({ received: false, reason: "row not ready" }), {
      status: 503,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(JSON.stringify({ received: true }), {
    headers: { "Content-Type": "application/json" },
  });
});
