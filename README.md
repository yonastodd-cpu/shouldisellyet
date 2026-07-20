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

**Billing:** create two Stripe Payment Links ($5.99 one-time, $5.99/mo) and paste
them into `CHECKOUT_URL` / `MONITOR_CHECKOUT_URL` in `web/report.html` and
`MONITOR_CHECKOUT_URL` in `web/index.html`. Until then, signups are captured as
`status='pending'` in Supabase for manual follow-up.

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
