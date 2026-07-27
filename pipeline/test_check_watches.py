"""Unit tests for the personal-number watch engine. Run: pytest -q"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from check_watches import (compute_metric, is_crossed, latest_price, pmt,
                            process_subscriber, scale_value)


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


# ——— process_subscriber (multi-watch array orchestration) ———

def _make_data_dir(tmp_path, zip_code, state, price_history):
    (tmp_path / "zips").mkdir(exist_ok=True)
    (tmp_path / "index.json").write_text(json.dumps({zip_code[:3]: state}))
    (tmp_path / "zips" / f"{state}.json").write_text(json.dumps({
        zip_code: {"h": {"p": price_history}}
    }))
    (tmp_path / "meta.json").write_text(json.dumps({"national": {}}))
    return str(tmp_path)


def test_process_subscriber_no_watches_is_noop():
    sub = {"watches": [], "calc_inputs": {}, "zip": "20906"}
    updated, emails = process_subscriber(sub, "/nonexistent", 6.58)
    assert updated == [] and emails == []


def test_process_subscriber_fires_once_and_latches(tmp_path):
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [400000] * 12)
    sub = {
        "email": "a@example.com", "zip": "20906", "access_token": "tok",
        "calc_inputs": {"value": 400000, "bal": 250000},  # equity = 150000
        "watches": [{"metric": "equity", "direction": "below", "threshold": 200000, "crossed": False}],
    }
    updated, emails = process_subscriber(sub, data_dir, 6.58)
    assert len(emails) == 1 and "equity" in emails[0][0].lower()
    assert updated[0]["crossed"] is True

    # second run with the same (still-crossed) data must NOT re-email
    sub["watches"] = updated
    updated2, emails2 = process_subscriber(sub, data_dir, 6.58)
    assert emails2 == []
    assert updated2[0]["crossed"] is True


def test_process_subscriber_rearms_after_uncrossing(tmp_path):
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [400000] * 12)
    sub = {
        "email": "a@example.com", "zip": "20906", "access_token": "tok",
        "calc_inputs": {"value": 400000, "bal": 100000},  # equity = 300000, not below 200000
        "watches": [{"metric": "equity", "direction": "below", "threshold": 200000, "crossed": True}],
    }
    updated, emails = process_subscriber(sub, data_dir, 6.58)
    assert emails == []
    assert updated[0]["crossed"] is False  # rearmed, silently


def test_process_subscriber_evaluates_each_watch_independently(tmp_path):
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [400000] * 12)
    sub = {
        "email": "a@example.com", "zip": "20906", "access_token": "tok",
        "calc_inputs": {"value": 400000, "bal": 250000, "rate": 3.75},  # equity=150000, no lockin trip
        "watches": [
            {"metric": "equity", "direction": "below", "threshold": 200000, "crossed": False},  # crosses
            {"metric": "lockin", "direction": "below", "threshold": 0, "crossed": False},        # does not
        ],
    }
    updated, emails = process_subscriber(sub, data_dir, 6.58)
    assert len(emails) == 1
    by_metric = {w["metric"]: w for w in updated}
    assert by_metric["equity"]["crossed"] is True
    assert by_metric["lockin"]["crossed"] is False


def test_process_subscriber_skips_uncomputable_watch_without_erroring(tmp_path):
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [400000] * 12)
    sub = {
        "email": "a@example.com", "zip": "20906", "access_token": "tok",
        "calc_inputs": {"value": 400000, "bal": 250000},  # no rate → lockin uncomputable
        "watches": [{"metric": "lockin", "direction": "below", "threshold": 100, "crossed": False}],
    }
    updated, emails = process_subscriber(sub, data_dir, 6.58)
    assert emails == []
    assert updated == sub["watches"]  # left untouched, not crashed
