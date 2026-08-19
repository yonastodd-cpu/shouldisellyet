# Tier B validation gate + threshold calibration — PASSED, 2026-08-19

Run 32306099306: 4,000 requests of a 4,000 ceiling, zero retries wasted,
zero errors, zero no_data. 673.3 MB stored across the combined 5,000 ZIPs;
all 4,000 loaded. The cycle's included quota is now fully spent (5,000 of
5,000) — anything further this month is overage.

## The four §2.3 checks

1. **Coverage: 100%.** All 4,000 Tier B ZIPs carry price, DOM, listings and
   a full 12-month history. Even the thinnest ZIP (8 active listings)
   computes all three YoY signals; 0 of 5,000 score insufficient_data.
2. **Distributions: consistent.** Tier B vs A: price p50 $390k vs $425k,
   DOM 64 vs 61, listings p50 186 vs 334 — exactly what descending
   owner-occupancy rank should produce.
3. **Cross-vendor: the level ratio replicates.** Against Realtor.com on
   4,000 independent ZIPs: listings r=0.892, DOM r=0.839, and the
   RentCast/RDC listing ratio p50 = 2.34 vs Tier A's 2.26. A stable,
   replicating vendor difference is what YoY scoring requires.
4. **Round-trip: 5/5** random rows re-parse from raw_json identical to
   their stored columns.

## The finding: two thresholds were dead, and are now refit

Signal firing rates, same 5,000 ZIPs, proxy (sale basis) vs real
(active-listing basis):

| signal | proxy | real @ ported threshold | real @ refit |
|---|---|---|---|
| price_falling / _fast | 14.9% / 14.4% | 15.0% / 13.6% | unchanged |
| dom_stretching | 13.2% | **0.8%** | 11.5% |
| inventory_surge | 3.8% | **0.5%** | 3.0% |

Price YoY ports perfectly across the basis change. The volume signals do
not: stale inventory anchors an active pool, damping its YoY swings ~8–16x.
At the ported thresholds both signals were functionally dead — the site
would never again have flagged a demand crack or a supply wave.

The refit holds SENSITIVITY constant instead of the number
(percentile-matched on the real distributions, rounded):

    dom_stretch      +0.40 → +0.10   (matched +0.085)
    inventory_surge  +0.50 → +0.30   (matched +0.277)
    dom_shrink       -0.15 → -0.20   (over-fired at 29.7% vs intended 19.2%)
    inventory_drop   -0.15 unchanged (matched -0.144)

## Result, and the provisional flag

v1 on these 5,000 ZIPs (June, sale basis): ACT 16.2%. v2 refit on real
August RentCast data: **ACT 15.8%** — flat across the entire migration.
HOLD rises 46.2% → 58.6%, which is WATCH→HOLD (fewer 1–2 point
combinations) plus the deliberately tightened 3-of-3 strong path (7.4% →
3.2%), both by design and documented in reading-methodology-v2.

SPEC["provisional"] is retired: the calibration this flag demanded has now
run against 5,000 real responses. Changing any threshold again requires
re-running calibrate_v2.py --from-db and updating the pinned test.

## Still open

- The June→August drift step still mixes vendor behaviour with two real
  months; a second RentCast month resolves it for free from history.
- The operator's manual 20–30 ZIP spot-check against public listing sites.
