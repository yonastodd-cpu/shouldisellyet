#!/usr/bin/env python3
"""The Realtor.com kill switch.

Realtor.com research figures — days on market, active inventory, price-cut
share — are under licence review. This module is the single place that decides
whether any of them may leave the private side, so that turning them off is a
variable change rather than an edit spread across six files.

  SHOW_REALTOR_CROSSCHECK=0   nothing Realtor-derived is fetched, written into
                              web/, or credited to a reader.
  unset / anything else       current behaviour, unchanged.

WHY A SWITCH AND NOT A DELETION. The licence answer is not in yet. If it comes
back unfavourable the remedy has to be immediate, and if it comes back fine
nothing should have been thrown away in the meantime.

WHAT "OFF" HAS TO MEAN. Not hidden — absent. The cross-check block used to ship
inside every public per-ZIP record, so a reader who opened the network tab had
the figures whether or not the strip was drawn. OFF therefore gates the
PRODUCER (fetch_data attaches nothing) and the WRITER (provisioning strips
anything that reaches it anyway), not the renderer.

ON A STATIC SITE THIS STILL NEEDS A DEPLOY. Everything here is baked at build
time; there is no server to re-read the variable. Flipping it is a CI variable
change plus a rebuild — no code edit, no review, but not instant. Said plainly
because "config change rather than a deploy" is what the task asked for and
this architecture cannot quite give it.

THE TRAP THIS MODULE EXISTS TO AVOID. `entry["x"]` had two consumers, not one:
web/market-render.js drew it, and pipeline/rank_interim.py GATED on it — two of
its six eligibility gates were pure Realtor.com (`no_rdc`, `rdc_flagged`) and
`x["inv"]` supplied the ranking tiebreak. A switch that stripped `x` to stop
displaying it would therefore have quietly emptied the paid-tier ranking, which
targets metered RentCast calls. That ranking is now frozen and its inputs are
withdrawn (see rank_interim.load_entries), so nothing reads `x` for ordering
any more — but a future consumer must not be added without re-reading this.

Run: python3 -m pytest pipeline/test_realtor_crosscheck.py -q
"""

import os

_TRUTHY_OFF = {"0", "false", "off", "no", ""}

# Module attribute, not a bare read at each call site: tests monkeypatch this
# the way they monkeypatch data_pause.PAUSED, and callers ask the predicates
# below rather than branching on the boolean themselves.
SHOW = os.environ.get("SHOW_REALTOR_CROSSCHECK", "1").strip().lower() not in _TRUTHY_OFF

# Vendor-neutral on purpose: a page that has switched the cross-check off
# should not name the vendor it is no longer showing, which is the same rule
# data_pause applies to the paused market-data credit.
OFF_LINE = "Independent cross-check temporarily unavailable."

# The record key the cross-check block ships under.
FIELD = "x"


def shows_crosscheck():
    """May Realtor-derived figures be fetched, written, or displayed?"""
    return SHOW


def strip(record):
    """A public per-ZIP record with the cross-check removed when off.

    Applied at the point data leaves the private side. provision_readings
    builds each record as {**reading, "st": state} — every key of the reading
    copied through unfiltered — so a cross-check block that reached it would
    ship without anyone deciding to publish it.
    """
    if SHOW or not isinstance(record, dict) or FIELD not in record:
        return record
    return {k: v for k, v in record.items() if k != FIELD}


def credit(text):
    """Attribution text with the Realtor.com clause removed when off."""
    if SHOW or not text:
        return text
    out = text
    for clause in (" · Listing data from Realtor.com&reg; Economic Research",
                   " · Listing data from Realtor.com® Economic Research",
                   "Listing data from Realtor.com&reg; Economic Research · ",
                   "Listing data from Realtor.com® Economic Research · "):
        out = out.replace(clause, "")
    return out
