# Data sources, fields, and cadence

What the product ingests, what it computes, how often, and what it would
take to swap a source out. For the *wording* rules around crediting these
sources, see [ATTRIBUTION.md](ATTRIBUTION.md).

## Sources

| Source | File pulled | Cadence | Role |
| --- | --- | --- | --- |
| **Redfin Data Center** — ZIP-code market tracker | `zip_code_market_tracker.tsv000.gz` (~1.5 GB gzipped TSV) | Monthly (checked Mon & Thu by ETag) | **Drives every verdict.** All four dials + the 36-month value/DOM history. |
| **Realtor.com** — residential listings database | `RDC_Inventory_Core_Metrics_Zip.csv` (~7 MB) | Monthly | **Cross-check only.** Displayed beside the dials; never feeds the verdict. |
| **Freddie Mac** — Primary Mortgage Market Survey | `PMMS_history.csv` | Weekly (read on each refresh) | 30-year rate: lock-in math, buyer affordability, rate alerts. |
| **FRED** (St. Louis Fed) | `fredgraph.csv?id=MORTGAGE30US` | Fallback only | Alternate transport for the *same* PMMS series. Not a separate publisher. |
| **FHFA** — experimental annual ZIP5 house price index | `hpi_at_bdl_zip5.xlsx` | **Annual**, run by hand | Benchmark line on the value trend + the danger-line backtest. |

`web/data/` (committed, ~14 MB) is derived output, not raw source.

## Normalized fields the product computes from

The verdict engine reads a single struct — `ZipMetrics` in
[`pipeline/verdict.py`](../pipeline/verdict.py):

| Field | Meaning | Redfin column today |
| --- | --- | --- |
| `months_of_supply` | Dial 1 | `months_of_supply`, else `inventory / homes_sold` |
| `median_sale_price_yoy` | Dial 2 | `median_sale_price_yoy` (fraction) |
| `median_dom` / `median_dom_yoy` | Dial 3 | `median_dom`, `median_dom_yoy` (**absolute days**, not a fraction) |
| `price_drop_share` | Dial 4 | `price_drops` (fraction; usually empty in production files) |
| `inventory_yoy` | Dial 5 (supply wave) | `inventory_yoy` (fraction) |
| `inventory` / `homes_sold` | Counts shown in the "What goes in" disclosures | `inventory`, `homes_sold` |
| value/DOM history | 36-month trend chart | `median_sale_price`, `median_dom` per `period_end` month |
| 30-year rate | Lock-in, buyer math, rate alerts | *(PMMS `now` / `year_ago` / `asof`)* |

⚠️ **The mapping is not abstracted.** `row_to_metrics()` reads raw Redfin
column names directly. There is no adapter layer, so a replacement source
cannot be dropped in — see below. (Deliberately not refactored here.)

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

1. ETag check against the Redfin file — unchanged means deploy-only, no rebuild.
2. **Snapshot raw sources** → `archive/{YYYY-MM}/` (see below).
3. `pipeline/fetch_data.py` runs against the archived local copy.
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

**Stored as workflow artifacts, not committed.** The Redfin tracker alone
is ~1.5 GB per month against a 20 MB repo; committing it would make the
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
| `zip_code_market_tracker.tsv000.gz` | Redfin | 1.5 GB |
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
