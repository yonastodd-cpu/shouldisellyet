# ShouldISellYet.com 🚦

A free home-equity warning system. Enter a ZIP code, get a traffic-light verdict
(🟢 HOLD / 🟡 WATCH / 🔴 ACT) computed from public housing-market data, refreshed monthly.

## Architecture ($0/month)

```
Redfin Data Center (ZIP tracker, gzipped TSV)
        │  monthly, via GitHub Actions cron
        ▼
pipeline/fetch_data.py  ──►  pipeline/verdict.py (threshold engine)
        │
        ▼
web/data/               static JSON: index.json + zips/{STATE}.json + meta.json
        │
        ▼
web/index.html          static site (GitHub Pages / Netlify) — no backend
```

No servers, no database. The "app" is a static site plus a monthly batch job.

## Quick start

```bash
# 1. Run tests (no network needed)
pip install pytest
pytest pipeline/ -q

# 2. Generate real data (downloads ~gigabyte-scale TSV from Redfin; needs open network)
python pipeline/fetch_data.py --states MD,VA,DC     # start regional
python pipeline/fetch_data.py                        # or all US ZIPs

# 3. Preview
cd web && python -m http.server 8000                 # http://localhost:8000
```

If `web/data/` is missing (e.g. opening index.html as a file), the page falls
back to built-in demo ZIPs (20874, 20906) so it always works.

## Deploy free

1. Push this folder to a GitHub repo.
2. Settings → Pages → Source: **GitHub Actions**.
3. Actions tab → "Monthly data refresh & deploy" → **Run workflow** (first run).
4. Thereafter it refreshes data and redeploys on the 20th of each month automatically.

Point your domain (e.g. shouldisellyet.com) at GitHub Pages in Settings → Pages → Custom domain.

## Backend: Supabase (signups) + Resend (alerts)

**Supabase — subscriber storage (one-time setup):**
1. Supabase dashboard → SQL Editor → paste and run `supabase/schema.sql`.
2. Settings → API: copy the Project URL and the `anon` public key.
3. Paste both into `web/index.html` (`SUPABASE_URL`, `SUPABASE_ANON_KEY`).
   The anon key is safe to publish — RLS only permits INSERTs into `subscribers`.
   All signups (monitoring, waitlist) then land in the `subscribers` table.

**Resend — verdict-change alert emails:**
1. resend.com → Domains → add `shouldisellyet.com` and add the DNS records it
   shows (SPF/DKIM on a subdomain — these do NOT conflict with Titan email MX).
2. Create an API key.

**GitHub Actions secrets** (repo → Settings → Secrets and variables → Actions):
- `SUPABASE_URL` — the project URL
- `SUPABASE_SERVICE_KEY` — the service-role key (server-side only)
- `RESEND_API_KEY`

On every data refresh, `pipeline/notify_changes.py` diffs old vs. new verdicts
and emails each `monitor`-plan subscriber whose ZIP changed color. If secrets
aren't configured it dry-runs (prints what it would send) and never fails the build.

**Billing:** consumer prices live in `web/prices.js` (single source of truth:
$39/yr annual · $5.99/mo monthly · $9.99 one-time report · $29 first-year
upgrade for report buyers within 30 days). Create the matching Stripe Payment
Links and paste them into `LINKS` in `web/subscribe.html` — see the TODO there
for exactly which links are missing. Until a link exists, that option captures
the signup as `status='pending'` in Supabase for manual follow-up.

## Stripe webhook — automatic activation (no manual steps after payment)

`supabase/functions/stripe-webhook/index.ts` activates subscribers the moment
Stripe payment completes, and sends the welcome email via Resend:

- `checkout.session.completed` → finds the customer's pending signup by email
  and flips it to `active` (or inserts a new active row), pulling ZIP + address
  from Stripe's collected billing address. Sends a monitoring welcome or a
  report-purchase email depending on whether the checkout was a subscription.
- `customer.subscription.deleted` → marks the subscriber `canceled`.

**Setup (one time):**
1. Run `supabase/schema-v2.sql` in the Supabase SQL Editor.
2. Deploy the function — either `supabase functions deploy stripe-webhook`
   (CLI) or Supabase dashboard → Edge Functions → New function → name it
   `stripe-webhook` → paste `index.ts`. In the function's settings, disable
   "Enforce JWT verification" (Stripe can't send a Supabase JWT).
3. Add secrets (dashboard → Edge Functions → Secrets):
   `STRIPE_WEBHOOK_SECRET`, `RESEND_API_KEY`, optional `ALERT_FROM`.
4. In Stripe: Developers → Webhooks → **Add endpoint** →
   URL `https://<project-ref>.supabase.co/functions/v1/stripe-webhook` →
   select events `checkout.session.completed` and
   `customer.subscription.deleted` → create, then copy the **Signing secret**
   (whsec_…) into the `STRIPE_WEBHOOK_SECRET` secret from step 3.
5. On both Payment Links, make sure "Collect customers' addresses" is ON —
   that's a ZIP fallback (the primary ZIP now rides along as `client_reference_id`
   from the plan-details page).
