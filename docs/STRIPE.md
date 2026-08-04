# Stripe — what the operator has to do by hand

Everything in this file is dashboard work. None of it can be scripted from
this repo: Payment Links, coupons and the address-collection toggle live in
Stripe, and the site only holds the resulting URLs.

Prices in code: [`web/prices.js`](../web/prices.js) (single source of truth).
Links in code: the `LINKS` object in [`web/subscribe.html`](../web/subscribe.html).

---

## 1. Reprice — three of four done

Repriced 2026-08-03. Three links are live and verified against their own
checkout pages (price, interval, and no address fields):

| Offer | Charges | Status |
| --- | --- | --- |
| One-time report | **$5.99** one-time | ✅ live |
| EquityWatch monthly | **$3.99**/month | ✅ live |
| EquityWatch annual | **$29.00**/year | ✅ live |
| Upgrade, first year | **$23** | ⛔ **no link yet** |

### The one that's left: the $23 upgrade

This is what a report buyer is offered — their $5.99 credited against the
annual plan, for 30 days after purchase.

`annual_upgrade` in `LINKS` is deliberately **empty**, because every wrong
value is worse than none:

| If it pointed at… | It would charge | |
| --- | --- | --- |
| old $39 link + `UPGRADE10` | $29 | over by $6 |
| new $29 link + `UPGRADE10` | $19 | under by $4 |
| new $29 link, no coupon | $29 | over by $6 |

Empty makes `go()` take its manual-follow-up branch: the signup saves as
`pending` with source `subscribe-page:annual-upgrade`, and the customer is
told we'll email their payment link and that they haven't been charged.

To finish it — **promotion codes are already enabled on the annual link**, so:

1. Product catalog → Coupons → New → **amount off $5.99**, duration **Once**.
2. Set `annual_upgrade` to the annual link + `?prefilled_promo_code=<CODE>`.
   First charge **$23.01**, renewals $29.

Or paste a dedicated flat **$23** first-year link instead ($23.00 exactly).

**`UPGRADE10` must not survive as-is** — it's a flat $10 built for the old
$39 → $29. Delete it, or resize it to $5.99 and reuse it above.

### After pasting, check

- `subscribe.html?plan=report` → Stripe shows **$5.99**
- `subscribe.html?plan=monitor` → **$29/yr** (annual is the default)
- `subscribe.html?plan=monitor&billing=monthly` → **$3.99/mo**
- `subscribe.html?plan=monitor&upgrade=report-credit` → first charge **$23.01**
  (or $23.00 on a dedicated link), renewing at $29

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
