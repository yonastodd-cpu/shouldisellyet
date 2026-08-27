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
| GitHub GC request **PAUSED at our request** | 2026-08-22T13:40:24Z | **Our decision to pause; NOT yet communicated to GitHub.** The reply is drafted (`GITHUB_TICKET_PAUSE_REPLY.md`) and has not been posted, so the ticket is open, unactioned and carries no hold. GitHub can action it at any time. Corrected 2026-08-23 — an earlier row and memo revision 7 both described this as agreed with GitHub, which it is not. |
| **Legal hold in force; preservation archive created** | 2026-08-22T18:50:29Z | `LEGAL_HOLD.md` at repo root is the switch; archive held read-only (33 files hashed / 1.09 GB after the 22 Aug extension; manifest reissued 23 Aug) outside the repo with SHA-256 per file in `PRESERVATION_MANIFEST.md`. Two deletion paths changed to move-aside; `pipeline/test_legal_hold.py` fails if either is undone. |
| **Derived-use provenance inventory completed** | 2026-08-22T19:37:23Z | `DERIVED_USE_INVENTORY.md` (gitignored — it names open exposures and this repo is public). 51 published outputs have former-vendor data in their computation chain, 48 reachable by a third party today. Includes the finding that the v2 danger lines themselves have that lineage, which makes every live reading a mixed-lineage output. |
| **Realtor.com ingest paused; index/figures optionality built** | 2026-08-22T23:36:48Z | `SHOW_REALTOR_CROSSCHECK` default flipped to OFF and the raw CI curl that bypassed it guarded; `INDEX_MODE`/`INDEX_LICENSE` and `FIGURES_OFF` built as flags with defaults unchanged; capture-survey tool built plan-only. A served present-tense vendor credit in `web/data/meta.json` corrected (its figures preserved). |
| **Per-ZIP identifiers removed from committed release reports** | 2026-08-23T03:58:42Z | `research-2026-06/07.json` no longer name the 2,135 and 2,403 ZIPs that crossed into WATCH/ACT, nor 24 of 25 `top_streaks`; counts preserved, pages render identically. Originals preserved under `LEGAL_HOLD.md` and in git history. **NOT fixed:** `levels-*.json` and `streaks.json` still publish ~20,000 ratings per month for ZIPs whose own pages withhold one — see the note in `DERIVED_USE_INVENTORY.md`. |
| **Research state seeded into the private store** | 2026-08-23T16:20:53Z | `schema-v40` applied to production: `public.research_state`, RLS on, zero policies, no grants to `anon`/`authenticated`. All four keys written and **read back through the build's own PostgREST path** by the `seed-research-store` CI job. Committed files deliberately still in place — removal is a separate step. |
| **Per-ZIP research state removed from the public repository** | 2026-08-23T16:37:16Z | `levels-2026-05/06/07.json` and `streaks.json` untracked and gitignored — ~90,000 ZIP-to-rating pairs, ~73,000 of them for markets whose own pages withhold a rating. Gated on `--verify-store` reproducing July's published flip count (2,403) from the store with the files unreachable. Preserved in the archive and in git history. |

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
| **GitHub actioned ticket #4688700** | *timestamp not held — see note* | Reported to us as: **"cleared the cached views for the unreferenced commits"**. We do not hold the response timestamp or the message itself; both must be taken from the ticket and recorded here before this row is relied on. |
| **Ambiguity in that action, recorded** | 2026-08-25T02:15:35Z | Their wording describes the **view layer**. It does not say whether the underlying git objects were deleted. Our probes cannot settle it: GitHub refuses bare-SHA fetches for unreachable objects whether or not they still exist. **Clarification to be requested in writing.** |
| **Reopening / clarification reply to GitHub** | *NOT POSTED as at 2026-08-25T02:15:35Z* | No reply has been posted by this session and none is evidenced. The earlier hold reply (`GITHUB_TICKET_PAUSE_REPLY.md`) was also never posted — see the correction row of 2026-08-23. If a reply has since been sent from outside this session, its timestamp must be added here. |
| **GitHub-side state verified, read-only** | 2026-08-25T02:15:35Z | All 24 listed commits: web page **404**, `git fetch origin <sha>` **refused**. Control commits known reachable on `main` returned **200 / FETCHED** by the same method, so the refusals are not a probe artefact. Detail in `ARCHIVE_VERIFICATION_2026-08-25.md`. |
| **Preservation archive integrity re-verified** | 2026-08-25T02:15:35Z | Every file re-hashed against `PRESERVATION_MANIFEST.md`: **33 recorded, 33 present, 0 missing, 0 unrecorded, 0 hash mismatches — INTACT.** |
| **All 24 commits confirmed held locally** | 2026-08-25T02:15:35Z | Present in the pre-rewrite backup object store (24/24), in the archive's independent tarball of that store (24/24), and the archive bundle verifies as *"a complete history"*. Whatever was deleted upstream, we hold it. |
| **Credential rotation: no blocking items** | 2026-08-25T02:15:35Z | Independently swept, not inherited from the prior audit. Current tree: 0 Stripe/AWS/GitHub/private-key literals; 3 JWTs, all `role: anon` (public by design). Pre-rewrite history: one `(whsec_…)` documentation placeholder, 0 literals. Consistent with `AUDIT_REPORT.md` §3 and `GITHUB_PURGE_REQUEST.md` line 43. |
| **Go-live clearance: all five gates green** | 2026-08-25T18:09:44Z | Certified at commit `36f54ac`, deployed and verified in production. **As of 2026-08-25T18:09:44Z, no prior-vendor-lineage figure is reachable on any surface; private holdings preserved unchanged under LEGAL_HOLD.** Detail in `GO_LIVE_REPORT.md`. Reindexing held at the eyeball checkpoint. |
| **Research pages held back from search** | 2026-08-26T00:53:02Z | `RESEARCH_INDEXABLE = False` at commit `c82f218`, deployed and cold-fetch verified. All three research pages return `noindex,follow`; zero `/research` URLs in the sitemap (they were never in it). Reason: with figures dark the research hub is ~200 words, thin for search — the earlier decision to index assumed a truncated v2 series rather than a withheld-figures notice. Reversible by the same constant when a current-basis month closes. The 5,000 per-ZIP pages and `/press.html`, `/methodology.html` are unaffected and remain indexable. |
| **Final go-live review: CLEAR TO OPERATE** | 2026-08-27T02:17:10Z | 22-row review vs production in `FINAL_REVIEW.md`. Fresh gates A–E green; LEGAL_HOLD re-hashed 33/33 intact; money path evidenced by the first real on-demand sale (20874) plus live fail/dedupe probes. Two reds found and fixed in-review: stale methodology coverage pair (now build-stamped from the release contract, `18b4216`) and demand logging blind to direct ZIP-page visits (`92dfb95`). Yellow rows 2, 6, 9, 18, 19, 22 carry dated notes; operator confirmations outstanding: GitHub Actions failure emails received (row 19b), optional live-card synthetic purchase (row 6). Also this date: GitHub's reply on ticket #4688700 reported received but undated (see the "timestamp not held" row above — still to be recorded from the ticket); sitemap submitted to GSC 2026-08-25. |
| **Gate-failure alerting live-tested (review row 19b closed)** | 2026-08-27T02:34:52Z | Operator confirms BOTH GitHub Actions failure emails arrived (runs 33030565266 and 33030617282, the review night's two genuine failures). The gate-failure leg of `FINAL_REVIEW.md` row 19 is closed as live-tested, not assumed. Stale-data (19a) and webhook-failure (19c) alerting remain notes: no in-repo email exists for either. |
