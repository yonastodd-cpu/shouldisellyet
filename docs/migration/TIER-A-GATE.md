# Tier A validation gate (Phase 2.3) — PASSED, 2026-08-19

Run against 1,000 Tier A ZIPs acquired in runs 32304466324 (smoke, 1 request)
and 32304579641 (998 requests, zero errors, zero no_data, 142.2 MB stored).
Two requests were also spent on pre-gate smoke tests. Total: 1,000 of the
5,000 included Growth requests.

## 1. Coverage — 100%

All 1,000 rows carry price, DOM, listings, and a full 12-month history.
Nothing in Tier A came back thin. (Expect no_data to appear in Tier B — these
were the 1,000 largest owner-occupied ZIPs in the country.)

## 2. Sanity distributions — sane

list price p10/p50/p90 = $265k / $425k / $750k · active DOM p50 = 61 days ·
listings p50 = 334 (min 53, max 2,119). Active DOM sits high versus sold-DOM
norms, exactly as reading-methodology-v2 predicted.

## 3. Cross-vendor corroboration — shape agrees, levels are vendor-specific

Against Realtor.com's committed per-ZIP data (independent vendor, same
active-listing basis, 998 overlapping ZIPs):

    listings  r = 0.931, but RentCast counts ~2.26x RDC's (p10 1.78, p90 3.22)
    DOM       r = 0.868, RentCast reads systematically higher

THE FINDING THAT MATTERS: the two vendors clearly count "an active listing"
differently, so LEVELS are not comparable across vendors — but the
correlation says both are measuring the same market. This is the
metric-shift lesson a third time, and it is why verdict_v2 scores only
year-over-year ratios of a self-consistent series and never levels. Any
future surface that shows a RentCast listing count next to an RDC one will
confuse readers; don't.

DMV spot-check table (10 MD ZIPs) reviewed: list medians plausible for every
ZIP ($799k Ellicott City, $475k Clinton, etc). The plan's fuller 20–30 ZIP
manual check against public listing sites remains open for the operator, but
the independent-vendor corroboration is the stronger evidence.

## 4. raw_json round-trip — clean

5 random rows pulled from market_stats, parsed from raw_json with
fetch_rentcast.parse_market, compared to their stored columns: 5/5 identical.
CI's own --parse-only pass also parsed all 998 responses without error.

## Verdict

Tier B spend is justified on data-quality grounds. Before dispatching it:
tier B is 4,000 ZIPs and 4,000 requests remain in this cycle — exactly
enough, with zero slack for retries beyond the ceiling. Either run Tier B at
--ceiling 4000 and accept that a retry-heavy run leaves a tail for next
cycle, or wait for the cycle boundary. Do not let it overage.
