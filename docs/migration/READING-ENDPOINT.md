# The per-ZIP reading endpoint — what it is and the order to ship it in

`supabase/functions/market-reading` serves one ZIP's reading. It replaces the
browser fetching `web/data/zips/{ST}.json` — a whole state's records — to
display a single ZIP.

## Why it is needed, and why not today

While the site is paused every record in those files is `{"st":"MD"}`, so the
bulk fetch currently exposes nothing: a state file is 7.6 KB of ZIP codes.

That changes the moment Phase 4 releases a tranche. Released ZIPs get their
readings provisioned back into those same files, and a page that downloads 300
records to show one is republishing 299 of them to anyone with the network tab
open. **This endpoint must be deployed and the clients switched before Tranche
1, not after.**

## Ship order — it matters

1. **Apply `supabase/schema-v36.sql`.** Creates `public.zip_release`, the
   server-readable copy of the release allowlist.
2. **Deploy the function.** `supabase functions deploy market-reading`, then
   disable "Enforce JWT verification" on it, matching `verify-access`.
3. **Verify it responds** before touching any client:
   `curl 'https://<project>.supabase.co/functions/v1/market-reading?zip=20601'`
   — expect `dataStatus: "pending_migration"` with a null reading, because
   nothing is released.
4. **Only then switch the clients.** Six call sites fetch the bulk file:
   `index.html:1158`, `address.js:144`, `my-report.html:969`,
   `report.html:553`, `admin.html:671` and `admin.html:1928`.

Steps 1–3 are deliberately not automated here. Pointing the homepage ZIP
lookup — the site's primary interaction — at an endpoint that does not answer
yet would break the front door to fix a leak that does not exist yet.

## What the function will and will not return

It is the republication boundary. Every field is named explicitly; there is no
`select *`, and `market_stats.raw_json` is never read. Adding a field to a
SELECT list is a decision to publish it, and
`pipeline/test_market_reading_fn.py` pins the whole allowed set so widening it
has to be deliberate.

`dataStatus` distinguishes three kinds of nothing:

| value | meaning | page renders |
|---|---|---|
| `ok` | released, has a reading | the reading |
| `pending_migration` | not in a released tranche | the rebuilding notice |
| `insufficient_data` | released but too thin to read | honest no-reading state, stays noindexed |

An unreleased ZIP and an unknown ZIP return the same shape on purpose.
Distinguishing them would let a caller map the release plan before it ships.

## A blocker for Tranche 1 that is not in this endpoint

`web/index.html:1089` holds `const DATA_PAUSED = true`, and the render branch
at 1832 keys off it. It is a **page-level boolean**, and
`pipeline/test_data_pause.py` pins it to `data_pause.PAUSED` so the two cannot
drift.

That means the homepage cannot honour a tranche. Release Tranche 1 and the
homepage still tells those 1,000 ZIPs their reading is being refreshed,
because the flag knows nothing about which ZIP was asked for. The only
available lever is flipping it globally — which republishes readings for the
~21,900 ZIPs that are **not** released.

So the per-ZIP switch is not merely an efficiency change. Until the homepage
takes its pause state from `dataStatus` per ZIP rather than from a constant,
Phase 4 has no working front door. Two consequences to plan for:

- The `test_data_pause.py` assertion has to move with the flag, or removing
  the constant fails the build.
- `insufficient_data` should route to the existing limited-data copy
  (`index.html:1851`), not the pause notice. Different situations deserve
  different sentences.

Also worth measuring before the switch: a repopulated `CA.json` is roughly
500–650 KB for a visitor checking one ZIP, and the share-arrival path
(`index.html:2019`) downloads a **second** whole state to render one sentence
about the sharer's ZIP.

## The admin surfaces are a known exception

`admin.html` scans shards for its ops queue and genuinely wants many ZIPs at
once. Forcing it through a per-ZIP endpoint is thousands of requests. It needs
either a service-role query inside the authenticated admin session or an
accepted slower path — decide that when the clients are switched rather than
leaving a dangling bulk fetch.
