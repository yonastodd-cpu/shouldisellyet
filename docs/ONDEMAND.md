# On-demand pulls & search-demand logging

Shipped 2026-08-25. Any US ZIP — including the ~17,874 notice-page ZIPs — is
purchasable: checkout pulls fresh market data at order time, validates it,
and only then lets the charge happen.

## The funnel, end to end

    lookup (homepage) ──► demand log (zip_lookups)
        │
        ├─ reading ──► normal purchase path
        │
        └─ notice  ──► CTA "full report available now" + notify-me capture
                │
                ▼
    checkout (subscribe.html go())
                │
                ▼
    ondemand-pull edge fn:  store check ──► ceiling ──► ONE /markets call
                │                                            │
                │ (data already held: $0)                    ▼
                │                                   quality floor (min_known,
                │                                   same as verdict_v2)
                ▼                                            │
        ok ──► Stripe Payment Link ──► webhook ──► report    │ FAIL
                                                             ▼
                                     "…haven't been charged" + notify-me
                                     + zip_lookups row (coverage gap)

A passing pull stores `market_stats` (raw_json + retrieved_at +
source='rentcast'), `market_history`, `zip_readings` (the v2 reading, named
columns) and a `zip_release` row (tranche='ondemand') — so the API serves the
ZIP immediately (homepage + paid report read the word from
`market-reading`'s `reading` field). The static page stays a notice until the
operator dispatches the promotion sweep.

## The pieces

| Piece | Where |
|---|---|
| Kill switch | `pipeline/ondemand_switch.py` (mirrors: ondemand-pull fn, index.html, subscribe.html — pinned by `test_ondemand_switch.py`) |
| Demand log | `supabase/functions/demand/index.ts` → `public.zip_lookups` (schema-v41); client side in `web/track.js` (`SISY.demand`/`SISY.follow`, DNT-suppressed) |
| Pull + validate + store | `supabase/functions/ondemand-pull/index.ts` (SPEC mirror of `verdict_v2.py`, pinned by `test_ondemand_pull_fn.py`) |
| Reading served pre-deploy | `market-reading/index.ts` fills `reading` from `public.zip_readings` |
| Admin report | `/admin.html#demand` → `admin_demand(days)` RPC |
| Promotion sweep (manual dispatch only — operator decision 2026-08-26, no cron) | `.github/workflows/ondemand-promote.yml` → `pipeline/promote_ondemand.py` → tranches.json → normal gated deploy |
| Gate | Gate B (`scripts/gate-paid-surfaces.py`) now also asserts no built notice page renders a figure |

## Cost & abuse controls

* **Ceiling**: `ONDEMAND_MONTHLY_CEILING` (edge-function secret, default 150
  in code). Every row in `public.ondemand_pulls` is one paid vendor call,
  any status; at the ceiling the CTA path answers "temporarily at capacity"
  — never a silent overage. Size it as: remaining included monthly quota −
  the next scheduled `market-refresh` budget.
* **Dedupe**: a pulled ZIP is live for a month (32-day freshness window);
  the store is checked BEFORE any vendor call, so later buyers cost $0.
* **Farming**: pre-payment pulls are rate-limited 10/h per IP overall and
  3/h per IP on the vendor path.
* **No key, no sales**: if `RENTCAST_API_KEY` is missing from the function's
  secrets, notice-ZIP checkouts degrade to "at capacity" (store-backed ZIPs
  unaffected).

## Operator setup (one-time)

1. Run `supabase/schema-v41.sql` in the SQL editor (after v40).
2. Deploy edge functions: `demand`, `ondemand-pull` (new), `market-reading`,
   `save-watch` (updated). Disable "Enforce JWT verification" on the new two.
3. Add secrets in Supabase → Edge Functions: `RENTCAST_API_KEY` (same key
   the GitHub acquisition workflow uses), optionally
   `ONDEMAND_MONTHLY_CEILING`.

## Notes & deviations recorded

* Watch baselines: `save-watch` now stamps `baselineBasis` from
  `zip_release.basis` at write time — the upstream fix
  `check_watches.record_baseline_basis()` documents. The basis literal is
  `"active listings"` (the repo's name for the RentCast asking-price basis);
  no `rentcast_asking` literal exists anywhere, and introducing one would
  trip `CrossBasisError` against every current surface.
* The monthly refresh: `market-refresh.yml` is manual-dispatch by design
  (no cron yet — Phase 5 picks the cadence). On-demand ZIPs join the same
  roster as tranche ZIPs once the promotion sweep lands them in tranches.json;
  until a scheduled refresh exists, their refresh is the same manual
  dispatch every other ZIP gets.
* Failure copy says "our data provider", not the vendor's name — the
  licence bars the name on commercial surfaces (see index.html's v-stamp
  comment).
