# RentCast migration — Phase 1 onward (cost-minimized plan, as written)

Phase 0 is recorded in `docs/REDFIN-SUNSET.md` and is unchanged by this
document. What follows is the written plan as received, followed by the
corrections that came out of checking it against this repo — same treatment
Phase 0 got, and for the same reason: the plan was drafted against assumptions
the codebase does not meet.

**Read the corrections before spending anything.** Two of them change the
plan's cost arithmetic and one of them blocks Day 0.

---

## Governing principle

Every dollar of API spend should buy a page that earns traffic. Spend on the
head, use free public data for the tail, never pay twice for the same bytes.

## Phase 1 — RentCast setup (Days 0–4)

### 1.1 Cut the bill before picking a plan

**Lever 1 — shrink N.** Start from the actual SISY ZIP-page count, intersect
with the free Census ZCTA list (~33k), drop ZIPs below a housing-unit floor
using free Census ACS B25001 (e.g. <500 units), rank the survivors by 90-day
GSC impressions. Expect a steep curve.

**Lever 2 — never pay twice.** Store the raw JSON response for every call,
permanently. One `/markets` call returns current stats plus ~12 months of
history plus breakdowns by property type and bedroom count — set
`historyRange` to the maximum on the *first* call (sale history goes back to
Jan 2024). Develop against saved fixtures, not the live API. Make the runner
idempotent with per-ZIP checkpointing.

**Lever 3 — free public data for the long tail.** See §3.2.

### 1.2 Plan crossover math

| Plan | $/mo | Included | Overage |
|---|---|---|---|
| Developer | $0 | 50 | $0.20 |
| Foundation | $74 | 1,000 | $0.06 |
| Growth | $199 | 5,000 | $0.03 |
| Scale | $449 | 25,000 | $0.015 |

| Monthly volume | Cheapest plan | Cost |
|---|---|---|
| under ~170 | Developer | $0 – $24 |
| ~170 – ~1,170 | Foundation | $74 – $84 |
| ~1,170 – ~13,300 | Growth | $199 – $449 |
| above ~13,300 | Scale | $449+ |

Recommendation as written: **Growth at $199 for month one**, on the assumption
that Levers 1–3 reduce the paid tier to ~5,000 ZIPs.

### 1.3 Billing traps
- Quota does not roll over.
- Switching plans resets quota mid-cycle — confirm in writing with RentCast
  support what happens to already-consumed requests before any mid-month move.
- Turn on 85%/100% usage emails; check the dashboard daily during the run.

### 1.4 Account and schema prep
- API key restricted by IP/endpoint, in a secrets manager, never in the repo.
- `market_stats` table: `zip`, `as_of_month`, `source`, `retrieved_at`, parsed
  metrics, **and `raw_json`**.
- Per-ZIP job status: `pending` / `done` / `no_data` / `error` /
  `free_source_only`.
- Read the RentCast Terms of Use in full (attorney batch item 2).

## Phase 2 — Migration job (Days 4–12)

| Tier | Contents | Source | API cost |
|---|---|---|---|
| A | Top ~1,000 ZIPs by impressions | RentCast, full history | included |
| B | Next ~4,000 ZIPs | RentCast, full history | included |
| C | Remaining ZIPs above the housing floor | free public sources | $0 |
| D | Below the floor / `no_data` | nothing — live but noindexed | $0 |

Run Tier A first and validate before spending on Tier B.

**Runner discipline:** checkpoint per ZIP; throttle to the published rate
limit; exponential backoff on 429/5xx; **cap retries at 3 and mark `error`**;
hard stop at a configured request ceiling; log HTTP status and byte size per
call.

**Validation gate before Tier B:** coverage % with usable `saleData`; sanity
distributions on median price, DOM, listing counts; spot-check 20–30 familiar
ZIPs against public listing sites; confirm stored `raw_json` round-trips
cleanly through the parser.

## Phase 3 — Formula rebuild (Days 8–20)

Redfin gave largely **closed-sale** data. RentCast `/markets` statistics are
computed from **active listings**. Inputs change meaning, not just name:

| Redfin concept | RentCast field | Note |
|---|---|---|
| Median sale price | `medianPrice` (active) | list-price median; trend valid, level reads high |
| Median sale PPSF | `medianPricePerSquareFoot` | same caveat |
| Median DOM (sold) | `averageDaysOnMarket` (active) | skews high; stale inventory sits in the pool |
| Inventory | `totalListings` | close match |
| New listings | `newListings` | close match |
| Sale-to-list ratio | — | no equivalent, drop |
| % sold above list | — | no equivalent, drop |
| Price drops % | — | restore from free sources |
| Homes sold | — | restore from free sources |

