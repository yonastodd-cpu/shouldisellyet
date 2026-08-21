# Remediation dates

Dates that go into the counsel memo. Recorded when the change was **deployed
and verified live**, not when it was written — an earlier draft of the memo
dated a withdrawal from the day we believed it happened and was wrong twice.

| What | When (UTC) | Verified how |
|---|---|---|
| Redfin ingestion stopped | 2026-08-14T13:53:43Z | `data_pause.INGESTION_STOPPED_UTC`; network fetch guarded in code |
| Redfin display stopped — first pass | 2026-08-19 | five surfaces fixed; see `ABSENCE_TEST_AUDIT.md` |
| Redfin display stopped — actual | 2026-08-20 | two more surfaces found live (`/report.html`, `/press.html`) and fixed. **This is the honest date.** |
| Research-file licence narrowed | 2026-08-20 | nine grant surfaces; `test_research_license.py` |
| Methodology page + revised ToS published | 2026-08-20 | `/methodology.html`; ToS effective 20 Aug 2026 |
| Tranche 1 released (1,000 ZIPs) | 2026-08-20T18:22:28Z | `pipeline/tranches.json`; `public.zip_release` |
| Tranche 2 released (4,000 ZIPs) | 2026-08-20T19:51:54Z | same |
| **Bulk-downloadable serving of underlying figures stopped** | **2026-08-21T01:36:16Z** | see below |

## Bulk serving of underlying figures

**Bulk-downloadable serving of underlying figures stopped 2026-08-21T01:36:16Z; figures now
render per-page only.**

Until that timestamp two paths distributed the vendor's underlying
measurements rather than displaying them:

- `/data/z/{zip}.json` — 5,000 files named by ZIP code, each carrying seven
  current metrics and a twelve-month series of asking prices and
  days-on-market. Roughly **120,000 raw monthly vendor values**,
  unauthenticated, complete, and collectable by iterating five digits. Two
  fields and the entire history rendered on no page at all: this file was
  their only exit.
- `/metro/{slug}/` — each of 608 metro pages carried a per-ZIP table with a
  price-vs-last-year column. One fetch of `/metro/new-york-ny/` returned 211
  ZIPs' figures; **4,699 distinct ZIPs — 94% of everything released — were
  harvestable in 608 requests**, against 22,874 for the per-ZIP files. Denser
  than the artifact above, and it did not look like a data file.

After that timestamp:

- Public per-ZIP records carry **our own output only** — the reading word, its
  basis, the month it is as of, and the state. Not one vendor measurement.
- Each page renders **its own ZIP's** figures, baked into that page's HTML at
  build time from a private directory that is never deployed.
- Runtime figures come from `market-reading`, one ZIP per request,
  rate-limited, CORS-pinned, named columns only, never `raw_json`. There is no
  list form and no wildcard.
- Metro tables list ZIP, city and rating. The rating is ours; the figures
  behind it are on that ZIP's own page.

This does not make collection impossible and is not meant to. It makes what we
operate a page-display service rather than a distribution channel, which is
the distinction the licence question turns on.
