#!/usr/bin/env python3
"""The exposure windows — when each leaked surface stopped leaking.

WHY THIS FILE EXISTS. A capture survey is only evidence if every date in it
can be traced to the record. Three different things stopped on three
different days, and a survey that collapses them into one "we fixed it around
the 20th" window is worse than no survey: it invites the question twice and
answers it wrong once.

So the windows live here, each one carrying the record it came from, and every
row of every output CSV names the window it was measured against.

WINDOW SHAPE: open at the start, closed at the end. There is no defensible
start date — the figures were published from first launch, and the earliest
archived capture IS the evidence of when exposure began, which is one of the
things this survey exists to find out. Inventing a start would throw that
away. So `start_utc` is None everywhere and `contains()` asks one question:
was this capture taken at or before the moment the surface stopped leaking?

Captures AFTER the end are still recorded, with in_window false. They are the
other half of the evidence — they show the fix is live in the archive too.

DATE PRECISION IS NOT UNIFORM, and the CSV says so per row. Two of these
timestamps are exact to the second because a deploy recorded them. Two are
date-only because the record (REMEDIATION_DATES.md) has only a date for them,
and a fabricated time would read as more certain than it is.
"""

from datetime import datetime, timezone

# Context, not a window. Recorded because the first question anyone asks is
# "when did you stop taking their data", and the answer is not the same as
# "when did you stop showing it". Mirrors data_pause.INGESTION_STOPPED_UTC —
# imported rather than retyped would be better, but this tree deliberately
# imports nothing from pipeline/ (see targets.py, THE IMPORT RULE).
INGESTION_STOPPED_UTC = "2026-08-14T13:53:43Z"

# precision: "second" — a deploy stamped it; "day" — the record has a date only
WINDOWS = {
    "consumer_figures": {
        "label": "Withdrawn figures on consumer pages and in their share metadata",
        "start_utc": None,
        "end_utc": "2026-08-20T23:59:59Z",
        "precision": "day",
        "source": ("REMEDIATION_DATES.md — 'Redfin display stopped — actual, "
                   "2026-08-20 … This is the honest date.' The 2026-08-19 "
                   "first pass is NOT the end of this window: two surfaces "
                   "(/report.html, /press.html) were still live on the 20th."),
    },
    "vendor_credits": {
        "label": "Vendor credit line on pages that were already showing no figures",
        "start_utc": None,
        "end_utc": "2026-08-21T23:59:59Z",
        "precision": "day",
        "source": ("The memo's third round. A paused page displays no vendor "
                   "data, so the credit beneath the refresh banner told a "
                   "reader and a crawler that the page rests on data it is "
                   "not showing. Distinct from consumer_figures: a capture "
                   "between the two ends shows the credit and no figures, "
                   "which is a materially different exhibit."),
    },
    "research_zip_file": {
        "label": "Per-ZIP research ratings CSV published under an open reuse grant",
        "start_utc": None,
        "end_utc": "2026-08-21T03:22:25Z",
        "precision": "second",
        "source": ("REMEDIATION_DATES.md — 'Per-ZIP research file withdrawn, "
                   "2026-08-21T03:22:25Z'. 2,135 rows for 2026-06 and 2,403 "
                   "for 2026-07."),
    },
}

# A discrepancy worth stating rather than smoothing over: the credit removal
# ships in commit 29c7d0d, dated 2026-08-20 in git, while the memo places the
# credits round on 21 August. Both are in this file's blast radius and they
# disagree by a day. The window here follows the MEMO, because that is the
# document counsel is working from and a survey that quietly re-dates the memo
# is a survey counsel cannot cite. The wider end is also the conservative one:
# it marks more captures in-window, never fewer. Resolve it against the deploy
# log before the memo is filed, and correct here if the memo moves.
CREDITS_DATE_CONFLICT = (
    "memo says 21 Aug; git commit 29c7d0d is dated 20 Aug — window follows the "
    "memo (wider, conservative). Confirm against the deploy log."
)

_CDX_FMT = "%Y%m%d%H%M%S"


def parse_iso(stamp):
    """'2026-08-21T03:22:25Z' -> aware datetime. Returns None for None."""
    if not stamp:
        return None
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def parse_cdx(stamp):
    """A 14-digit Wayback timestamp -> aware datetime.

    Raises on anything else rather than guessing. A malformed timestamp that
    silently became "now" would land every capture outside every window and
    read as a clean survey, which is the one wrong answer this tool must never
    produce.
    """
    s = str(stamp).strip()
    if len(s) != 14 or not s.isdigit():
        raise ValueError(f"not a 14-digit CDX timestamp: {stamp!r}")
    return datetime.strptime(s, _CDX_FMT).replace(tzinfo=timezone.utc)


def to_iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def contains(window_id, when):
    """Was `when` (aware datetime) inside the exposure window?"""
    w = WINDOWS[window_id]
    end = parse_iso(w["end_utc"])
    start = parse_iso(w["start_utc"])
    if start is not None and when < start:
        return False
    return when <= end


def matched(window_ids, when):
    """Which of `window_ids` this capture falls inside. Order preserved."""
    return tuple(w for w in window_ids if contains(w, when))


def cdx_bound(window_id):
    """The `to=` bound for a CDX query, 14 digits.

    Deliberately NOT applied as a filter in the planned query — see
    sources.WAYBACK_CDX. It is carried so the plan can state the bound a reader
    would otherwise have to compute by hand.
    """
    return parse_iso(WINDOWS[window_id]["end_utc"]).strftime(_CDX_FMT)
