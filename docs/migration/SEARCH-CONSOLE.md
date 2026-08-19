# Search Console — access, credentials, and what the data can and cannot say

`pipeline/fetch_gsc.py` pulls the per-ZIP impression ranking that Phase 1's
Lever 1 and Phase 4's tranche order both depend on. This is the setup around
it, and the honest limits on what it can return today.

## State as found

- `shouldisellyet.com` carries a live TXT record
  `google-site-verification=Pl42pMKLLqaISlVPLHJAv5_5hMMjLCt10ZkR-pnNpO0`.
  That is the **Domain property** method, which covers http/https/www and
  non-www in one property. DNS is at Cloudflare; hosting is GitHub Pages.
- Phase 0 recorded that Search Console was never connected. The record says
  otherwise — a property was verified at some point. Whether it still exists,
  under which Google account, and how far back it holds data are questions
  that need a Google login.
- Bing is separately verified (`web/BingSiteAuth.xml`) and IndexNow is wired
  (`pipeline/indexnow.py`). Google was the only gap.

**The TXT record alone does not grant API access.** It proves domain
ownership to whichever account used it. If that account is not the one
minting the OAuth token below, the API returns 403 and the puller says so
explicitly.

## Step 1 — confirm the property (human, 2 minutes)

At [search.google.com/search-console](https://search.google.com/search-console),
signed in as the site's Google account, look for a `shouldisellyet.com`
**Domain** property.

- **Present:** open Performance and set the range to 16 months. Whether any
  data predates **2026-08-14** (when Phase 0's `noindex` landed) decides
  whether a pre-pause ranking exists at all.
- **Absent:** Add property → Domain → `shouldisellyet.com`. The TXT record is
  already in place, so Verify succeeds immediately — do not remove or replace
  the record, and note that a *new* property starts collecting from that day
  with no backfill.

`pipeline/fetch_gsc.py --probe` answers the same question in one request once
step 2 is done, and is the version that gets written down.

## Step 2 — OAuth credentials (human, one time)

Three secrets, read-only scope
`https://www.googleapis.com/auth/webmasters.readonly`:

| Secret | Where it comes from |
|---|---|
| `GSC_CLIENT_ID` | Google Cloud console → APIs & Services → Credentials → OAuth client ID, type **Desktop app** |
| `GSC_CLIENT_SECRET` | same screen |
| `GSC_REFRESH_TOKEN` | the one-time consent exchange below |

Enable the **Google Search Console API** on the project first, and add the
site's Google account as a **test user** on the OAuth consent screen (or
publish the app — see the caveat below).

To mint the refresh token, complete the consent flow once in a browser and
exchange the resulting code. Any standard OAuth desktop flow works; the
puller itself only ever uses the refresh token.

**Caveat that bites later:** while the consent screen is in *Testing*, Google
expires refresh tokens after **7 days**. A puller that worked all week and
dies on day 8 is this, not a code change. Publish the app (it stays
private — an unverified app with a read-only scope and one internal user does
not need Google's verification review) before wiring it into any scheduled
run.

Store all three as repository secrets, never in the repo — same posture as
`SUPABASE_SERVICE_KEY` and `RESEND_API_KEY`.

## Step 3 — run it

```
python3 pipeline/fetch_gsc.py --probe          # how far back does data go?
python3 pipeline/fetch_gsc.py                  # 90-day per-ZIP ranking
python3 pipeline/fetch_gsc.py --input archive/gsc/<window>   # re-parse, no quota
```

Output is `pipeline/gsc_zip.csv` — `zip,clicks,impressions,ctr,position`,
most impressions first. Every raw response is kept under `archive/gsc/`
(gitignored), so re-parsing and re-ranking never costs another request.

Notes on the numbers, all of which the tests pin:

- Trailing-slash variants are distinct URLs to Search Console and are summed
  into one ZIP. Counting them separately would halve the ZIPs that Tier A is
  chosen on.
- `position` is impression-weighted, not averaged. Two pages at position 4
  (900 impressions) and 40 (100 impressions) average to 22, which is nowhere
  near where the ZIP actually shows up.
- State hubs (`/zip/MD/`), share stubs (`/s/…`) and the index never enter the
  ranking.
- The window ends `--lag` days back (default 3). Search Console's last two
  days are incomplete, and a partial day understates exactly the pages being
  ranked.

## What this cannot tell you yet

Impressions accrue only for URLs that can appear in search results. Every one
of the 22,874 ZIP pages currently serves `noindex,follow`, and the live
submitted sitemap is four URLs. So unless the property holds pre-pause
history, a run today correctly returns **no ZIP rows at all**.

The puller does not paper over this. An empty result prints why, points at
correction 1 in `PHASE1-PLUS.md`, and **refuses to overwrite a populated
`gsc_zip.csv` with an empty one** unless `--allow-empty` is passed — because
the failure mode that costs money is not a crash, it is a plausible-looking
zero-row ranking that somebody spends $199 against.

Until then the interim Tier A ranking is mandatory: housing units ×
FHFA-covered × RDC not `quality_flag`ged. Connect Search Console anyway — it
earns the coverage and indexing diagnostics Phase 4 needs to watch
deindex-to-reindex, gives query data on the four still-indexed URLs, and
starts accruing the moment Tranche 1 lifts `noindex` on Tier A.
