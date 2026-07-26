"""Unit tests for the personal-number watch engine. Run: pytest -q"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_watches import (compute_metric, is_crossed, latest_price, pmt,
                            scale_value)


# ——— pmt / scale_value ———

def test_pmt_matches_known_amortization():
    # $268,000 at 3.75%/30yr — a standard, checkable P&I figure.
    assert round(pmt(268000, 3.75)) == 1241


def test_pmt_zero_rate_is_straight_division():
    assert pmt(360000, 0, 30) == 1000.0


def test_pmt_zero_principal_is_zero():
    assert pmt(0, 5.0) == 0.0


def test_scale_value_scales_proportionally():
    # value was $400k when median was $350k; median rose 10% since
    assert round(scale_value(400000, 350000, 385000)) == 440000


def test_scale_value_falls_back_when_median_missing():
    assert scale_value(400000, None, 385000) == 400000
    assert scale_value(400000, 350000, None) == 400000


def test_latest_price_skips_trailing_nulls():
    entry = {"h": {"p": [300000, 310000, None, None]}}
    assert latest_price(entry) == 310000


def test_latest_price_none_when_no_history():
    assert latest_price({}) is None
    assert latest_price({"h": {"p": []}}) is None


# ——— compute_metric ———

def test_equity_is_value_minus_balance():
    inputs = {"value": 400000, "bal": 250000}
    assert compute_metric("equity", inputs, None, 6.5) == 150000


def test_walkaway_applies_cost_pct_default_8():
    inputs = {"value": 400000, "bal": 250000}
    # 400000*0.92 - 250000 = 118000
    assert round(compute_metric("walkaway", inputs, None, 6.5)) == 118000


def test_walkaway_respects_custom_cost_pct():
    inputs = {"value": 400000, "bal": 250000, "costPct": 6}
    assert round(compute_metric("walkaway", inputs, None, 6.5)) == 126000


def test_lockin_positive_when_market_rate_higher():
    inputs = {"value": 400000, "bal": 268000, "rate": 3.75}
    v = compute_metric("lockin", inputs, None, 6.58)
    assert v is not None and v > 0  # today's rate costs more than their locked-in rate


def test_lockin_none_without_rate():
    inputs = {"value": 400000, "bal": 268000}
    assert compute_metric("lockin", inputs, None, 6.58) is None


def test_lockin_none_without_positive_balance():
    inputs = {"value": 400000, "bal": 0, "rate": 3.75}
    assert compute_metric("lockin", inputs, None, 6.58) is None


def test_metric_uses_scaled_value_when_median_history_given():
    inputs = {"value": 400000, "baselineMedian": 350000, "bal": 250000}
    # value scales to 440000 (see test_scale_value_scales_proportionally)
    assert round(compute_metric("equity", inputs, 385000, 6.5)) == 190000


def test_unknown_metric_returns_none():
    assert compute_metric("bogus", {"value": 1, "bal": 0}, None, 6.5) is None


# ——— is_crossed ———

def test_below_direction():
    assert is_crossed(90000, "below", 100000) is True
    assert is_crossed(110000, "below", 100000) is False


def test_above_direction():
    assert is_crossed(110000, "above", 100000) is True
    assert is_crossed(90000, "above", 100000) is False


def test_crossed_is_none_when_value_uncomputable():
    assert is_crossed(None, "below", 100000) is None
