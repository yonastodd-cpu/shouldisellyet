# Data flow — where each source enters, and where it can be switched off

One page for the question "if a vendor's answer comes back unfavourable, what
do I turn off, and what breaks?"

## Sources

| Source | Status | Feeds a reading? | Switch |
|---|---|---|---|
| **RentCast** `/markets` | Paid, active | **Yes — the only one** | none yet |
| **Realtor.com** RDC inventory CSV | Free download, dormant | No — display cross-check only | `SHOW_REALTOR_CROSSCHECK` |
| **FHFA** ZIP house price index | Public domain | No — threshold backtest, benchmark | n/a |
| **U.S. Census** ZCTA / CBSA | Public domain | No — metro mapping, place names | n/a |
| **Freddie Mac** PMMS | Public | No — rate context on paid reports | n/a |
| **Redfin** | **Discontinued 14 Aug 2026** | No | `data_pause.PAUSED` |

## The reading path

```
fetch_rentcast.py  → archive/rentcast/         (private, gitignored)
load_market_stats.py → market_stats + market_history   (Supabase, private)
rescore_v2.compact() → {l, s, r, b, m, h}
provision_readings.py → web/data/z/{zip}.json  (public, one file per ZIP)
build_pages.py     → web/zip/{zip}/index.html  (public)
```

Two gates sit across that path. `data_pause.PAUSED` withholds every reading;
`tranches.json` releases them back a tranche at a time. Both are Python
module state, flipped by editing and deploying — see `pipeline/data_pause.py`.

## The Realtor.com kill switch

`SHOW_REALTOR_CROSSCHECK` (default **on**) exists because the Realtor.com
research figures are under licence review and the answer is not in yet. Setting
it to `0` means no Realtor-derived value is fetched, written into `web/`, or
credited to a reader: `fetch_data.py` skips the download entirely rather than
downloading and discarding, `provision_readings.py` strips any cross-check
block that reaches a public record, and the credit disappears from the research
footer and from `llms.txt`. It is deliberately enforced at the producer and the
writer rather than at the renderer, because the figures used to ship inside
every public per-ZIP record — a reader with the network tab open had them
whether or not the strip was drawn, so hiding it would have changed nothing
that matters. `pipeline/realtor_crosscheck.py` is the only place that decides;
`pipeline/test_realtor_crosscheck.py` exercises both positions.

Being a static site, flipping it is a CI variable change **plus a rebuild** —
no code edit and no review, but not instant. There is no server to re-read it.

Two things worth knowing before flipping it. The cross-check is already dormant:
the strip compared against the discontinued vendor's figures and was never
rebuilt for RentCast, and no provisioned record has carried the block since the
pause, so switching off changes credits and future fetches rather than anything
a reader sees today. And `entry["x"]` once had a second consumer —
`rank_interim.py` gated two of its six eligibility tests on it and used it as
the ranking tiebreak — so a switch aimed at display would have silently emptied
the paid-tier ordering that targets metered RentCast calls. That ranking is now
frozen and its inputs are withdrawn, but a new consumer must not be added
without re-reading this paragraph.

## Where a figure can still leave

Everything under `web/` ships. `pipeline/surfaces.py` enumerates every surface
that can publish one and names the test asserting its absence; a surface added
without a test fails the build. The research releases under `web/research/` are
the known exception — they publish per-ZIP verdicts that the pause withholds
elsewhere, recorded as a deliberate deferral in `docs/REDFIN-SUNSET.md`.
