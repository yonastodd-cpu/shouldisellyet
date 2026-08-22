#!/usr/bin/env python3
"""The Realtor.com kill switch.

Realtor.com research figures — days on market, active inventory, price-cut
share — are under licence review. This module is the single place that decides
whether any of them may leave the private side, so that turning them off is a
variable change rather than an edit spread across six files.

  SHOW_REALTOR_CROSSCHECK unset / 0   nothing Realtor-derived is fetched,
                                      written into web/, or credited to a
                                      reader. THIS IS NOW THE DEFAULT.
  SHOW_REALTOR_CROSSCHECK=1           the pre-2026-08-22 behaviour, restored
                                      in full.

WHY THE DEFAULT CHANGED, AND WHEN. On 2026-08-22 the default flipped from ON
to OFF. Display had been dormant for a while; INGESTION had not — the monthly
Realtor.com pull kept running, and the governing terms for that feed have
still not been obtained. Ingesting a vendor's file every month while unable to
say what the terms permit is the part that had to stop, and the honest way to
stop it is at the fetch, not at the renderer.

THIS IS A PAUSE, NOT A DEPRECATION. Nothing is deleted, no code path is
removed, and every call site still asks this module rather than assuming an
answer. The switch reads exactly as it always did; only the default moved.

HOW TO RESUME, once the terms are cleared:
  1. Set SHOW_REALTOR_CROSSCHECK=1 in the CI variables and rebuild. That
     restores fetching, writing and crediting in one move — there is no second
     flag to find, which is the whole reason this module exists.
  2. Backfill the months the pause skipped. Realtor.com publishes its Core
     Metrics files as dated monthly archives, so a missed month is retrievable
     later at the same URL shape; nothing about a pause is permanent. Run
     fetch_data.py once per missed month against the archived file.
A pause therefore costs a backfill, not a hole.

WHY A SWITCH AND NOT A DELETION. The licence answer is not in yet. If it comes
back unfavourable the remedy has to be immediate, and if it comes back fine
nothing should have been thrown away in the meantime.

WHAT "OFF" HAS TO MEAN. Not hidden — absent. The cross-check block used to ship
inside every public per-ZIP record, so a reader who opened the network tab had
the figures whether or not the strip was drawn. OFF therefore gates the
PRODUCER (fetch_data attaches nothing) and the WRITER (provisioning strips
anything that reaches it anyway), not the renderer.

WHY THE SKIP IS LOGGED. A gate that stops a fetch and prints nothing looks
exactly like a job that lost its step, and six months later nobody can tell a
deliberate pause from a silent breakage. log_skip() puts a dated, reasoned line
in the run output so the record shows a decision. That is the same instinct as
data_pause.guard_fetch raising instead of no-opping — say the stop out loud.

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

AND DO NOT ADD A SECOND SWITCH. Verified again on 2026-08-22: this flag already
gates the fetch (fetch_data.py), the write (provision_readings.py) and both
credits (build_pages.py, build_research.py). A second overlapping variable is
how this codebase has previously ended up with two maps that disagree about
what is live. If a new surface needs gating, it imports this module.

Run: python3 -m pytest pipeline/test_realtor_crosscheck.py -q
"""

import os
import sys

_TRUTHY_OFF = {"0", "false", "off", "no", ""}

# Module attribute, not a bare read at each call site: tests monkeypatch this
# the way they monkeypatch data_pause.PAUSED, and callers ask the predicates
# below rather than branching on the boolean themselves.
# DEFAULT "0" SINCE 2026-08-22 — see "WHY THE DEFAULT CHANGED" above. The
# string is deliberately still an env default rather than a hardcoded False so
# that resuming is a CI variable change and not a code edit.
SHOW = os.environ.get("SHOW_REALTOR_CROSSCHECK", "0").strip().lower() not in _TRUTHY_OFF

# The date the default flipped, and why, kept next to the flag rather than in a
# doc so the two cannot drift. data_pause records its stop the same way, for
# the same reason: "when did you stop, and on whose say-so" is the first thing
# anyone asks afterwards.
PAUSED_UTC = "2026-08-22"
PAUSE_REASON = ("the governing terms for the Realtor.com research feed have "
                "not been obtained and are under review")

# Vendor-neutral on purpose: a page that has switched the cross-check off
# should not name the vendor it is no longer showing, which is the same rule
# data_pause applies to the paused market-data credit.
OFF_LINE = "Independent cross-check temporarily unavailable."

# The record key the cross-check block ships under.
FIELD = "x"


def shows_crosscheck():
    """May Realtor-derived figures be fetched, written, or displayed?"""
    return SHOW


def skip_notice(what="the Realtor.com monthly ingest"):
    """The one-line explanation a skipped fetch owes the log.

    Single line by construction: GitHub Actions annotations terminate at the
    first newline, so a multi-line message would publish its first clause and
    silently drop the reason — which is the only part worth reading.
    """
    return (f"SKIPPED {what}: SHOW_REALTOR_CROSSCHECK is off, the default "
            f"since {PAUSED_UTC}, because {PAUSE_REASON}. Deliberate pause, "
            f"not a failed fetch and not a deprecation — set "
            f"SHOW_REALTOR_CROSSCHECK=1 to resume (missed months backfill "
            f"from Realtor.com's dated monthly archives).")


def log_skip(what="the Realtor.com monthly ingest", stream=None):
    """Announce the skip where an operator reading the run will see it.

    Under Actions this is emitted as a ::notice::, which surfaces on the run
    summary rather than only inside a collapsed step log — a pause nobody
    scrolls to is a pause nobody knows about. Elsewhere it is a plain print so
    a local run reads the same sentence. Returns the line for the tests.
    """
    line = skip_notice(what)
    if os.environ.get("GITHUB_ACTIONS"):
        line = f"::notice title=Realtor.com ingest paused::{line}"
    print(line, file=stream or sys.stdout, flush=True)
    return line


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
