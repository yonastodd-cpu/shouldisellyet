# Search Console submission — steps for the operator

Prepared 2026-08-25T18:16:04Z. Staged at commit `36f54ac` (plus the research-indexable change,
committed below). **Nothing has been submitted; every step here is yours.**

## What is staged

| | |
|---|---|
| Sitemap index | `https://shouldisellyet.com/sitemap.xml` |
| Chunks | 1 (`/sitemaps/pages-1.xml`) |
| URLs | **5,003** — 5,000 live per-ZIP readings + 3 hub pages |
| Verified | Every sitemap URL is indexable; every released ZIP is in the sitemap. Checked both directions. |
| Left out, deliberately | The **17,874** rebuild-notice pages. They return 200 and keep `noindex,follow`. |

Also now indexable: `/press.html`, `/methodology.html`, `/research/`.

## Steps

1. **Confirm the deploy landed.**
   ```bash
   curl -sS https://shouldisellyet.com/sitemap.xml | head -20
   ```
   You want one `<loc>` pointing at `/sitemaps/pages-1.xml`.

2. **Spot-check three pages return no robots meta.**
   ```bash
   for u in /zip/20901/ /press.html /research/; do printf "%s " "$u"; curl -sS "https://shouldisellyet.com$u" | grep -c 'name="robots"'; done
   ```
   All three should print `0`. A `1` means something is still noindexed — stop and say so.

3. **Confirm a notice page is still excluded.**
   ```bash
   curl -sS https://shouldisellyet.com/zip/63764/ | grep -o '<meta name="robots"[^>]*>'
   ```
   Must print `noindex,follow`. If it does not, the 17,874 are being offered and that is a stop.

4. **Submit in Search Console.**
   Property → **Sitemaps** → enter `sitemap.xml` → Submit.
   Only if steps 2 and 3 both behaved.

5. **Request indexing on two pages by hand**, to prime the crawl:
   URL Inspection → `https://shouldisellyet.com/zip/20901/` → Request indexing.
   Repeat for `https://shouldisellyet.com/press.html`.

6. **Check back at 48 hours and at 7 days.** Coverage → expect ~5,000
   discovered. What matters is not the total but the **Excluded** reasons: any
   large "Crawled — currently not indexed" bucket is worth a look, and any
   "Submitted URL marked noindex" means the two systems disagree and the
   sitemap is wrong.

## If you need to undo it

Reindexing is the slowest step here to take back, which is why it went last.

- **Stop offering the pages:** flip `PAUSED` in `pipeline/data_pause.py` and
  redeploy. The noindex returns and the sitemap shrinks on the next build.
- **Research only:** `RESEARCH_INDEXABLE = False` in `pipeline/research.py`.
- **In Search Console:** removing a sitemap stops it being re-read but does not
  deindex what was already crawled. Deindexing needs the noindex above, and
  Google re-crawling to see it — days, not minutes.

## One thing worth knowing before you submit

With the research figures dark, the research **hub** is about 200 words. That is
thin for a page competing in search. It is honest content and indexing it does
no harm, but if you would rather not offer it until figures return, set
`RESEARCH_INDEXABLE = False` — the per-ZIP pages, which are the point of this
exercise, are unaffected either way.
