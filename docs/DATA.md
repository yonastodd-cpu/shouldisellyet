# Data sources, fields, and cadence

What the product ingests, what it computes, how often, and what it would
take to swap a source out. For the *wording* rules around crediting these
sources, see [ATTRIBUTION.md](ATTRIBUTION.md).

## Sources

| Source | File pulled | Cadence | Role |
| --- | --- | --- | --- |
| **Redfin Data Center** — hub, ZIP housing market | `redfin_data_center/housing_market/monthly/all_zips.csv` (~660 MB CSV) | Monthly (checked Mon & Thu by ETag) | **Drives every verdict.** Three of four dials + the 36-month value/DOM history. |
| **Redfin Data Center** — hub, ZIP price drops | `redfin_data_center/price_drops/monthly/all_zips.csv` (~340 MB CSV) | Monthly, same release | Dial 4 (price-cuts share) — a signal the legacy tracker shipped empty for years. |
| **Realtor.com** — residential listings database | `RDC_Inventory_Core_Metrics_Zip.csv` (~7 MB) | Monthly | **Cross-check only.** Displayed beside the dials; never feeds the verdict. |
| **Freddie Mac** — Primary Mortgage Market Survey | `PMMS_history.csv` | Weekly (read on each refresh) | 30-year rate: lock-in math, buyer affordability, rate alerts. |
| **FRED** (St. Louis Fed) | `fredgraph.csv?id=MORTGAGE30US` | Fallback only | Alternate transport for the *same* PMMS series. Not a separate publisher. |
| **FHFA** — experimental annual ZIP5 house price index | `/hpi/download/annual/hpi_at_zip5.xlsx` | **Annual**, run by hand | Benchmark line on the value trend + the danger-line backtest. Through **2025** (release of 2026-03-31). The old `/document/hpi_at_bdl_zip5.xlsx` still returns 200 but is **frozen at 2023** — check the [datasets page](https://www.fhfa.gov/data/hpi/datasets) if `thru` ever stops advancing. |
| **GeoNames** — US postal codes (CC BY 4.0) | `export/zip/US.zip` → `pipeline/data/zip_places.csv` | Committed; re-run `fetch_places.py` on demand | City names on the ~18.6k generated ZIP pages and in the growth digest. Read from disk — the page build makes no network call. |
| **Zippopotam.us** — live ZIP lookup (GeoNames-derived) | `api.zippopotam.us/us/{zip}` | On demand, client-side | City prefill in the browser only (homepage check, address form). Never used at build time. |

`web/data/` (committed, ~14 MB) is derived output, not raw source.

## Normalized fields the product computes from

The verdict engine reads a single struct — `ZipMetrics` in
[`pipeline/verdict.py`](../pipeline/verdict.py):

| Field | Meaning | Redfin column today |
| --- | --- | --- |
| `months_of_supply` | Dial 1 | `months_of_supply`, else `inventory / homes_sold` |
| `median_sale_price_yoy` | Dial 2 | `median_sale_price_yoy` (fraction) |
| `median_dom` / `median_dom_yoy` | Dial 3 | `median_dom`, `median_dom_yoy` (**absolute days**, not a fraction) |
| `price_drop_share` | Dial 4 | price-drops file, `PERCENT ACTIVE WITH PRICE DROPS (%)` ÷ 100 (was empty in the legacy tracker) |
| `inventory_yoy` | Dial 5 (supply wave) | `inventory_yoy` (fraction) |
| `inventory` / `homes_sold` | Counts shown in the "What goes in" disclosures | `inventory`, `homes_sold` |
| value/DOM history | 36-month trend chart | `median_sale_price`, `median_dom` per `period_end` month |
| 30-year rate | Lock-in, buyer math, rate alerts | *(PMMS `now` / `year_ago` / `asof`)* |

The v2 hub columns are translated to the legacy names by `_adapt_v2()` in
`fetch_data.py`, so `row_to_metrics()` still reads one schema. Three unit
conversions live there and were verified against the national file — price
and inventory YoY are true percents (÷100 → fraction), while the DOM YoY
column claims "(%)" but actually carries **Δdays × 100** (+1 day → 100.0).
The pipeline recomputes DOM Δdays from its own month history wherever a
year-ago month exists, so that quirk only matters for history-gap ZIPs —
and it's pinned by `test_fetch_v2.py` either way.

## The 2026-06 migration (why the old tracker froze)

Every `redfin_market_tracker/*.tsv000.gz` file's Last-Modified stamps read
2026-06-02 18:15–18:20 GMT — one batch that ran once and never again — while
the Data Center page kept saying "Updated monthly." The data had **moved**,
not stopped: Redfin rebuilt the page as a "Download Hub" whose Download
button fetches static files under `redfin_data_center/` in the same public
S3 bucket and filters them client-side. Pulling those files directly is
exactly what the official button does. Confirmed 2026-08-03: hub files
Last-Modified 2026-07-30, rows through period end 2026-06-30.

Practical differences, all handled in `fetch_data.py`:

- plain CSV (legacy was gzipped TSV) — decompression is now by magic bytes
- `REGION NAME` is the bare ZIP (legacy: `"Zip Code: 20874"`)
- **no state column** — states come from the committed
  `pipeline/zip_states.csv` (extracted from the last v1-derived site data;
  3-digit-prefix majority fallback for unseen ZIPs). The hub's METRO field
  can't be used: metros straddle state lines (07002 is NJ, metro "New
  York, NY").
- no `property_type` column (all-residential only; property types are a
  separate hub dataset)
- `NA` for missing (legacy: empty string)
- price drops split into their own file — see Sources
- the archived legacy TSVs still parse: the schema is auto-detected

**Two dials came back from the dead with this migration, and the verdict
mix shifted accordingly.** The legacy tracker shipped `price_drops` empty
(the price-cuts signal never fired) and `months_of_supply` empty — the
proxy divided inventory by *rolling-3-month* sales, understating true
months-of-supply about 3× (20874: proxy 0.85 vs. real 2.2), so the supply
signals barely ever fired either. The v2 columns carry real values for
both. Expect one-time verdict-flip spikes in the digest and richer red
counts nationally; that is two designed signals finally receiving data,
not a methodology change. **Follow-up:** re-run the annual backtest
against v2 snapshots at the next FHFA release — the published
decline-rates for the mos and price-cuts signals were measured with those
columns empty.

## Swapping a source

Any replacement for the Redfin feed must map onto the normalized fields
above, and must match their **definitions**, not just their names:

- `median_dom_yoy` is an absolute change **in days**. Realtor.com's
  equivalent is a **fraction** — that mismatch is exactly why RDC is a
  cross-check and not a verdict input.
- The danger thresholds (4.0 months, −2% y/y, +40% DOM, 35% price cuts,
  +50% inventory) were validated against **Redfin's definitions** and
  backtested against FHFA outcomes. A source with different definitions
  invalidates the thresholds until re-backtested.
- Changing a verdict input's source silently would flip verdicts — and fire
  subscriber alert emails — on a data change rather than a market change.

**Recommended follow-up (not done here):** extract an adapter layer so each
source implements `-> ZipMetrics` behind a common interface, instead of
`row_to_metrics()` reaching into Redfin column names. That is the real
prerequisite for a same-job fallback feed.

## Refresh pipeline

`.github/workflows/update.yml`, Mon & Thu 13:00 UTC:

1. ETag check against the Redfin housing-market file — unchanged means
   deploy-only, no rebuild.
2. **Snapshot raw sources** → `archive/{YYYY-MM}/` (see below).
3. `pipeline/fetch_data.py` runs against the archived local copies
   (`--input all_zips.csv --price-drops price_drops_all_zips.csv`).
4. Verdict-change alerts, personal-number watches, tests.
5. Commit `web/data`, deploy Pages.

Annual, by hand, after each FHFA release:

```bash
python3 pipeline/fetch_fhfa.py --full-out /tmp/fhfa_full.csv
python3 pipeline/backtest_thresholds.py --redfin <tracker.gz> --fhfa-full /tmp/fhfa_full.csv
```

Commit the regenerated `pipeline/fhfa_zip.csv` and
`pipeline/backtest_results.json`. The monthly pipeline reads those
artifacts and needs no extra dependencies (`openpyxl` is only for the
annual run).

## Archiving

Each refresh writes dated copies of every raw source to
`archive/{YYYY-MM}/`, **in addition to** the normal working data — archives
are never overwritten and the working data path is unchanged.

**Stored as workflow artifacts, not committed.** The Redfin files alone
are ~1 GB per month against a 20 MB repo; committing them would make the
repo unusable within a year. `archive/` is gitignored. Download from the
run's artifacts page (`raw-sources-YYYY-MM`).

⚠️ **Retention is 90 days, not longer.** 90 days is GitHub's hard cap for
artifacts on public repositories — a larger `retention-days` is silently
reduced (observed: "Retention days cannot be greater than the maximum
allowed retention set within the repository. Using 90 instead"). So the
archive protects against a *recent* upstream revision, **not** against
long-term discontinuation.

**For durable retention, move the upload to an S3/R2 bucket.** The archive
step already writes plain files into a dated folder, so only the upload
target changes. This is the single highest-value follow-up in this doc: at
90 days, an upstream file that disappears and isn't noticed within a
quarter is gone.

Archived per month (verified on run 30729033579, 2026-08-02):

| File | Source | Size |
| --- | --- | --- |
| `all_zips.csv` | Redfin (housing market) | ~660 MB |
| `price_drops_all_zips.csv` | Redfin (price drops) | ~340 MB |
| `RDC_Inventory_Core_Metrics_Zip.csv` | Realtor.com | 7.1 MB |
| `PMMS_history.csv` | Freddie Mac | 95 KB |
| `redfin-data-center.html` | terms page | *see below* |

⚠️ **The terms-page capture does not work from CI.** Redfin rate-limits
datacenter IPs: a HEAD request returns 200, but the GET body is a bot wall
("Are You a Robot?", HTTP 429, ~1.9 KB) containing none of the citation
terms. The step now checks the *content* and deletes the file if it's a
block page, so a saved bot wall can never masquerade as a compliance
record — it logs a warning instead. **The capture is therefore an operator
task, below.**

### Operator task — not automated

Save an [archive.org](https://web.archive.org/) capture of the Redfin Data
Center page and keep a dated screenshot alongside this folder. Redo it
whenever their terms change.
