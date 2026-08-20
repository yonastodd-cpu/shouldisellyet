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

import json
from pathlib import Path

# ————— the switch —————
PAUSED = True

# When ingestion actually stopped, recorded because "when did you stop using
# it" is the first question anyone asks later. Kept here rather than in a doc
# so it cannot drift from the behaviour it describes.
# CORRECTED. The first value here was the moment the decision was made, which
# was wrong: a scheduled refresh completed at 2026-08-13T14:27:12Z — AFTER that
# timestamp and BEFORE this gate reached main — and committed a full 2026-07
# Redfin snapshot (commit 5d79b43). Ingestion actually stopped when the gate
# landed, and this records that instead. A stop time that flatters the record
# is worse than none: it is the one field somebody will rely on later.
INGESTION_STOPPED_UTC = "2026-08-14T13:53:43Z"
LAST_INGESTED_PERIOD = "2026-07"   # committed by 5d79b43, before the gate
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


# ————— Phase 4: the tranche allowlist —————
#
# Phase 0 was all-or-nothing. Phase 4 releases ZIPs in tranches, and the unit
# of release is this file: pipeline/tranches.json, one entry per tranche with
# the ZIPs it covers and when it went out. Absent or empty means nothing is
# released, which is the safe default — a missing file pauses everything
# rather than publishing everything.
#
# THE TRAP THIS AVOIDS. An allowlist that only asks "is this ZIP released?"
# would republish the numbers Phase 0 withdrew, because the entries in
# web/data/zips are still Redfin-derived. Releasing a ZIP is therefore TWO
# conditions: it is in a released tranche, AND the reading being rendered
# carries the new basis. A ZIP promoted before its v2 data lands stays dark
# instead of quietly resurrecting the old vendor's figures.
TRANCHES = Path(__file__).parent / "tranches.json"

# The only basis that may publish while PAUSED. Matches verdict_v2.SPEC and
# the `b` field its to_compact() writes onto every reading.
RELEASED_BASIS = "active listings"

# Legacy readings carry no basis at all, which is exactly how they are
# recognised: absence is the marker.
LEGACY_BASIS = ""

_allowlist = None


def released_zips(path=None):
    """The union of every released tranche. Cached; pass a path to reload."""
    global _allowlist
    if _allowlist is not None and path is None:
        return _allowlist
    out = set()
    try:
        data = json.loads(Path(path or TRANCHES).read_text())
        for t in data.get("tranches", []):
            if t.get("released_utc"):
                out.update(str(z) for z in t.get("zips", []))
    except (OSError, ValueError):
        out = set()          # unreadable == nothing released, never everything
    if path is None:
        _allowlist = out
    return out


def shows_data(zip_code=None, basis=None):
    """Whether a surface may display a reading or a market figure.

    While paused, a ZIP shows data only if it is in a released tranche AND
    the reading offered carries RELEASED_BASIS. Callers that pass no basis
    get the allowlist check alone — fine for surfaces deciding layout, but
    anything rendering an actual number should pass it, because that second
    condition is the whole guard against republishing withdrawn data.
    """
    if not PAUSED:
        return True
    if zip_code is None or zip_code not in released_zips():
        return False
    return basis is None or basis == RELEASED_BASIS


def wrongly_promoted(zip_code, basis):
    """True for a ZIP that is released but whose reading is still legacy.

    Not an error state to crash on — a build must not take the site down —
    but it is a release that did not happen, and build_pages counts and
    reports these rather than letting them pass as ordinary paused pages.
    """
    return (PAUSED and zip_code in released_zips()
            and basis != RELEASED_BASIS)


def indexable(zip_code=None, thin=False, basis=None):
    """Whether a page may be indexed.

    Released is necessary but not sufficient: a ZIP whose reading says it has
    too little data to read gets a page and an honest state, but should not
    compete in search for a rating it does not have.

    NEITHER IS THE TRANCHE FILE SUFFICIENT ON ITS OWN. This used to ask only
    whether the ZIP was released, while the BODY asked shows_data(zip, basis)
    — the tranche file AND the record actually carrying a v2 reading. The two
    can disagree, and on 2026-08-20 they did: the store was unreachable from
    CI, provisioning fell back to notice-only for every ZIP, and the 1,000
    released pages shipped with "this reading is being refreshed" in the body
    and no noindex in the head. A thousand pages offered to crawlers with
    nothing on them — worse than paused, because paused at least told the
    truth in both places.

    So indexability now takes the same two arguments the body does. The rule
    is one rule: a page may be indexed when it may show its reading.
    """
    if thin:
        return False
    if not PAUSED:
        return True
    return shows_data(zip_code, basis)


def robots_meta(zip_code=None, thin=False, basis=None):
    """The one meta tag that deindexes. Empty when the page may be indexed.

    Per-ZIP now: a released ZIP whose record carries a v2 reading drops the
    noindex, everything else keeps it. Callers passing nothing keep the global
    behaviour, which is correct for the metro, story and research pages — none
    of which are released per-ZIP.
    """
    return "" if indexable(zip_code, thin, basis) else '<meta name="robots" content="noindex,follow">'


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
