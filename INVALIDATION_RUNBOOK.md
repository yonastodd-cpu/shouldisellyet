# Social-preview invalidation runbook

Until 2026-08-19 our page titles, descriptions, OpenGraph tags and preview
images carried market readings that have since been withdrawn. The code is
fixed and verified in production. This covers what external platforms cached
before the fix, which we cannot reach from code.

## What production serves now (audited 2026-08-19)

42 URLs — 20 ZIP pages, 10 state indexes, 8 share stubs, homepage, `/zip/`,
report and press — checked for rating words and market figures across
`<title>`, `description`, and every `og:*` / `twitter:*` tag.

**No leaks.** Two pages matched the detector and are correct as written:
`/zip/` and `/press.html` describe the product ("HOLD / WATCH / ACT verdicts
for 22,874 U.S. ZIP codes"). Naming the rating vocabulary is what the site
is; publishing a specific ZIP's rating is what stopped.

Also closed on 19 August, found during this audit: **~3,400 per-ZIP preview
images** at `/og/{period}/{zip}.png` were still being generated and deployed
with the verdict and a figure painted into the pixels. No page linked them —
they had pointed at the brand card since the pause began — but the files were
live at 200 and reachable by anyone holding a URL from an earlier share.

## Why there is no cache-bust parameter in this release

The usual fix is to version the image URL so platforms keyed on it refetch.
It is unnecessary here and would be misleading:

- Paused pages **already** changed their `og:image` from
  `/og/{period}/{zip}.png` to `/og/default.png`. The URL a platform sees on
  re-scrape is different, so a version suffix adds nothing.
- The old per-ZIP image URLs now **404**. A platform serving a stale preview
  is serving its own cached copy, which a version parameter on our side
  cannot touch.
- Versioning `default.png` would force a refetch of a brand card that has not
  changed, spending re-scrape quota to deliver the same bytes.

Add versioning when readings return in Phase 4 — at that point image content
changes per release and the URL should change with it.

## Priority order for manual re-scrape

Highest exposure first: pages most likely to have been shared while showing a
reading.

1. `https://shouldisellyet.com/` — homepage
2. The 10 largest state indexes: MD, VA, DC, TX, CA, NY, FL, IL, PA, OH
3. `/s/{zip}/` share stubs for any ZIP known to have been shared — these
   exist only to be shared, so they are the likeliest to sit in a cache
4. High-traffic ZIP pages. **We cannot rank these yet**: Search Console is not
   returning impression data (see `SEARCH-CONSOLE.md`), so use the interim
   ranking in `pipeline/tier_interim.csv` and say plainly that it is a
   supply proxy, not a traffic ranking.

## Per platform

| Platform | Purge tool | Reality |
|---|---|---|
| **Facebook / Meta** | Sharing Debugger → "Scrape Again"; batch via the Graph API (`POST /?id={url}&scrape=true`) | The only one with a real programmatic purge. `scripts/rescrape-og.sh` drives it. Needs an app access token. |
| **LinkedIn** | Post Inspector → inspect the URL | Manual, one URL at a time. Refreshes on inspect. |
| **X / Twitter** | Card Validator was retired | No forced refresh. Cache expires on its own, typically within about a week. Waiting is the remedy. |
| **WhatsApp, iMessage, Telegram, Slack** | none | These cache per-client or per-conversation with no public purge. **Expiry is the only remedy**, and a preview already delivered into a conversation is a screenshot that cannot be recalled. Set expectations accordingly. |
| **Google** | URL Inspection → Request Indexing | Affects search results, not social previews. Only worth doing for pages already indexed. |

## Verification

After re-scraping, paste three URLs into Facebook's Sharing Debugger and
LinkedIn's Post Inspector and confirm the preview shows the neutral state:

- title "… housing market — reading being refreshed"
- description "This market reading is being rebuilt on a new data engine…"
- image the brand card, not a card with numbers on it

Then re-run the production audit:

    python3 scripts/audit-og.py scripts/og-priority-urls.txt

## Honest limits

We cannot enumerate every shared URL — the site has no record of what was
shared, only that share stubs were generated for all 22,874 ZIPs. We can
purge what we can name and let the rest expire. Nothing here recovers a
preview already sitting in someone's message history.