6. **Confirmation page → redirect** on BOTH Payment Links: after payment, redirect to
   `https://shouldisellyet.com/my-report.html?paid=1` so buyers land on their report
   (the token in the welcome email is the durable private link).

## Report paywall (verify-access edge function)

The report page (`my-report.html`) will not render until it confirms a valid
access token. Tokens are minted per purchase by `stripe-webhook` (`access_token`
column) and delivered via the welcome email's "Open my report" link + the
post-checkout redirect.

Setup:
1. Run `supabase/schema-v3.sql` (adds the `access_token` column).
2. Deploy `supabase/functions/verify-access/index.ts` as edge function
   `verify-access`; disable "Enforce JWT verification". No secrets needed.
3. `my-report.html` already points `SUPABASE_URL` at your project — the gate is
   live once the function is deployed. (If the function is unreachable it *fails
   open* so a paying customer is never wrongly blocked; obscurity + token is the
   enforcement, not a hard wall.)

The plan-details page `subscribe.html` sits before Stripe: it describes exactly
what the plan includes and requires a Terms/refund-policy consent checkbox before
the "Continue to secure payment" button activates.
6. Test: Stripe webhook page → "Send test event" → `checkout.session.completed`;
   confirm a row appears/activates in the `subscribers` table and the function
   logs show `activated …`.

## Personal-number alerts (save-watch edge function + check_watches.py)

On the report page, a subscriber can watch their own walk-away number,
equity, or lock-in cost against a threshold they set — separate from the
ZIP-level HOLD/WATCH/ACT alert everyone on the monitor plan already gets.
This is opt-in: saving a watch is the only thing on the site that sends
personal calculation inputs (value, balance, rate, etc.) to the backend —
see the "watch your numbers" section in `privacy.html`.

Setup:
1. Run `supabase/schema-v4.sql` (adds `calc_inputs` + `watch_*` columns).
2. Deploy `supabase/functions/save-watch/index.ts` as edge function
   `save-watch`; disable "Enforce JWT verification". No secrets needed — it
   verifies the subscriber's existing access token itself before writing.
3. The GitHub Action already runs `pipeline/check_watches.py` after each data
   refresh, using the same `SUPABASE_SERVICE_KEY` / `RESEND_API_KEY` secrets
   as `notify_changes.py` — no new secrets needed. It recomputes each
   watcher's metric from the freshly published ZIP data and emails once per
   crossing (a latch column, `watch_crossed`, prevents repeat alerts every
   month the value stays past the threshold).

## Verdict thresholds (pipeline/verdict.py)

| Signal | Yellow-ish | Red-ish | Points |
|---|---|---|---|
| Months of supply | > 4 | > 6 | 2 / 3 |
| Median sale price YoY | < −2% | < −5% | 2 / 3 |
| Listings with price cuts | > 35% | — | 1 |
| Days on market YoY | > +40% | — | 1 |
| Inventory YoY | > +50% | — | 1 |

Score ≥ 4 → 🔴 ACT · ≥ 2 → 🟡 WATCH · else → 🟢 HOLD.
ZIPs with fewer than 2 known signals default to 🟢 with an "insufficient data" note.

**Upside verdict:** when ZERO danger lines are crossed and ≥3 of these strength
signals are met, the verdict is 🔵 "strong" — ACT, seller's-market flavor:
months of supply < 2.5 · price ≥ +5% y/y · DOM down ≥ 15% y/y · price cuts < 20%.
(Redfin's price-drops column is empty in current production files, so that
signal is skipped and the other three must all be met.) Danger verdicts always
win. The front end also applies this upgrade client-side so existing data files
render it without a pipeline rerun.

## Licensing checklist (do before charging money)

- [ ] Email press@redfin.com for written OK to use Data Center files in a commercial
      product with attribution ("Data from Redfin, a national real estate brokerage").
      Attribution is already wired into `meta.json` → the site footer/verdict card.
- [ ] Do NOT add Zillow data — their research data terms restrict commercial use.
- [ ] Optional hardening: add FHFA HPI (public domain, ZIP-level annual) as a
      second price signal, and BLS metro employment as the jobs signal.
- [ ] Run the "ACT" wording past a lawyer; keep the not-financial-advice disclaimer.

## Roadmap

- v1 (this repo): free ZIP checker + waitlist. Validate demand.
- v1.5: Formspree → real email list; monthly "your ZIP changed color" campaign (Buttondown/Mailchimp).
- v2: paid tier — address-level tracking (needs an AVM API, e.g. ATTOM from ~$95/mo), Stripe, accounts. Build as a Next.js app; this repo's pipeline carries over unchanged.
- Seed data in `web/data/` was generated from `pipeline/seed.tsv` — July 2026
  figures for 20874/20906 researched manually (some fields estimated). The first
  real pipeline run overwrites it.
