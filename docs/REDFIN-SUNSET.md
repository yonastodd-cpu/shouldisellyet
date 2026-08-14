# Redfin sunset — Phase 0 record

**Ingestion stopped when the gate reached main** — see `INGESTION_STOPPED_UTC`. That timestamp is the answer to
"when did you stop using it," and it lives in `pipeline/data_pause.py`
(`INGESTION_STOPPED_UTC`) so it cannot drift from the behaviour it describes.

**A refresh beat the gate.** A scheduled run completed at 2026-08-13T14:27:12Z
and committed a full 2026-07 Redfin snapshot (commit `5d79b43`) — after the
decision to stop, before the gate shipped. That data is in the repo, is tagged
`source='redfin'` like the rest, and is paused along with everything else. The
stop timestamp was corrected to the moment the gate actually landed rather than
the moment the decision was made; a stop time that flatters the record is worse
than none, because it is the one field somebody relies on later.

Phase 0 of the Redfin→RentCast migration. No page was deleted, no URL was
retired, nothing 404s or redirects, and the site stayed up throughout.

## The switch

Everything is one flag: `PAUSED` in `pipeline/data_pause.py`, mirrored by
`DATA_PAUSED` in `web/index.html` because the homepage is committed rather than
generated. A test asserts the two agree.

To re-enable: set both to `false` and deploy. Phase 4's tranches add a ZIP
allowlist inside `data_pause.shows_data()`; until then it is all-or-nothing.

## What was actually done

**0.1 Ingestion stopped.** `update.yml`'s check step now forces
`changed=false` while keeping `deploy=true`. That distinction is load-bearing:
every generated directory is gitignored and rebuilt on each deploy, so
stopping the *build* would delete ~23,000 live URLs — the one thing this
migration forbids. The ETag probe is left in place but unreachable so the
record of how the gate worked survives.

The workflow gate does not disarm anything run by hand, so the guard is also on
the network path of `fetch_data.py`, `tools/backtest_cases.py` and
`backtest_thresholds.py`. It refuses **remote** fetches only — a local
`--input` still works, which is how the tests run and how a re-run against a
new vendor's export will run.

**Known side effect:** eleven downstream steps gated on `changed` also stop,
none of which touch Redfin — subscriber alert emails, the Supabase velocity
upsert, the marketing queue generator. That is correct for now: each would
publish or notify on numbers Phase 0 has just withdrawn.

**0.2 Provenance.** `schema-v34.sql` adds `source` and `retrieved_at` to
`zip_velocity` (27,405 rows) and `source` to `marketing_tasks`. `subscribers`
is deliberately untouched — it already has a `source` column meaning *signup
channel*, and writing `'redfin'` onto it would corrupt attribution data to
answer a question it was never asked. `retrieved_at` is backfilled to the last
day of the period each row describes, documented in the column comment as an
approximation rather than a recorded instant, because no true retrieval
timestamp was ever stored.

**Nothing was deleted.** Posture until counsel answers question #1: stop
displaying, stop computing, retain.

**0.3 Deindexed and blanked.** `noindex,follow` on every affected page; pages
still return 200; robots.txt still allows crawling — a blocked page is never
crawled, so its noindex is never read and the URL lingers indefinitely.
Affected URLs are held out of the sitemap in `build_pages.py`, which is the
only place possible since the sitemap is generated fresh each deploy.

The blanking goes past the body. On a paused ZIP page the verdict and metrics
are removed from the `<title>`, the meta description, the OG and Twitter tags,
the JSON-LD `@graph` (including the FAQ answer), the share text, and the OG
image, which falls back to the brand card. A banner over the gauges would have
left every one of those serving withdrawn numbers to crawlers, social unfurls
and anyone opening a shared link.

**0.4 Traffic snapshot.** `docs/migration/phase0-traffic-snapshot.json`.

## Corrections to the written plan

The plan was drafted against assumptions this codebase does not meet. Each of
these was verified before acting:

| Plan said | Actually |
|---|---|
| Homepage is not Redfin-dependent, leave untouched | It renders the rating and all four gauges inline from the same per-ZIP JSON. Paused too. |
| Remove affected URLs from the sitemap | The 609 metro pages are in **no** sitemap; only `noindex` deindexes them. |
| Add a `source` column to the metrics tables | No provenance field existed anywhere, and `subscribers.source` means something else. This is a schema change, not an annotation. |
| Export top ZIPs from Search Console | There is no Search Console, and no analytics beyond first-party counting. |
| Hide the values behind a banner | The values are also in the title, meta, OG tags, JSON-LD and a pre-rendered PNG. |
| Pages not built on Redfin data stay untouched | On the `/zip/` side that set is empty — all 22,874 derive their verdict from Redfin columns alone. |

**The traffic snapshot cannot rank Phase 4's tranches.** `public.events` is
first-party anonymous counting that honours DNT/GPC, so those visits are never
recorded at all. It holds an 8-day window: 3,068 events, 2,021 distinct ZIP
paths of 22,874 pages, a maximum of 27 views on any single page, 1,558 seen
exactly once, and 17 Google referrals in total. There is no organic-search
signal in it. Phase 4 needs Search Console connected — and connecting it
*before* the tranches start is now on the critical path, because the ordering
it produces is the whole basis of the reindex plan.

## Marketing queue

All 32 queued posts set to `skipped`. Each quoted a figure Phase 0 withdrew and
deep-linked to a page now serving the refresh notice. `status_reason` is a
four-value enum, so the reason is recorded in
`supabase/hold-queue-redfin-sunset.sql` and here rather than crammed into a
column that cannot hold it. Reversible — but Phase 4 should regenerate rather
than un-skip, since the numbers will have moved.

## Still open — attorney batch

1. **Retention vs deletion** of stored Redfin-derived data. Nothing has been
   purged; tagging first is what makes a later purge precise rather than broad.
2. **RentCast API ToU** review before the migration rides on it.
3. **Realtor.com / Zillow research-data licences** for commercial display with
   attribution, if they feed the rebuilt formula.
4. **Updated ToS/methodology disclosures** naming the new sources.

## Not done in Phase 0, deliberately

- **The four free research CSVs are still published.** Their columns carry
  verdicts, counts, shares and deltas rather than raw vendor metrics, and
  `LICENSE.txt` grants commercial republication with attribution to
  ShouldISellYet. Every value in them is nonetheless vendor-*derived*, and the
  chart PNGs beside them bake in numbers with no source line. If the driver for
  this migration is licensing, **public redistribution is the highest-exposure
  surface on the site** and it outranks any rendered page. It was left alone
  only because the plan did not name it and pulling published downloads is a
  decision with its own consequences.
- **`docs/ATTRIBUTION.md` is stale in three ways** — it documents a homepage
  sources strip deleted on 2026-08-12, a marketing line that no longer exists,
  and a surface table missing the metro pages, the story page and the OG cards.
  Those three surfaces publish vendor-derived metrics with *no* attribution at
  all, which also means a grep for "redfin" does not find them. The sweep in
  the plan's "anything else" list should start there.
