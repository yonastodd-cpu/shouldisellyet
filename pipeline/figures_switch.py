#!/usr/bin/env python3
"""FIGURES_KILL_SWITCH — withhold the vendor's numbers, keep our own word.

WHY THIS FILE EXISTS. The reading (HOLD / WATCH / ACT) and the figures it is
computed from are two different things with two different owners. The word is
ours: a level produced by verdict_v2 from thresholds we published. The figures
— asking-price change, days on market, listing counts, the twelve-month
history behind every chart — are the vendor's market statistics, restated.

We told counsel that separation exists and that we could act on it alone. It
did not exist as a switch: it existed as an argument about which lines of six
files somebody would edit under time pressure. This module is that claim made
real, and one flag is the whole point — an architecture that would PERMIT the
separation is not the same as a separation you can turn on and verify.

  FIGURES_OFF = False   current behaviour, unchanged. The default, so nothing
                        moves until somebody moves it.
  FIGURES_OFF = True    no RentCast-derived market figure is published on the
                        surfaces listed below — body, dial, chart, <title>,
                        meta description, OG/Twitter tags, JSON-LD, share stub,
                        or rendered OG image — while every page keeps its
                        reading word, its headline, its danger-line disclosure
                        and its methodology.

WHAT THIS SWITCH DOES NOT YET REACH. Said here rather than discovered during an
incident, and verified 2026-08-22 — all three carry figures the switch cannot
suppress:

  * web/report.html and web/my-report.html compute `val / (1 + m.spy)` and
    print a dollar figure. Neither file references this switch.
  * supabase/functions/market-reading/index.ts serves spy / inv / invy / dom as
    named columns from a live endpoint. A build-time literal cannot reach a
    running server; suppressing that needs a deploy of the function itself.

So the honest claim is "every static surface the builders render", not "any
surface". Wiring the two report pages is the next piece of work; the endpoint
is a separate decision because it is the paid product's data path.

WHAT COUNTS AS A FIGURE. A number MEASURED BY the vendor about a market, or
arithmetic on one: everything in a record's `m` block, the `h` history series,
and anything derived from either (the national price percentile, the
"fastest month" for listings, the OG card's stat line, the velocity phrase).

WHAT IS NOT A FIGURE, and deliberately survives:
  * the reading word and its headline — our calculation, our copy;
  * the published danger lines ("line: +30% y/y") — disclosure of OUR rule,
    stated identically on every page whatever its data says. test_pause_leaks
    already draws this distinction and it is the right one;
  * the as-of month. A date is not a market statistic, and a page that shows
    a reading has to be able to say which month it read;
  * counts of our own ZIP pages and readings (hubs, llms.txt);
  * the Warning-Sign Index and the recomputed case studies. Different lineage
    (Redfin, express republication licence) and a different question — if
    those must stop, that is a different switch;
  * the Realtor.com cross-check, which realtor_crosscheck.py already owns.

THE THREE RENDERERS MUST AGREE. The same dials are drawn by
pipeline/build_pages.py (static ZIP pages), web/index.html (the homepage
checker) and web/market-render.js (both report surfaces). Client JavaScript
cannot import this module, so those two keep a literal `FIGURES_OFF` and
test_figures_switch.py fails when any of the three disagrees — the arrangement
test_threshold_disclosure.py already uses for the thresholds, for the same
reason: three copies of a decision is fine, three copies that can DIVERGE is
not. Flipping the switch means editing all three; the test is what makes that
one flag instead of three.

ON A STATIC SITE THIS IS A DEPLOY, NOT A TOGGLE. Every ZIP page is baked at
build time and there is no server to re-read anything, so flipping this is an
edit plus a rebuild — same honesty realtor_crosscheck.py states about itself.
The client literals matter anyway: the homepage renders from a record fetched
at runtime, so a page already in someone's browser is drawing dials this file
alone cannot reach.

WHAT THIS IS NOT. It is not a pause and it is not a deletion. data_pause.py
withdraws the whole reading for un-released ZIPs; this withdraws the figures
from readings that are otherwise fine. Nothing stored is removed — see
LEGAL_HOLD.md. A page keeps its URL, its 200, and its indexability: a reading
with no figures is still a page with something true on it, which is exactly
why the noindex logic is data_pause's and not this module's.

Run: python3 -m pytest pipeline/test_figures_switch.py -q
"""

# ————— the switch —————
#
# A literal, not an environment read: this is data_pause's pattern rather than
# realtor_crosscheck's, because the client copies below cannot read an
# environment either. A flag whose three copies are set three different ways
# is a flag that will be flipped in two of them.
FIGURES_OFF = False

# The identifier the two client files declare. Named here so the sync test
# looks for one string rather than two hand-typed ones.
JS_CONST = "FIGURES_OFF"

# Reader-facing, for a surface that would otherwise render a value. Vendor-
# neutral for the same reason data_pause's notice is: a page that has stopped
# showing a source is not the place to name it.
WITHHELD_LINE = "Market figures are not being shown for this reading."


def shows_figures():
    """May a vendor-derived market figure be rendered anywhere?

    Deliberately takes no arguments. data_pause.shows_data() is per-ZIP
    because releases are per-ZIP; this is a licence posture and applies to
    every ZIP at once. A per-ZIP variant would be a different decision and
    should be a different function, not an optional argument on this one.
    """
    return not FIGURES_OFF


def metrics(m):
    """A record's `m` block, or {} when figures are off.

    THE POINT OF RETURNING {} rather than raising or returning None: every
    renderer here already handles a record with no metrics, because ~17,874
    ZIPs have exactly that and have had since provisioning began. Routing the
    metrics through one function means the withheld case takes a code path
    that is exercised on every build instead of a new branch that is exercised
    the day somebody flips the switch.
    """
    if FIGURES_OFF:
        return {}
    return m or {}


def history(h):
    """A record's `h` series, or None when figures are off.

    Charts are the figure people forget. A sparkline carries no digits and
    still publishes twelve monthly values — shape is data. Same for the
    derived "listings move fastest in March": no numeral, entirely computed
    from the vendor's series.
    """
    return None if FIGURES_OFF else h


def strip(record):
    """A record with its figures removed, for anything that SHIPS a record.

    The renderers above take their figures through metrics()/history(); this
    is for the other kind of leak — a whole record copied to the client, where
    the numbers are in the network tab whether or not anything drew them. That
    is precisely how the Realtor.com cross-check shipped inside every public
    per-ZIP file while the strip was only ever hidden (see
    realtor_crosscheck.strip, same shape, same reason).

    Reason CODES stay; reason VALUES go. "inventory_surge" is the name of a
    rule we publish. 0.5909 is the vendor's measurement of this market.
    """
    if not FIGURES_OFF or not isinstance(record, dict):
        return record
    out = {k: v for k, v in record.items() if k not in ("m", "h")}
    if isinstance(out.get("r"), list):
        out["r"] = [r[:2] if isinstance(r, (list, tuple)) and len(r) > 2 else r
                    for r in out["r"]]
    return out