Design v2 to run on RentCast fields alone; free supplements layer on top.

**Free ZIP-level sources, ranked by licence safety:** FHFA HPI (public domain,
cleanest — the price-appreciation anchor); Census ACS (public domain);
Realtor.com Data Library (ToU review required); Zillow Research (needs
explicit commercial clearance, not assumed).

**Recompute at $0:** rewrite HOLD/WATCH/ACT; backtest against stored raw JSON,
not the live API; check the national distribution against the pre-migration
baseline — if most of the country flips category the thresholds are wrong, not
the country; freeze `reading-methodology-v2`; update the public methodology
page and the ToS/disclaimers.

## Phase 4 — Progressive reindex (Days 16–45)

Tranche 1 (~Day 16) Tier A, QA 25 pages by hand first. Tranche 2 (~Day 24)
Tier B, once Tranche 1 shows clean data and normal GSC pickup. Tranche 3
(~Day 35) Tier C pages meeting the quality floor, labelled distinctly on the
methodology page. **Tier D never re-enabled** — live, 200, `noindex`, honest
"insufficient data" state.

## Phase 5 — Steady state

| Option | Paid req/mo | Plan | $/mo |
|---|---|---|---|
| A. All 5,000 monthly | 5,000 | Growth | $199 |
| B. Top 1,000 monthly, rest quarterly | ~2,333 | Foundation + overage | ~$154 |
| C. Top 1,000 monthly, rest semiannually | ~1,667 | Foundation + overage | ~$114 |
| D. Top 1,000 monthly only | 1,000 | Foundation | $74 |

Recommended landing spot: B or C, ~$114–154/month. Set a 60-day review to
promote high-traffic Tier C ZIPs into the paid tier and demote paid ZIPs that
never earn impressions. Keep the free-source ingest scripts maintained even
where unused — single-vendor dependency is now the product's main structural
risk.

## Attorney batch
1. Redfin data — retention vs deletion now that use has stopped.
2. RentCast ToU — confirm derived-reading display is permitted.
   **SHARPENED 2026-08-19 by the re-scoring step.** The question is no longer
   only about display. `web/data/zips/*.json` is committed to a PUBLIC repo,
   and after re-scoring it carries 5,000 ZIPs' current RentCast medians plus
   **60,000 monthly median-price history points**. That is the closest thing
   in this system to redistributing vendor data rather than displaying a
   derived reading, and it is the usual prohibited use. Note the posture is
   not new — the same field published 36 months of Redfin history per ZIP for
   as long as the site has existed — but the vendor is new and its terms are
   unreviewed. If counsel objects, the fix is small and local: the sparkline
   can read from Supabase at request time instead of shipping in the page
   data, or `h` can be truncated. Worth asking before Tranche 1, not after.
3. Realtor.com Data Library and Zillow Research — commercial display terms.
4. Updated SISY ToS/methodology disclosures naming the new sources and the
   per-tier refresh cadence.

---

# Corrections to the written plan

Each verified against the code before being written down.

| Plan said | Actually |
|---|---|
| Rank ZIPs by 90-day GSC impressions | Phase 0 said Search Console was never connected. **A `google-site-verification` TXT record is live on the domain**, so a property was verified at some point — but even if it is still active, every ZIP page is `noindex` and accrues no impressions. The ranking cannot exist before the reindex it is meant to order. |
| 38k ZIP universe; full sweep costs $644 on Scale | The site has **22,874** ZIP pages. 22,874 is inside Scale's 25,000 included quota, so a full national sweep is **$449 flat**, not $644. |
| Design v2 on RentCast fields alone; homes-sold is a nice-to-have supplement | Months of supply is `inventory ÷ homes_sold` and is the **highest-weighted signal in the engine**. RentCast has no `homes_sold`. RentCast-alone deletes the top danger check and one of four strength checks. |
| Realtor.com is a future free supplement pending clearance | `load_rdc()` in `fetch_data.py` already pulls the Realtor.com ZIP file **every monthly run, in production, today**. The licence question is live now, not in Phase 3. |
| Build Tier C on FHFA + Census | FHFA is **already built** (`fetch_fhfa.py`, `fhfa_zip.csv`, 19,023 ZIPs) — and it is annual and lagged, which its own module docstring calls "a benchmark and backtest source, never an early-warning signal." It cannot carry a timely reading alone. |
| — (not mentioned) | Re-enabling data un-gates `notify_changes.py` and `check_watches.py`. The first post-cutover run will email subscribers about verdict changes that are a **source change, not a market change**. |

