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

## Still in the public artifact — pending Prompt 1

| Path | Vendor | Contents | Note |
|---|---|---|---|
| `web/data/zips/*.json` (51) | Redfin, Realtor.com | ~28,400 entries: metrics + 36-month price/DOM history | also served directly as bulk JSON at `/data/zips/{ST}.json` |
| `pipeline/rentcast_stats.csv` | RentCast | 4,001 rows of current-month statistics | pushed by the acquisition workflow |
| `pipeline/snapshots/verdicts-*.json` (3) | Redfin | ~28k rows × 3 months of raw metrics | not just readings |
| `pipeline/tier_interim.csv` | Realtor.com | one derived count column | regenerate without it |

Held back, not yet pushed: the re-scored `web/data/zips` carrying 60,000
RentCast price points, on branch `backup-local`.

## Not on this list, and why

`pipeline/research/`, `pipeline/velocity/`, `web/data/velocity-aggregates.json`,
`web/data/cases/index.json`, `web/data/stories.json` — our own derived
indicators (counts, shares, deltas, ratings). No vendor measurements.
`pipeline/fhfa_zip.csv`, `acs_zip.csv`, `zip_cbsa.csv`, `zip_places.csv`,
`zip_centroids.json` — US Government works, public domain.
