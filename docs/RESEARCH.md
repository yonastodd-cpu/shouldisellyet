# ShouldISellYet Research — pipeline notes

The product is a citable monthly index. Everything here exists to protect
the one asset an index has: **a definition that never silently changes.**

## The pieces

| Piece | Runs | Does |
| --- | --- | --- |
| `pipeline/research.py` | CI, each refresh, **before** the digest | Restates the month to the 4-signal index definition from `web/data/zips` shards, appends to `research/history.json`, advances `streaks.json`, writes `levels-{month}.json` (next month's flip base) and `research-{month}.json` (everything a release consumes) |
| `pipeline/build_research.py` | CI, **every deploy** (beside `build_pages.py`) | Builds `/research/` hub, per-month release pages, both press charts, the OG stat card, the 4-image social set, CSVs + LICENSE, and `methodology.html` — from committed JSONs only, no network |
| `pipeline/fetch_cbsa.py` | By hand, per OMB delineation revision (~5-yearly) | Rebuilds `data/zip_cbsa.csv` (ZIP→metro) |
| Growth digest | CI, after research | "Research release" section: headline, bullets, asset links, inline pitch draft; `PRESS_LIST` env writes per-outlet drafts to `archive/{month}/press-drafts/` — generated, never sent |

Committed state lives in `pipeline/research/`: `history.json` (172 months of
national/state/metro aggregates), `streaks.json`, `levels-{month}.json`,
`research-{month}.json` per release, `changelog.json`.

## The index, in one breath

WSI = ZIPs at WATCH or ACT ÷ scored ZIPs. Four signals (supply, price y/y,
time-to-sell y/y, inventory y/y) at the site's published thresholds,
evaluated by the live verdict engine with price-cuts withheld — constant
methodology since the series begins. Insufficient-data ZIPs are out of both
numerator and denominator. STRONG is denominator-only.

## The seam, and the restatement rule

- **Continuous series: 2020-06 → present** (Redfin hub, ~25k scored
  ZIPs/month). Records, deltas, superlatives live here and nowhere else.
- **Context tail: 2012-03 → 2020-05** (legacy tracker, ~18k ZIPs).
  Lighter stroke on the chart, excluded from records.
- Measured cross-source agreement over the 72 overlap months: **72.74%**
  of 1.36M shared zip-months — similar, not the same. That number is why
  the segments never share a superlative.
- The current month always comes from the site's own shards, not a fresh
  hub download: Redfin republishes the file daily (measured drift ~1.5% in
  one day), and the index must match the ZIP pages a reader can check.

**Rule: any change to thresholds, signals, sources, or the scored
definition bumps the version in `changelog.json`, restates history where
the data permits, annotates the WSI chart at the change month
(`"annotate": true`), and states what changed in plain language.** The
methodology page renders the changelog verbatim. Never edit a published
month's number without a changelog entry that explains it.

## Re-running the backfill

History is reproducible: the legacy tracker is frozen, and the hub file is
re-downloadable (revisions restate the hub segment — that is the
restatement rule working, not an error; note it in the changelog if
material).

```
python3 pipeline/research.py --backfill \
    --hub /path/all_zips.csv --tracker /path/zip_code_market_tracker.tsv000.gz
```

Sources: hub `redfin_data_center/housing_market/monthly/all_zips.csv`;
legacy `redfin_market_tracker/zip_code_market_tracker.tsv000.gz` (frozen
2026-06). Expect ~6 minutes and ~3M scored zip-months per source.

## Release cadence (operator)

Generation is automatic at each refresh; **publication discipline is
yours**: pitch on the third business day after the refresh lands, every
month, same day — consistency is what trains journalists to expect it. The
digest hands you the headline, bullets, assets, and a pitch draft;
`PRESS_LIST` gives you per-outlet files to personalise. Nothing auto-sends.

Launch sequencing per the concept doc: one quiet release to shake the page
out, pitch from month two, measure citations and CSV downloads, three
consecutive releases with any citation before building the widget.

## CSV field lists (the licence boundary)

Public CSVs carry derived indicators ONLY:

- `wsi-history.csv` — month, wsi_pct
- `state-aggregates-{m}.csv` — state, scored_zips, hold, watch, act,
  strong, warning_share_pct, delta_pts
- `metro-aggregates-{m}.csv` — cbsa, metro, scored_zips,
  warning_share_pct, delta_pts
- `zip-flips-{m}.csv` — zip, city, state, from_verdict, to_verdict

No upstream Redfin/Realtor metric columns may be added to public files
without counsel review against both sources' terms — the verdict layer is
ours; their raw data is not.