## 1. The impression ranking cannot exist before the reindex it orders

Lever 1's ranking step, the Tier A/B split, Phase 4's tranche order and Phase
5's promote/demote review all take 90-day GSC impressions as an input.

Phase 0 recorded that Search Console was never connected. That is not quite
right: `shouldisellyet.com` carries a live
`google-site-verification=Pl42pMKLLqaISlVPLHJAv5_5hMMjLCt10ZkR-pnNpO0` TXT
record (DNS at Cloudflare, hosting on GitHub Pages), which is the Domain-
property verification method. Either a property is verified right now under
some Google account, or one was verified and later removed and the record
outlived it. **Checking which is the highest-value open item in this
document** — a live property may hold up to 16 months of history, which is the
only way a pre-pause impression ranking can exist at all.

But verifying today does not solve Lever 1, because of a circular dependency
the plan does not name:

- Impressions accrue only for URLs that appear in search results.
- Every one of the 22,874 ZIP pages serves `noindex,follow` (verified live),
  so none of them can appear, so none of them can accrue impressions.
- The live submitted sitemap is **four URLs** — `/`, `/report.html`,
  `/press.html`, `/zip/`. Phase 0 holds every ZIP, state hub and research URL
  out of it by design.
- Phase 4 removes `noindex` in tranches **ordered by those impressions**.

So the ranking that decides which pages to un-noindex can only be produced
after they are un-noindexed. Verifying Search Console starts the clock; it
does not turn it back.

`docs/migration/phase0-traffic-snapshot.json` cannot substitute — it carries
its own refusal in a `caveat` field: first-party anonymous counting that
honours DNT/GPC, an 8-day window, 2,021 distinct ZIP paths of 22,874, a
maximum of 27 views on any page, 17 Google referrals total, no organic-search
signal, "NOT a substitute for Search Console and must not be used alone to
rank reindex tranches."

What this means in practice:

- **Confirm the property first.** If it is live with pre-pause history, Lever 1
  works as written and this correction shrinks to a footnote. If not,
  everything below applies.
- **The interim ranking is mandatory, not a fallback.** Built:
  `pipeline/rank_interim.py` writes `pipeline/tier_interim.csv` from
  committed data alone, no network and no quota. **10,633 ZIPs clear the
  gates** — standing page, ACS housing units >= 500, FHFA-covered, a
  Realtor.com row that is not `quality_flag`ged — so the 5,000-ZIP paid tier
  can be filled with quality ZIPs and still leaves 5,633 for Tier C.
  Ordering is owner-occupied units descending, the closest free proxy to
  "how many people here could plausibly ask whether to sell."

  **Its curve is flat where the plan assumed steep.** Tier A's 1,000 ZIPs
  carry 24.4% of eligible owner-occupied stock and the full 5,000 carry
  76.5%. Housing supply is far more evenly spread than search demand, so
  this cannot reproduce the "a few thousand ZIPs carry the large majority of
  impressions" concentration Lever 1's cost argument leans on. Tiering by
  this proxy buys less focus than an impressions split would — which is an
  argument for reading the $449 Scale option in correction 2 as live rather
  than settled. Say which ordering was used on the page that explains why
  those 1,000 were chosen.
- **Verify and connect regardless**, today. Even with zero ZIP impressions it
  earns the coverage and indexing diagnostics that Phase 4 needs to watch
  deindex-to-reindex, plus query data on the four still-indexed URLs, and it
  starts accruing the moment Tranche 1 lifts `noindex` on Tier A.
- Do not defer the migration 90 days waiting for impressions that cannot
  arrive. Do not rank by the events table.

## 2. The universe is 22,874 and that changes the cost tradeoff

The plan's headline comparison — $199 tiered vs $644 for "the all-38k-on-Scale
approach" — is against a number this site does not have. The real alternative
is **$449 flat, once, for every ZIP the site publishes**, with no overage,
because 22,874 fits inside Scale's included 25,000.

That is $250 more than Growth for complete national coverage in one month, with
every raw payload stored permanently under Lever 2 and therefore never bought
again. Tiering is still defensible — it front-loads validation, and Tier D
pages were never going to be reindexed — but the honest framing is "$199 now
and a decision later" versus "$449 once and the tail is done forever," not
"$199 versus $644."

Recommendation stands at Growth for month one, on the strength of the Tier A
validation gate rather than on the cost gap.

## 3. Months of supply does not survive the source change

`verdict.py` scores five danger checks. Months of supply is the only one that
can reach 3 points on its own, and `fetch_data.py` computes it as
`inventory ÷ homes_sold`. RentCast supplies `totalListings` but nothing
equivalent to homes sold, because active-listing statistics cannot see closings.

