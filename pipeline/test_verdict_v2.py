"""Verdict engine v2 — the semantics that had to survive the source change.

v2 exists because two of v1's five danger signals have no active-listing
equivalent. The risk is not that it crashes; it is that it quietly says
something different from what v1 said for the same market, or that a
threshold gets tuned until the old distribution reappears and the engine
claims confidence the data no longer supports.

Run: python3 -m pytest pipeline/test_verdict_v2.py -q
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import verdict as v1
import verdict_v2 as v2
from verdict_v2 import SPEC, MarketV2, evaluate, from_market_stats, yoy


def m(**kw):
    return MarketV2(zip_code=kw.pop("zip_code", "20874"), **kw)


# ————— yoy —————

def test_yoy_is_a_fraction():
    assert yoy(110, 100) == pytest.approx(0.10)
    assert yoy(90, 100) == pytest.approx(-0.10)


def test_yoy_refuses_a_zero_or_negative_base():
    """A ZIP with no listings a year ago has not grown infinitely — it has no
    comparison."""
    assert yoy(50, 0) is None
    assert yoy(50, -1) is None


def test_yoy_needs_both_ends():
    assert yoy(None, 100) is None and yoy(100, None) is None


# ————— the three danger signals —————

def test_price_falling_fast_alone_is_act():
    v = evaluate(m(list_price_yoy=-0.08, listings_yoy=0.0))
    assert v.level == "red" and v.word == "ACT" and v.score == 3
    assert v.reasons[0][0] == "price_falling_fast"


def test_price_falling_slowly_alone_is_watch():
    """v1 scored this 2 and called it WATCH. It still does."""
    v = evaluate(m(list_price_yoy=-0.03, listings_yoy=0.0))
    assert v.level == "yellow" and v.score == 2


def test_two_secondary_signals_are_watch_not_act():
    """DOM stretching plus an inventory surge is 2 points — WATCH under v1's
    bands and WATCH under v2's. Lowering red to 3 must not have promoted it."""
    v = evaluate(m(list_price_yoy=0.0, active_dom=60, active_dom_yoy=0.55,
                   listings_yoy=0.60))
    assert v.score == 2 and v.level == "yellow"


def test_slow_price_fall_plus_one_secondary_reaches_act():
    """3 points. This is the one case v2's lowered red band promotes, and it
    is the intended consequence of losing two signals."""
    v = evaluate(m(list_price_yoy=-0.03, listings_yoy=0.60))
    assert v.score == 3 and v.level == "red"


def test_single_secondary_signal_is_watch():
    v = evaluate(m(list_price_yoy=0.0, listings_yoy=0.60))
    assert v.score == 1 and v.level == "yellow"


def test_healthy_market_is_hold():
    v = evaluate(m(list_price_yoy=0.01, active_dom=30, active_dom_yoy=0.05,
                   listings_yoy=0.05))
    assert v.level == "green" and v.word == "HOLD" and v.score == 0


@pytest.mark.parametrize("field", ["list_price_yoy", "active_dom_yoy", "listings_yoy"])
def test_thresholds_are_exclusive_at_the_boundary(field):
    """A value exactly AT a threshold does not trip it — same as v1."""
    at = {"list_price_yoy": SPEC["price_slow"],
          "active_dom_yoy": SPEC["dom_stretch"],
          "listings_yoy": SPEC["inventory_surge"]}[field]
    kw = {"list_price_yoy": 0.0, "listings_yoy": 0.0,
          "active_dom": 40, "active_dom_yoy": 0.0}
    kw[field] = at
    assert evaluate(m(**kw)).score == 0


# ————— the strong path —————

def test_strong_requires_all_three_surviving_signals():
    """v1 needed 3 of 4. Two of those four died, so this needs 3 of 3 — a
    strong reading renders as ACT, telling somebody to sell into a hot
    market, so the conservative error is the right one."""
    all_three = dict(list_price_yoy=0.09, active_dom=20, active_dom_yoy=-0.25,
                     listings_yoy=-0.30)
    assert evaluate(m(**all_three)).level == "strong"
    two_of_three = dict(all_three, listings_yoy=0.0)
    assert evaluate(m(**two_of_three)).level == "green"


