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
                        rendered OG image, or the live per-ZIP endpoint's JSON
                        — while every page keeps its reading word, its
                        headline, its danger-line disclosure and its
                        methodology.

WHAT THIS SWITCH REACHES, STATED PRECISELY. This paragraph is the one that gets
quoted back at us, so it says what is true and no more.

Reached: every surface the builders render (the static ZIP pages, the share
stubs, the OG cards), the two client renderers, AND — since 2026-08-24 —
supabase/functions/market-reading/index.ts, the live per-ZIP endpoint, which
until then served spy / dom / domy / inv / invy as named columns to any browser
while the static pages beside it had already stopped drawing them. That
endpoint cannot import this module: it mirrors FIGURES_OFF in its own literal
and pipeline/test_figures_switch_endpoint.py fails when the two disagree.

WHAT THIS SWITCH STILL DOES NOT REACH. Said here rather than discovered during
an incident; re-verified 2026-08-24:

  * web/my-report.html computes `val / (1 + m.spy)` and prints a dollar figure
    from a record it assembles itself, and declares no switch of its own. Its
    dials DO go empty when the endpoint withholds, because that page builds
    its record out of the endpoint's response and the `m.spy != null` guards
    then fall through — but that is a CONSEQUENCE of an upstream change, not a
    control this module holds, and a page that got its record from anywhere
    else would print the figure. Both report pages also ship hardcoded
    DEMO/SAMPLE records carrying metric blocks, on a path no flag here can
    reach. (web/report.html was being wired to market-render.js's copy while
    this was written — read that file rather than trusting this sentence.)
  * anything already served. A response the CDN cached before the flip keeps
    its figures for up to max-age plus the stale window, and a page already
    open in a browser keeps drawing what it downloaded. Flipping this switch is
    an edit, a rebuild, a deploy of the edge function, and a cache purge — in
    that order, and the purge is the step that gets forgotten.

So the honest claim is "every surface we render or serve, once the flip has
shipped to all of them" — not "any surface", and not "instantly".

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

FOUR COPIES MUST AGREE. The same figures are emitted by four places, and
neither client JavaScript nor Deno can import a Python module, so the other
three keep a literal `FIGURES_OFF`:

  pipeline/figures_switch.py    this file — the builders (ZIP pages, stubs,
                                OG cards)
  web/index.html                the homepage checker
  web/market-render.js          both report surfaces
  supabase/functions/market-reading/index.ts
                                the live per-ZIP endpoint

test_figures_switch.py pins the first three to each other and
test_figures_switch_endpoint.py pins the fourth to this file — the arrangement
test_threshold_disclosure.py already uses for the thresholds, for the same
reason: four copies of a decision is fine, four copies that can DIVERGE is not.
Flipping the switch means editing all four; the tests are what make that one
flag instead of four.

THE FOURTH COPY IS NOT LIKE THE OTHER THREE. Three of them take effect on the
next build. The endpoint's takes effect only when the FUNCTION is deployed,
which is a separate action on a separate schedule — and that asymmetry is
exactly how the gap opened: a build-time literal cannot reach a running server,
so the pages went quiet and the endpoint kept answering. If you flip three and
ship a build, the endpoint is still serving figures.

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

Run: python3 -m pytest pipeline/test_figures_switch.py \
                       pipeline/test_figures_switch_endpoint.py -q
"""

# ————— the switch —————
#
# A literal, not an environment read: this is data_pause's pattern rather than
# realtor_crosscheck's, because the client copies below cannot read an
# environment either. A flag whose three copies are set three different ways
# is a flag that will be flipped in two of them.
FIGURES_OFF = False

# The identifier the three non-Python copies declare — the two client files
# and the edge function. Named here so the sync tests look for one string
# rather than three hand-typed ones.
JS_CONST = "FIGURES_OFF"

# Reader-facing, for a surface that would otherwise render a value. Vendor-
# neutral for the same reason data_pause's notice is: a page that has stopped
# showing a source is not the place to name it.
#
# market-reading/index.ts returns this verbatim as the withheld response's
# `notice`, and test_figures_switch_endpoint.py compares the two — a
# reassuring sentence that has drifted into two wordings is a sentence nobody
# can quote to counsel.
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
