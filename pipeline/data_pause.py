#!/usr/bin/env python3
"""The Redfin sunset switch — one flag, every surface.

WHY THIS FILE EXISTS. Phase 0 of the Redfin→RentCast migration takes every
Redfin-derived number off the site without deleting a single page or URL. That
touches six generators, the committed homepage, the sitemap, and ~3,400 OG
cards. Scattering that decision across all of them would make Phase 4 —
re-enabling in tranches — an archaeology exercise. So the decision lives here
and everything imports it.

TO RE-ENABLE: set PAUSED = False and deploy. Nothing else. Phase 4's tranches
add a ZIP allowlist to `shows_data()`; until then it is all-or-nothing.

WHAT PAUSING DOES, AND WHY EACH PART IS NECESSARY
  * noindex meta on every affected page. NOT robots.txt — a blocked page is
    never crawled, so the noindex is never read and the URL lingers in the
    index. Crawlable + noindex is the only combination that actually deindexes.
  * Pages keep returning 200. No 404, no 410, no redirect: the URLs keep their
    standing and Phase 4 re-enables them cleanly.
  * The numbers come out of the BODY *and* the metadata. A banner over the
    gauges leaves the verdict in <title>, the meta description, the OG and
    Twitter tags, the JSON-LD, and the pre-rendered OG image — which is what a
    crawler, a social unfurl and a shared link actually read. Half a blanking
    is a blanking that reads as done and is not.
  * Affected URLs leave the sitemap. Generated fresh each deploy, so this is a
    code path, not a file edit.

WHAT PAUSING DOES NOT DO
  * It does not delete data. Retention is an open question for counsel
    (docs/REDFIN-SUNSET.md, question #1); until answered the posture is stop
    displaying, stop computing, retain.
  * It does not stop the site rendering. Every generator still runs and still
    writes every page — because their output is gitignored and rebuilt on each
    deploy, skipping a generator would delete live URLs, which is the one thing
    this migration forbids.
"""

# ————— the switch —————
PAUSED = True

# When ingestion actually stopped, recorded because "when did you stop using
# it" is the first question anyone asks later. Kept here rather than in a doc
# so it cannot drift from the behaviour it describes.
INGESTION_STOPPED_UTC = "2026-08-13T02:00:00Z"
PAUSED_SOURCE = "redfin"

# Reader-facing. Says what is true — the reading is being rebuilt on a new data
# engine — without implying fault, outage, or that the page is broken. It never
# names the outgoing vendor: a banner is not the place to litigate a data
# licence, and naming one would date the copy the moment it changes.
NOTICE_TITLE = "This reading is being refreshed"
NOTICE_BODY = ("We're rebuilding this market reading on a new data engine. "
               "The page will show its rating again shortly — nothing here has "
               "been deleted, and your ZIP will be back with fresh numbers.")

# Neutral <title> and description for paused pages. The old ones carried the
# verdict word and the metrics, which is exactly what must stop being served.
NOTICE_TITLE_TMPL = "{place} housing market — reading being refreshed"
NOTICE_DESC = ("This market reading is being rebuilt on a new data engine and "
               "will return shortly. Free per-ZIP housing readings from public "
               "market data.")


def shows_data(zip_code=None):
    """Whether a surface may display a reading or a market figure.

    Takes a ZIP so Phase 4 can re-enable in tranches by allowlist without
    touching any caller again.
    """
    return not PAUSED


def robots_meta():
    """The one meta tag that deindexes. Empty string when live, so callers can
    interpolate it unconditionally."""
    return ('<meta name="robots" content="noindex,follow">'
            if PAUSED else "")


def notice_html(css_class="pause-notice"):
    """The reader-facing banner. Empty when live."""
    if not PAUSED:
        return ""
    return (f'<div class="{css_class}" role="status">'
            f'<b>{NOTICE_TITLE}.</b> {NOTICE_BODY}</div>')


NOTICE_CSS = """
.pause-notice{margin:0 0 22px;padding:14px 16px;border:1px solid #e7e4dd;
  border-left:3px solid #35527c;border-radius:8px;background:#f3f1ea;
  font-size:.94rem;line-height:1.6;color:#4c4a44}
.pause-notice b{color:#1d1c19}
"""


def title_for(place):
    return NOTICE_TITLE_TMPL.format(place=place)


def guard_fetch(what):
    """Called by anything that would pull from the paused source.

    Raises rather than returning, and names the file to edit. A script that
    silently no-ops is a script somebody re-runs during the migration and
    quietly re-ingests what Phase 0 just stopped.
    """
    if PAUSED:
        raise SystemExit(
            f"REFUSING to fetch {what}: {PAUSED_SOURCE} ingestion was stopped "
            f"at {INGESTION_STOPPED_UTC} (Phase 0 of the data migration).\n"
            f"Nothing here is broken — this guard is the stop.\n"
            f"If you genuinely need to re-ingest, flip PAUSED in "
            f"pipeline/data_pause.py and say why in the commit message.")