def test_a_danger_flag_always_beats_a_strong_reading():
    """'Sell now, it's hot' over a falling market is the worst thing this
    site could say."""
    v = evaluate(m(list_price_yoy=0.09, active_dom=20, active_dom_yoy=-0.25,
                   listings_yoy=0.60))          # surging AND flooding
    assert v.level != "strong" and v.score == 1


def test_strong_renders_as_act():
    v = evaluate(m(list_price_yoy=0.09, active_dom=20, active_dom_yoy=-0.25,
                   listings_yoy=-0.30))
    assert v.word == "ACT"


# ————— insufficient data —————

def test_one_known_signal_is_not_a_reading():
    v = evaluate(m(list_price_yoy=-0.30))
    assert v.reasons == [("insufficient_data", 0, 1)]
    assert v.level == "green" and v.score == 0


def test_two_known_signals_is_enough():
    assert evaluate(m(list_price_yoy=-0.08, listings_yoy=0.0)).score == 3


def test_nothing_known_is_not_a_reading():
    assert evaluate(m()).reasons[0][0] == "insufficient_data"


# ————— the lost signals must stay lost —————

def test_engine_has_no_months_of_supply_or_price_drop_input():
    """RentCast cannot produce either. A field for them would invite a
    caller to pass a value from somewhere else and quietly re-import the
    metric mismatch this whole migration exists to remove."""
    fields = set(MarketV2.__dataclass_fields__)
    assert not any("supply" in f or "drop" in f or "sold" in f for f in fields)


def test_v1_still_scores_five_signals():
    """v2 does not replace v1 in this repo yet — Phase 4 does that. If v1
    changes underneath, the calibration baseline moves and this fails."""
    src = (Path(__file__).parent / "verdict.py").read_text()
    for check in ("supply_severe", "price_cuts_widespread", "dom_stretching",
                  "inventory_surge", "price_falling_fast"):
        assert check in src


# ————— provenance —————

def test_every_reading_records_its_basis():
    """A page that shows a number should be able to say what kind of number
    it is. Active-listing medians are not closed-sale medians."""
    v = evaluate(m(list_price_yoy=-0.08, listings_yoy=0.0))
    assert v.basis == "active listings"
    assert v2.to_compact(v, m(list_price_yoy=-0.08))["b"] == "active listings"


def test_spec_was_calibrated_before_the_flag_was_retired():
    """provisional was retired 2026-08-19 after a --from-db calibration on
    5,000 real Tier A+B responses (docs/migration/TIER-B-GATE.md). The two
    volume thresholds are percentile-matched to the active-listing basis;
    changing any threshold again requires re-running that calibration."""
    assert SPEC["provisional"] is False
    assert SPEC["dom_stretch"] == 0.10 and SPEC["inventory_surge"] == 0.30
    assert SPEC["dom_shrink"] == -0.20 and SPEC["inventory_drop"] == -0.15


# ————— building from stored payloads —————

PAYLOAD_HISTORY = {f"2025-{month:02d}": {} for month in range(8, 13)}
PAYLOAD_HISTORY.update({f"2026-{month:02d}": {} for month in range(1, 9)})


def test_from_market_stats_computes_yoy_off_the_history_block():
    hist = dict.fromkeys(PAYLOAD_HISTORY, {})
    months = sorted(hist)
    hist[months[-13]] = {"medianPrice": 500000, "averageDaysOnMarket": 30,
                         "totalListings": 100}
    row = {"zip": "20874", "as_of_month": "2026-08",
           "list_median_price": 450000, "active_dom": 45, "total_listings": 160}
    mk = from_market_stats(row, hist)
    assert mk.list_price_yoy == pytest.approx(-0.10)
    assert mk.active_dom_yoy == pytest.approx(0.50)
    assert mk.listings_yoy == pytest.approx(0.60)
    assert evaluate(mk).level == "red"        # -10% price (3) + dom (1) + inv (1)


def test_from_market_stats_survives_a_history_too_short_to_compare():
    row = {"zip": "20874", "list_median_price": 450000}
    mk = from_market_stats(row, {"2026-08": {}})
    assert mk.list_price_yoy is None
    assert evaluate(mk).reasons[0][0] == "insufficient_data"


def test_from_market_stats_survives_no_history_at_all():
    mk = from_market_stats({"zip": "20874", "list_median_price": 1}, None)
    assert mk.list_price_yoy is None
