"""
ShouldISellYet — verdict engine.

Takes per-ZIP market metrics and returns a traffic-light warning level
with machine-readable reasons. Pure logic, no I/O — fully unit-testable.

Thresholds are based on well-documented leading indicators:
  - Months of supply > 4       → sellers lose pricing power
  - Median sale price YoY < 0  → decline already underway
  - Price-drop share > 35%     → widespread seller capitulation
  - Days on market up > 40% YoY→ demand cracking
  - Inventory up > 50% YoY     → supply wave building
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ZipMetrics:
    zip_code: str
    state: str = ""
    period: str = ""                       # e.g. "2026-06"
    months_of_supply: Optional[float] = None
    median_sale_price_yoy: Optional[float] = None   # fraction, e.g. -0.03
    price_drop_share: Optional[float] = None        # fraction of listings w/ cuts
    median_dom: Optional[float] = None              # days
    median_dom_yoy: Optional[float] = None          # fraction change
    inventory_yoy: Optional[float] = None           # fraction change


@dataclass
class Verdict:
    zip_code: str
    level: str                 # "green" | "yellow" | "red"
    word: str                  # "HOLD" | "WATCH" | "ACT"
    score: int
    reasons: list = field(default_factory=list)   # list of (code, severity, value)


# (metric check, points, reason code)
def _checks(m: ZipMetrics):
    out = []
    if m.months_of_supply is not None:
        if m.months_of_supply > 6:
            out.append(("supply_severe", 3, m.months_of_supply))
        elif m.months_of_supply > 4:
            out.append(("supply_high", 2, m.months_of_supply))
    if m.median_sale_price_yoy is not None:
        if m.median_sale_price_yoy < -0.05:
            out.append(("price_falling_fast", 3, m.median_sale_price_yoy))
        elif m.median_sale_price_yoy < -0.02:
            out.append(("price_falling", 2, m.median_sale_price_yoy))
    if m.price_drop_share is not None and m.price_drop_share > 0.35:
        out.append(("price_cuts_widespread", 1, m.price_drop_share))
    # Redfin's MEDIAN_DOM_YOY is an absolute change in DAYS, not a fraction.
    # Flag when time-to-sell grew >40% vs. last year (needs current DOM to compute).
    if m.median_dom_yoy is not None and m.median_dom is not None:
        prior_dom = m.median_dom - m.median_dom_yoy
        if prior_dom > 0 and (m.median_dom_yoy / prior_dom) > 0.40:
            out.append(("dom_stretching", 1, m.median_dom_yoy))
    if m.inventory_yoy is not None and m.inventory_yoy > 0.50:
        out.append(("inventory_surge", 1, m.inventory_yoy))
    return out


LEVELS = {"green": "HOLD", "yellow": "WATCH", "red": "ACT"}


def evaluate(m: ZipMetrics) -> Verdict:
    flags = _checks(m)
    score = sum(p for _, p, _ in flags)

    if score >= 4:
        level = "red"
    elif score >= 2:
        level = "yellow"
    else:
        level = "green"

    # Not enough data to say anything → stay green but flag low confidence
    known = sum(
        v is not None
        for v in (m.months_of_supply, m.median_sale_price_yoy,
                  m.price_drop_share, m.median_dom_yoy, m.inventory_yoy)
    )
    if known < 2:
        return Verdict(m.zip_code, "green", "HOLD", 0,
                       [("insufficient_data", 0, known)])

    return Verdict(m.zip_code, level, LEVELS[level], score, flags)


def to_compact(v: Verdict, m: ZipMetrics) -> dict:
    """Compact JSON representation the front end consumes."""
    return {
        "l": v.level,
        "s": v.score,
        "r": [[c, round(val, 3) if isinstance(val, float) else val]
              for c, _, val in v.reasons],
        "m": {
            k: (round(x, 3) if isinstance(x, float) else x)
            for k, x in {
                "mos": m.months_of_supply,
                "spy": m.median_sale_price_yoy,
                "pd": m.price_drop_share,
                "dom": m.median_dom,
                "domy": m.median_dom_yoy,
                "invy": m.inventory_yoy,
            }.items() if x is not None
        },
        "st": m.state,
    }
