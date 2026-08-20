#!/usr/bin/env python3
"""ShouldISellYet — verdict engine v2, for active-listing data.

WHAT CHANGED AND WHY. v1 (verdict.py) scored five danger signals against
Redfin's largely closed-sale statistics. RentCast /markets statistics are
computed from ACTIVE LISTINGS, and two of those five have no equivalent:

  months of supply   inventory / homes_sold — there is no homes_sold, because
                     active-listing statistics cannot see closings. This was
                     v1's highest-weighted check.
  price-drop share   no equivalent field.

Three survive, and it is not a coincidence which three: every surviving check
was already a YEAR-OVER-YEAR RATIO, and both casualties were LEVELS. A ratio
is robust to the metric shift — active DOM sits higher than sold DOM and a
list-price median sits higher than a sale-price median, but the direction and
magnitude of their year-over-year change remain comparable. A level is not
robust to it at all.

That made the survivors portable in KIND. It did not make their NUMBERS
portable, and the first calibration against real data proved it: at v1's
thresholds dom_stretch fired on 0.8% of ZIPs where the same markets showed
13.2% on the sale basis, and inventory_surge on 0.5% against 3.8%. Stale
inventory anchors an active pool and damps its swings, so both lines were
percentile-matched to the new basis. Only the price lines ported unchanged.

  price falling      median list price YoY   < -2% / -5%
  time to sell       active DOM YoY          > +10%   (see the refit below)
  supply building    total listings YoY      > +30%   (see the refit below)

WHAT WAS TUNED. Four things, not one. The red band moved 4 to 3, because the
two checks that could contribute 4 points are gone and leaving it at 4 would
make ACT nearly unreachable. The Tier B calibration then moved dom_stretch
+40% to +10%, inventory_surge +50% to +30%, and dom_shrink -15% to -20%. Every
surviving check keeps its v1 WEIGHT; two no longer keep its threshold.

A consequence worth stating because the copy got it wrong for a day: with red
at 3, price_falling_fast alone reaches ACT. Under v1 no single check could, so
any sentence promising a reader that "multiple signals" are past the line is
false on a price-only ACT.

The bands were fitted to preserve SEMANTICS, not the national distribution.
Running v1's own logic on the committed data with the two lost signals
removed moves ACT from 28.3% to 22.8% and the seller's-market reading from
4.1% to 3.1% (pipeline/calibrate_v2.py reproduces both figures). Those are
real drops and they are left in place: with two of five danger signals gone
the engine genuinely has less evidence, so calling fewer ACTs is the honest
consequence. Tuning thresholds until the old distribution reappeared would
manufacture confidence the data no longer supports. What the comparison is
FOR is the plan's actual test — "if most of the country flips category, the
thresholds are wrong, not the country" — and a naive port fails it loudly:
unchanged bands collapse ACT to 9.7% and produce zero strong readings.

THRESHOLDS ARE CALIBRATED, not provisional. They were first fitted on
Redfin-sourced proxies, then refitted on 2026-08-19 against 5,000 real Tier
A+B responses — which is when the two volume lines moved. SPEC["provisional"]
is False and a test pins it; changing a threshold again requires re-running
calibrate_v2.py --from-db. See docs/migration/TIER-B-GATE.md.
"""

from dataclasses import dataclass, field
from typing import Optional

SPEC = {
    "version": "reading-methodology-v2",
    "basis": "active listings",
    # Calibrated against real Tier A+B responses, 2026-08-19 (5,000 ZIPs).
    # See docs/migration/TIER-B-GATE.md for the refit that retired this.
    "provisional": False,
    "price_fast": -0.05,      # median list price YoY below this → 3 points.
                              # v1's number, unchanged: list-price YoY fired
                              # within 1pt of sale-price YoY on real data.
    "price_slow": -0.02,      # → 2 points
    # The two volume thresholds are PERCENTILE-MATCHED to the new basis, not
    # ported. Active-listing pools are anchored by stale inventory, so their
    # YoY swings are damped: at v1's +0.40, dom_stretching fired on 0.8% of
    # real ZIPs versus the 13.2% the same markets showed on the sale basis —
    # a functionally dead signal. The refit holds SENSITIVITY constant (the
    # share of markets flagged) instead of the number: matched values were
    # +0.085 and +0.277, rounded to defensible figures below.
    "dom_stretch": 0.10,      # active DOM YoY above this → 1 point
    "inventory_surge": 0.30,  # total listings YoY above this → 1 point
    "red": 3,                 # v1 used 4; the only band that moved
    "yellow": 1,
    # Seller's-market signals. v1 needed 3 of 4; two of those four died with
    # months-of-supply and price-drop share, so this needs ALL THREE of what
    # is left. A "strong" reading renders as ACT — it tells somebody to sell
    # into a hot market — so the conservative error is the right one.
    "price_surge": 0.05,
    "dom_shrink": -0.20,      # tightened: -0.15 OVER-fired on the damped
                              # basis (29.7% vs the intended 19.2%); matched
                              # value -0.202.
    "inventory_drop": -0.15,  # matched almost exactly (-0.144); unchanged.
    "strong_min": 3,
    "min_known": 2,           # below this, no reading is offered at all
}


