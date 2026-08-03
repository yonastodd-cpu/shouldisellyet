# Stripe — what the operator has to do by hand

Everything in this file is dashboard work. None of it can be scripted from
this repo: Payment Links, coupons and the address-collection toggle live in
Stripe, and the site only holds the resulting URLs.

Prices in code: [`web/prices.js`](../web/prices.js) (single source of truth).
Links in code: the `LINKS` object in [`web/subscribe.html`](../web/subscribe.html).

---

## 1. Reprice — BLOCKS THE ANNOUNCEMENT

As of the 2026-08-03 reprice **every live Payment Link still charges the old
amount**. The site advertises the new ladder; Stripe charges the old one.

| What the site says | What Stripe charges | Gap | Priority |
| --- | --- | --- | --- |
| **$5.99** one-time report | $9.99 | **overcharges $4.00** | **Fix first** |
| **$29**/yr EquityWatch | $39/yr | overcharges $10.00 | Fix |
| **$3.99**/mo EquityWatch | $5.99/mo | overcharges $2.00 | Fix |
| **$23** upgrade (first year) | $29 | overcharges $6.00 | Fix |

**Every one of these overcharges.** A customer who clicks "$5.99" and is
billed $9.99 has a valid chargeback and a screenshot, so nothing about the new
pricing should be announced or emailed until this table is empty.

### Create these four, in live mode

1. **One-time report — $5.99**, one-time payment.
2. **EquityWatch monthly — $3.99/mo**, recurring monthly.
3. **EquityWatch annual — $29/yr**, recurring yearly.
4. **The upgrade path — $23 first year.** Two ways; pick one:
   - *Coupon* (matches how it works today): on the new $29 annual link, enable
     **Allow promotion codes**, and create a **once**-duration coupon for a
     flat **$5.99 off**. First charge becomes **$23.01**, renewals $29. Then
     set `annual_upgrade` to the annual link plus
     `?prefilled_promo_code=<CODE>`.
   - *Dedicated link*: a separate $23 first-year price. Cleaner arithmetic
     ($23.00, not $23.01), one more object to maintain.

   The existing **UPGRADE10** coupon is a flat $10, sized for the old
   $39 → $29. Against a new $29 link it would charge **$19** — undercharging
   by $4. Resize it or stop using it; do not leave it pointed at the new link.

Then paste all four into `LINKS` in `web/subscribe.html` and delete the ⚠️
block above it.

### After pasting, check

- `subscribe.html?plan=report` → Stripe shows **$5.99**
- `subscribe.html?plan=monitor` → **$29/yr** (annual is the default)
- `subscribe.html?plan=monitor&billing=monthly` → **$3.99/mo**
- `subscribe.html?plan=monitor&upgrade=report-credit` → first charge **$23.01**
  (or $23.00 on a dedicated link), renewing at $29

---

## 2. Turn OFF address collection on every Payment Link

The site now captures a structured address **once**, on the subscribe page,
before checkout (see [`web/address.js`](../web/address.js)). Stripe asking
again is the duplicate the customer notices — and its answer is the *billing*
address, which is often a different place from the property being watched.

For **each** of the four links: **Payment Links → the link → Edit → Options →
uncheck "Collect customers' addresses"** (both shipping and billing).

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
