# Stripe — what the operator has to do by hand

Everything in this file is dashboard work. None of it can be scripted from
this repo: Payment Links, coupons and the address-collection toggle live in
Stripe, and the site only holds the resulting URLs.

Prices in code: [`web/prices.js`](../web/prices.js) (single source of truth).
Links in code: the `LINKS` object in [`web/subscribe.html`](../web/subscribe.html).

---

## 1. Reprice — complete ✅ (2026-08-03/04)

All four paths are live and were verified against their own checkout pages
(price, interval, no address fields, params intact):

| Offer | Charges | Verified rendering |
| --- | --- | --- |
| One-time report | **$5.99** one-time | "$5.99" |
| MyMarketCheckup monthly | **$3.99**/month | "$3.99 per month" |
| MyMarketCheckup annual | **$29.00**/year | "$29.00 per year · $2.42 / month billed annually" |
| Upgrade, first year | **$23.01** | "$23.01 · Then $29.00 per year starting next year" |

The upgrade path is the **$29 annual link + `?prefilled_promo_code=UPGRADEPATH`**
("Upgrade Path" coupon: $5.99 off, duration Once). The $0.01 against the
advertised $23 is UNDER, never over.

**If the coupon, its code, or the annual link is ever edited in Stripe,
re-verify** that the upgrade URL still renders $23.01 — a coupon resized or
detached fails silently to full price. (The old flat-$10 `UPGRADE10` coupon
is superseded; if it still exists, delete it so nobody reuses it against the
$29 link, where it would charge $19.)

### Regression checks after any Stripe-side edit

- `subscribe.html?plan=report` → Stripe shows **$5.99**
- `subscribe.html?plan=monitor` → **$29/yr** (annual is the default)
- `subscribe.html?plan=monitor&billing=monthly` → **$3.99/mo**
- `subscribe.html?plan=monitor&upgrade=report-credit` → first charge
  **$23.01**, renewing at $29

---

## 2. Address collection — off ✅

The site captures a structured address **once**, on the subscribe page, before
checkout (see [`web/address.js`](../web/address.js)). Stripe asking again is
the duplicate the customer notices — and its answer is the *billing* address,
which is often a different place from the property being watched.

Verified off on all three live links: their checkout pages render no address,
city, state or postal fields. Do the same on any new link (**Edit → Options →
uncheck "Collect customers' addresses"**, shipping and billing both).

**Phone is still collected** on all three — a separate toggle, and one nothing
on the site asks for. It isn't a duplicate, so it isn't wrong; it is one more
field between a customer and a $5.99 purchase. Worth turning off unless you
want phone numbers.

**Leave the postal code inside the card field alone.** That is Stripe's own
AVS anti-fraud check on the card, not our address capture. It is a different
field for a different purpose and suppressing it would weaken fraud
protection for no gain.

### Why this is safe

The webhook does not depend on Stripe's address. It reads the property ZIP
from `client_reference_id` (which `subscribe.html` sets), and the structured
address is already on the pending `subscribers` row before checkout starts.
Stripe's address is only used on one fallback path — a purchase with no
pending row, i.e. someone who reached a Payment Link directly — and there,
`postal_code` may simply be absent; the row is written with a `00000` ZIP
sentinel for manual follow-up, exactly as before.

---

## 3. Webhook events

`checkout.session.completed` and `customer.subscription.deleted` are already
wired to `supabase/functions/stripe-webhook`. If you create *new* Payment
Links (step 1), confirm the same webhook endpoint still receives their
events — it is account-wide, so it should, but check one live test payment.

---

## 4. Deploy order — SQL before function

The webhook now depends on two migrations. **Run the SQL first.** Without
`stripe_session_id` every delivery of the same event looks like a new
purchase, which is exactly the duplicate-row bug the migration fixes.

```bash
# 1. Supabase SQL Editor: paste and run, in order
#    supabase/schema-v6.sql   (structured address)
#    supabase/schema-v7.sql   (stripe_session_id, report_email_sent_at)

# 2. then the functions
npx supabase functions deploy stripe-webhook
npx supabase functions deploy verify-access
npx supabase functions deploy save-address
```

`save-address` is new. Set **Enforce JWT verification → off** for it, as with
`verify-access` and `save-watch`: it authenticates with the report access
token, not a Supabase JWT.

`RESEND_API_KEY` must be set in **Edge Functions → Secrets** or no email
sends. That case is logged loudly and the send is left *unclaimed*, so the
mail goes out on a later retry rather than being silently marked delivered.

### Checking the once-only behaviour on live

In the Stripe dashboard, open the webhook endpoint, find a
`checkout.session.completed` delivery and hit **Resend**. Expected:

- the `subscribers` table gains **no** new row
- the customer gets **no** second email
- the function log prints `post-purchase email already sent for cs_… — skipping`