@dataclass
class MarketV2:
    """Everything the engine scores, plus what it records but does not score.

    Fields are named for what they ARE. list_price_yoy is the year-over-year
    change in the median ASKING price; naming it price_yoy would invite a
    reader to compare it with a v1 sale-price number that means something
    else.
    """
    zip_code: str
    period: str = ""
    list_price_yoy: Optional[float] = None
    active_dom: Optional[float] = None
    active_dom_yoy: Optional[float] = None      # fraction, not days (see below)
    listings_yoy: Optional[float] = None
    # Carried for display and for the next calibration, deliberately unscored:
    # neither has a v1 counterpart to calibrate against, so scoring them now
    # would be inventing a threshold rather than porting one.
    ppsf_yoy: Optional[float] = None
    new_listings_yoy: Optional[float] = None
    total_listings: Optional[float] = None


@dataclass
class VerdictV2:
    zip_code: str
    level: str                  # green | yellow | red | strong
    word: str                   # HOLD | WATCH | ACT
    score: int
    reasons: list = field(default_factory=list)
    basis: str = SPEC["basis"]


LEVELS = {"green": "HOLD", "yellow": "WATCH", "red": "ACT", "strong": "ACT"}


def yoy(now, year_ago):
    """Fractional year-over-year change, or None when it cannot be computed.

    A zero or negative base returns None rather than infinity: a ZIP that had
    no listings a year ago has not grown by an infinite percentage, it has no
    comparison. v1 had to special-case this because Redfin shipped DOM YoY as
    an absolute change in DAYS; RentCast history gives the level for each
    month, so the ratio is computed here and that quirk is gone.
    """
    if now is None or year_ago is None or year_ago <= 0:
        return None
    return (now - year_ago) / year_ago


def _danger(m, s=SPEC):
    out = []
    if m.list_price_yoy is not None:
        if m.list_price_yoy < s["price_fast"]:
            out.append(("price_falling_fast", 3, m.list_price_yoy))
        elif m.list_price_yoy < s["price_slow"]:
            out.append(("price_falling", 2, m.list_price_yoy))
    if m.active_dom_yoy is not None and m.active_dom_yoy > s["dom_stretch"]:
        out.append(("dom_stretching", 1, m.active_dom_yoy))
    if m.listings_yoy is not None and m.listings_yoy > s["inventory_surge"]:
        out.append(("inventory_surge", 1, m.listings_yoy))
    return out


def _strength(m, s=SPEC):
    out = []
    if m.list_price_yoy is not None and m.list_price_yoy >= s["price_surge"]:
        out.append(("prices_surging", 0, m.list_price_yoy))
    if m.active_dom_yoy is not None and m.active_dom_yoy <= s["dom_shrink"]:
        out.append(("homes_selling_fast", 0, m.active_dom_yoy))
    if m.listings_yoy is not None and m.listings_yoy <= s["inventory_drop"]:
        out.append(("inventory_tightening", 0, m.listings_yoy))
    return out


def known_count(m):
    return sum(v is not None for v in
               (m.list_price_yoy, m.active_dom_yoy, m.listings_yoy))