Under a RentCast-only formula:
- `supply_severe` / `supply_high` are gone — the strongest danger signal.
- `supply_tight` is gone — one of four strength signals, and
  `STRONG_MIN_SIGNALS = 3` of 4 means losing one materially raises the bar for
  a "strong" verdict.
- `price_drop_share` is gone too — no RentCast equivalent — taking a second
  danger check and a second strength check with it. That leaves 3 of 4 strength
  signals available and requires all 3, and the `known < 2` insufficient-data
  gate gets much easier to trip on thin ZIPs.

So "design the v2 formula to run on RentCast fields alone" is not a safety
margin here; it is a decision to ship a visibly weaker engine. Either the
Realtor.com feed becomes a **verdict input** (it already carries
`price_reduced_share` and `price_reduced_count`, which is the price-cut signal
restored) and the licence must clear before launch, or v2 accepts a
three-signal engine and the methodology page says which signals were retired
and why. That is a product call, not an implementation detail.

## 4. Realtor.com is already in production — the licence question is live today

`load_rdc()` fetches `RDC_Inventory_Core_Metrics_Zip.csv` on every monthly run
and ships `median_days_on_market`, `active_listing_count`,
`price_reduced_share`, `price_reduced_count` and the YoY fields into each ZIP
entry for display and cross-check. This is the same Realtor.com Data Library
the plan lists as a future free supplement "pending ToU review."

Three consequences:
1. Attorney batch item 3 is not a Phase 3 gate — it describes **current
   published behaviour**. If it fails review, something has to come down now,
   independently of RentCast.
2. The real question for the paid tier is not "what does RentCast give us"
   but "**what does RentCast add over a feed we already have for free**."
   Honestly: median price and price-per-square-foot, plus history back to Jan
   2024. Everything else on the plan's field-mapping table is either already
   arriving from RDC or has no RentCast equivalent at all. A 5,000-ZIP paid
   tier may be several times larger than that delta justifies.
3. `load_rdc()` refuses to feed the verdict engine on purpose, and its
   docstring gives the two reasons: definitions do not reconcile (RDC's
   `price_reduced_share` does not match `price_reduced_count / active_listing_count`
   in the published file; RDC `*_yy` fields are fractions while Redfin's
   `median_dom_yoy` is absolute days), and switching a verdict input's source
   silently "would flip verdicts and fire subscriber alert emails on a
   data-source change, not a market change." **That warning applies with full
   force to RentCast.** It was written about a feed with the same definitional
   mismatch problem the plan's §3.1 table describes.

RDC's `quality_flag` — set on roughly half the file, mostly thin ZIPs — is also
the plan's housing-unit floor, already computed, already free, already parsed.
Census B25001 is worth pulling as a cross-check, not as the primary filter.

## 5. FHFA exists, and cannot carry Tier C alone

`fetch_fhfa.py` and the committed `fhfa_zip.csv` cover **19,023 ZIPs** — 3,851
short of the 22,874 published pages. It is annual, lagged, and its own module
docstring is explicit: "the official, government-published measure of *value* —
annual and lagged, so it is a benchmark and backtest source, never an
early-warning signal."

A Tier C built on FHFA + Census produces a page whose reading is up to a year
stale and cannot move when the market moves. Tier C in practice means RDC,
which routes straight back to correction 4. If the licence does not clear,
Tier C collapses into Tier D and the noindexed set grows from "below the
housing floor" to "everything outside the paid tier" — roughly 18,000 pages.
The plan should carry that as its named downside case.

## 6. Suppress subscriber alerts across the cutover

Phase 0 gated eleven downstream steps off `changed=false`, including subscriber
alert emails and the velocity upsert. Setting `PAUSED = false` un-gates them.
The first run on RentCast data will diff new verdicts against Redfin-era stored
verdicts and mail subscribers about every difference — on a source change.

Add to Phase 4, before Tranche 1: land the new baseline with notifications
still gated, verify the diff volume, and only then re-enable
`notify_changes.py` and `check_watches.py`. Phase 0 already established the
same principle for the marketing queue ("regenerate rather than un-skip").

## Open, for the human

- Whether v2 ships as a three-signal RentCast-only engine or takes RDC as a
  verdict input and gates launch on the licence answer (correction 3).
- Whether to verify Search Console now and start Tier A on an interim
  data-quality ranking, or hold the reindex for real impression data
  (correction 1).
- Whether the delta RentCast actually adds over RDC — median price and PPSF —
  justifies 5,000 paid ZIPs or a much smaller head (correction 4).
