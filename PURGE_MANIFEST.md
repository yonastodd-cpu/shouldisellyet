# Purge manifest

Files carrying third-party vendor measurements that must leave the public
repository and its history. Maintained across the remediation prompts; the
history scrub reads this list.

## Removed from the deployed artifact — 2026-08-19 (Prompt A)

| Path (now) | Was | Vendor | Contents | Public serving stopped |
|---|---|---|---|---|
| `pipeline/cases/austin-2021.json` | `web/data/cases/` | Redfin | 48 monthly measurement records + peak/trough prices | 2026-08-19 |
| `pipeline/cases/boise-2021.json` | `web/data/cases/` | Redfin | 48 monthly records + prices | 2026-08-19 |
| `pipeline/cases/cape-coral-2022.json` | `web/data/cases/` | Redfin | 54 monthly records + prices | 2026-08-19 |
| `pipeline/cases/miss-39500.json` | `web/data/cases/` | Redfin | 54 monthly records + prices | 2026-08-19 |
| `pipeline/cases/*.png` (4) | `web/data/cases/` | Redfin | charts plotting the above series | 2026-08-19 |

All four JSON files were downloaded by every homepage visitor until this date.
They remain in git history and must be scrubbed.

## Removed from the repo and the artifact — 2026-08-19 (Prompt 1)

| Path | Vendor | Contents | Where it went |
|---|---|---|---|
| `web/data/zips/*.json` (51) | Redfin, Realtor.com | 33,426 records, 31,947 carrying metrics, plus 36-month price/DOM history | `_private_data_export/web/data/zips/` — retained, gitignored, to be moved to private storage by the operator |

`web/data/zips/` is now **generated** by `pipeline/provision_readings.py` from
`pipeline/data/page_manifest.csv` (zip,state — no measurements) plus readings
pulled from the private store for released tranches only. With nothing
released, every generated record is `{"st": "MD"}`. Still in git history and
must be scrubbed.

## Still in the public repo — pending the history scrub

| Path | Vendor | Contents | Note |
|---|---|---|---|
| `pipeline/rentcast_stats.csv` | RentCast | 4,001 rows of current-month statistics | pushed by the acquisition workflow |
| `pipeline/snapshots/verdicts-*.json` (3) | Redfin | ~28k rows × 3 months of raw metrics | not just readings |
| `pipeline/tier_interim.csv` | Realtor.com | one derived count column | regenerate without it |
| `pipeline/cases/*` (8) | Redfin | moved out of the artifact 2026-08-19, still in the repo and its history | |

## Borderline, named rather than silently kept

`web/data/meta.json` carries `national.spy_deciles` — an eleven-value national
distribution of year-over-year price change, derived from vendor measurements
across every scored ZIP. It is an aggregate of the same kind as the published
research files, and it is what the withdrawn "rising faster than X% of ZIPs"
sentence was computed against. Nothing renders it while paused. Flagged so the
decision is made deliberately rather than by omission.

Held back, not yet pushed: the re-scored `web/data/zips` carrying 60,000
RentCast price points, on branch `backup-local`.

## Not on this list, and why

`pipeline/research/`, `pipeline/velocity/`, `web/data/velocity-aggregates.json`,
`web/data/cases/index.json`, `web/data/stories.json` — our own derived
indicators (counts, shares, deltas, ratings). No vendor measurements.
`pipeline/fhfa_zip.csv`, `acs_zip.csv`, `zip_cbsa.csv`, `zip_places.csv`,
`zip_centroids.json` — US Government works, public domain.