def evaluate(m, s=SPEC):
    """The reading. Same shape as v1's so callers need no branching."""
    known = known_count(m)
    if known < s["min_known"]:
        return VerdictV2(m.zip_code, "green", "HOLD", 0,
                         [("insufficient_data", 0, known)])

    flags = _danger(m, s)
    score = sum(p for _, p, _ in flags)

    # Danger always wins. A seller's-market reading renders only when not one
    # danger line is crossed — same rule as v1, and the reason is the same:
    # "sell now, it's hot" over the top of a falling market is the single
    # worst thing this site could say.
    if not flags:
        strong = _strength(m, s)
        if len(strong) >= s["strong_min"]:
            return VerdictV2(m.zip_code, "strong", LEVELS["strong"], 0, strong)

    level = "red" if score >= s["red"] else ("yellow" if score >= s["yellow"] else "green")
    return VerdictV2(m.zip_code, level, LEVELS[level], score, flags)


def from_market_stats(row, history=None, s=SPEC):
    """A market_stats row (or the runner's parsed dict) → MarketV2.

    `history` is the vendor's month-keyed history block; the twelve months in
    it are what make a year-over-year comparison possible from a single
    request, which is why historyRange is requested at maximum on the first
    call and never bought again.
    """
    hist = history or {}
    months = sorted(hist)
    prior = hist.get(months[-13]) if len(months) >= 13 else (
        hist.get(months[0]) if len(months) >= 12 else None)

    def then(key):
        return (prior or {}).get(key)

    return MarketV2(
        zip_code=row.get("zip") or "",
        period=row.get("as_of_month") or "",
        list_price_yoy=yoy(row.get("list_median_price"), then("medianPrice")),
        active_dom=row.get("active_dom"),
        active_dom_yoy=yoy(row.get("active_dom"), then("averageDaysOnMarket")),
        listings_yoy=yoy(row.get("total_listings"), then("totalListings")),
        ppsf_yoy=yoy(row.get("list_median_ppsf"), then("medianPricePerSquareFoot")),
        new_listings_yoy=yoy(row.get("new_listings"), then("newListings")),
        total_listings=row.get("total_listings"),
    )


def to_compact(v, m):
    """The front end's shape, matching v1's to_compact so the page templates
    do not fork. `b` records the basis on every reading — a page that shows a
    number should be able to say what kind of number it is."""
    return {
        "l": v.level,
        "s": v.score,
        "r": [[c, p, round(val, 4) if isinstance(val, float) else val]
              for c, p, val in v.reasons],
        "b": v.basis,
        "m": {"spy": m.list_price_yoy, "dom": m.active_dom,
              "domy": m.active_dom_yoy, "invy": m.listings_yoy,
              "inv": m.total_listings, "ppsfy": m.ppsf_yoy,
              "nly": m.new_listings_yoy},
    }


# ————— DISCLOSURE —————

def disclosure(spec=SPEC):
    """The danger lines, as a reader is told them.

    Everything that states a threshold to a human derives it from here, so the
    copy cannot drift from the engine. It did: after the Tier B refit moved
    dom_stretch from +40% to +10% and inventory_surge from +50% to +30%, every
    page, the press kit, the research methodology and this module's own
    docstring went on stating the old numbers — telling readers a rule the
    engine no longer applied.

    Client JavaScript cannot import this. It keeps literals, and
    test_threshold_disclosure.py parses them and fails when they disagree —
    the same arrangement test_prices.py already uses for the two pricing
    blocks that cannot import each other either.
    """
    def pct(v):
        s = f"{abs(v) * 100:.0f}%"
        return ("+" if v > 0 else "\u2212") + s
    return {
        "price_slow": pct(spec["price_slow"]),      # −2%
        "price_fast": pct(spec["price_fast"]),      # −5%
        "dom_stretch": pct(spec["dom_stretch"]),    # +10%
        "inventory_surge": pct(spec["inventory_surge"]),  # +30%
        "price_surge": pct(spec["price_surge"]),    # +5%
        "dom_shrink": pct(spec["dom_shrink"]),      # −20%
        "inventory_drop": pct(spec["inventory_drop"]),    # −15%
        "signal_count": 3,
        "signal_names": ("the year-over-year price trend",
                         "how long homes take to sell",
                         "how the pool of homes for sale is changing"),
    }


def methodology_sentence(spec=SPEC):
    """One sentence naming every signal and its line, built from the spec."""
    d = disclosure(spec)
    return (f"Three public signals, each with a danger line recalibrated for "
            f"active-listing data: the year-over-year price trend "
            f"({d['price_slow']}), how long homes take to sell "
            f"({d['dom_stretch']} year over year), and the number of homes for "
            f"sale ({d['inventory_surge']} year over year). A ZIP crossing "
            f"enough of them reads WATCH or ACT; a clean ZIP reads HOLD.")
