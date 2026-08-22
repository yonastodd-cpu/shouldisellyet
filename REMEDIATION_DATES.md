# Remediation dates

Dates that go into the counsel memo. **Times are UTC**, with local in brackets where the two fall on different days — the submission below was the evening of 21 August locally and the 22nd in UTC, and a memo that says one without the other invites a question nobody wants to answer twice.

Recorded when the change was **deployed
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
| **Per-ZIP research file withdrawn** | **2026-08-21T03:22:25Z** | see below |
| GitHub GC request **prepared** | 2026-08-21 | `GITHUB_PURGE_REQUEST.md` |
| GitHub GC request **submitted** | 2026-08-22 | ticket #4688700 |
| GitHub GC request **PAUSED at our request** | 2026-08-22T13:40:24Z | asked to hold, **not withdrawn**. Preservation of the objects now takes precedence over their removal. |

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


## Per-ZIP research file withdrawn

**Publication of the per-ZIP ratings file stopped 2026-08-21T03:22:25Z.** Affected months:
**2026-06** (`zip-flips-2026-06.csv`, 2,135 rows) and **2026-07**
(`zip-flips-2026-07.csv`, 2,403 rows). Both are gone from
`https://shouldisellyet.com/research/{month}/`. The state and metro
aggregates, the Warning-Sign Index history, the charts and the release pages
all continue.

The same rows were also rendered on each release page as HTML — 55 per-ZIP
rating rows, 40 flips and 15 streaks. Those are withdrawn too: removing the
file while leaving its contents on the page would have been a change of format
rather than of practice.

Decided for three reasons:

- It distributed the core product output in bulk under an open grant, while
  the site itself serves readings a page at a time.
- It published ratings for ZIP codes whose own pages withhold them. Of the
  2,403 rows in the July file, **1,946** were ZIPs the site was declining to
  rate; of the 55 ZIPs named on the July release page, **47** were.
- Counsel's review of the grant is pending, and the aggregates are the
  defensible subset of what it covers.

Journalist-facing copy now reads "Per-ZIP data is available on request for
specific stories", which keeps the press relationship without the open bulk
grant. `web/research/` is generated on every deploy, so the takedown is the
generator change — there is no separate deletion step, and the files stop
existing at the next build.


## GitHub garbage collection — three stages, tracked separately

The counsel memo needs to state each of these accurately, and they are not the
same event. Until the third line has a date, the repository still holds the
objects.

| Stage | Date | Evidence |
|---|---|---|
| History rewritten and force-pushed | 2026-08-20T02:57Z | `HISTORY_SCRUB_NOTES.md`; verified from a fresh clone |
| GC request **prepared** | 2026-08-21 | `GITHUB_PURGE_REQUEST.md` — 24 commits, 71 files, blob hashes |
| GC request **submitted** | 2026-08-22T01:17Z (21 Aug, 21:17 EDT) | GitHub Support ticket **#4688700** (Repositories → Repository features) |
| GitHub **confirmed** complete | *(blank — awaiting reply)* | written confirmation and effective date |
| **Outcome** | *(blank — pending)* | granted / refused. Not a formality — see below. |

**Fork network: empty** (`forks_count: 0`, `network_count: 0`, checked
2026-08-21). Garbage collection on our repository would not purge forks, so this
matters: had there been any, the request would have been insufficient on its
own.

**The accurate statement until confirmation arrives:** history was rewritten
and force-pushed on 20 August 2026; the original objects remain on GitHub's
servers, unreferenced but retrievable by commit SHA; garbage collection has
been requested and is not yet confirmed. Anything stronger overstates it.


### The outcome may be a refusal, and the memo must allow for it

Submitting this is not the same as it being granted. GitHub's own triage
answered the request before a human saw it, and said:

> GitHub Support can help with server-side cleanup only for **sensitive data**
> removal cases … GitHub Support won't remove non-sensitive data, and will only
> assist where the risk cannot be mitigated by rotating affected credentials …
> GitHub's published process does **not** support a request to purge
> unreachable objects solely for licensing or redistribution reasons when the
> content is not classified as sensitive data.

That was machine-generated and is not a decision, and the same answer directed
us to file anyway so Support could review it directly. But it is the published
policy, and it may be the answer.

The argument put to them is that the case satisfies their own test rather than
seeking an exception to it: their criterion is whether the risk can be
mitigated by rotating credentials, and licensed third-party data cannot be
rotated. A leaked key can be invalidated and reissued; a vendor's dataset
cannot. Removal from storage is the only available mitigation.

The ticket asks for a refusal in writing if it comes to that, because a clear
refusal settles the question as usefully as a confirmation. **If GitHub
declines, "gone from the repository" never becomes true**, and the permanent
accurate statement is "unreferenced but retrievable by commit SHA". Counsel
needs to know which of those two worlds this is, and until the reply lands
nobody does.

One failure mode to watch for: a reply that clears cached commit views and
closes the ticket without running collection. Caches and storage are different
things, and only the second is what question 1 turns on.
