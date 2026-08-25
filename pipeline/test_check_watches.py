"""Unit tests for the personal-number watch engine. Run: pytest -q"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from check_watches import (CrossBasisError, baseline_basis, compute_metric,
                            is_crossed, latest_price, pmt, process_subscriber,
                            scale_value)

LEGACY = ""                  # data_pause.LEGACY_BASIS — absence is the marker
CURRENT = "active listings"  # data_pause.RELEASED_BASIS


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


# ——— basis: the ratio that must not be formed ———

def test_scale_value_refuses_to_scale_across_bases():
    # The C11 defect: a closed-sale denominator under an asking-price
    # numerator. It must not produce a number at all.
    with pytest.raises(CrossBasisError):
        scale_value(400000, 350000, 500000, LEGACY, CURRENT)


def test_scale_value_refuses_a_baseline_of_any_other_basis():
    # The refusal is on inequality, not on one hardcoded pair — a future
    # third basis is caught by the same line.
    with pytest.raises(CrossBasisError):
        scale_value(400000, 350000, 500000, "sold pairs", CURRENT)


def test_scale_value_still_scales_within_one_basis():
    assert round(scale_value(400000, 350000, 385000, CURRENT, CURRENT)) == 440000
    assert round(scale_value(400000, 350000, 385000, LEGACY, LEGACY)) == 440000


def test_scale_value_without_a_median_has_no_basis_question():
    # No ratio is formed, so nothing crosses bases: the subscriber's own
    # saved figure comes back untouched rather than raising.
    assert scale_value(400000, None, 500000, LEGACY, CURRENT) == 400000
    assert scale_value(400000, 350000, None, LEGACY, CURRENT) == 400000


def test_compute_metric_refuses_a_cross_basis_dollar_metric():
    inputs = {"value": 400000, "baselineMedian": 350000, "bal": 250000}
    with pytest.raises(CrossBasisError):
        compute_metric("equity", inputs, 500000, 6.5,
                       baseline_basis=LEGACY, current_basis=CURRENT)


def test_baseline_basis_ignores_the_reading_basis_key():
    # This is the C11 defect in one assertion: the 2026-08-14 arm rewrote
    # `basis` to the new reading while carrying the old baseline median
    # through untouched. A watch that says basis=CURRENT therefore still has
    # a LEGACY baseline, and reading `basis` as the baseline's basis is what
    # let the cross-basis ratio run.
    assert baseline_basis({"basis": CURRENT}) == LEGACY
    assert baseline_basis({"basis": CURRENT, "baselineBasis": CURRENT}) == CURRENT


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

def _make_data_dir(tmp_path, zip_code, state, price_history, basis=None):
    """`basis=None` writes a legacy entry — no `b` key at all, which is
    exactly how the legacy basis is recognised (data_pause.LEGACY_BASIS)."""
    (tmp_path / "zips").mkdir(exist_ok=True)
    (tmp_path / "index.json").write_text(json.dumps({zip_code[:3]: state}))
    entry = {"h": {"p": price_history}}
    if basis is not None:
        entry["b"] = basis
    (tmp_path / "zips" / f"{state}.json").write_text(json.dumps({zip_code: entry}))
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
    # Lock-in carries no median, so it also picks up no basis bookkeeping.
    assert "baselineBasis" not in updated[0]


# ——— the rebaseline flow (C11) ———

def _legacy_sub(watches, inputs):
    """A subscriber whose watches have already been through the 2026-08-14
    migration arm: `basis` rewritten to the reading of the day, baseline
    median carried through from the old one, no `baselineBasis` anywhere."""
    return {"email": "a@example.com", "zip": "20906", "access_token": "tok",
            "calc_inputs": inputs, "watches": watches}


def test_rebaseline_notifies_and_never_emits_the_cross_basis_number(tmp_path):
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [500000] * 12, basis=CURRENT)
    sub = _legacy_sub(
        [{"metric": "equity", "direction": "above", "threshold": 200000,
          "crossed": False, "basis": LEGACY}],
        {"value": 400000, "baselineMedian": 350000, "bal": 250000},
    )
    updated, emails = process_subscriber(sub, data_dir, 6.58)

    # Told, in plain language, and told once.
    assert len(emails) == 1
    subject, html = emails[0]
    assert "recalculated on a new data source" in subject
    assert "new data source" in html
    # The prior vendor is never named to a reader.
    assert "redfin" not in (subject + html).lower()

    # Re-based, not scaled: the baseline median is now today's, on the
    # recorded current basis, and the value is the subscriber's own saved
    # figure — not 400000 * (500000/350000).
    w = updated[0]
    assert w["baselineBasis"] == CURRENT
    assert w["baselineMedian"] == 500000
    assert w["baselineValue"] == 400000
    assert "$321,428" not in html          # the cross-basis equity
    assert "$150,000" in html              # 400000 - 250000, unscaled


def test_rebaseline_relatches_so_the_next_run_is_quiet(tmp_path):
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [500000] * 12, basis=CURRENT)
    sub = _legacy_sub(
        [{"metric": "equity", "direction": "below", "threshold": 200000,
          "crossed": False, "basis": LEGACY}],
        {"value": 400000, "baselineMedian": 350000, "bal": 250000},
    )
    updated, emails = process_subscriber(sub, data_dir, 6.58)
    assert len(emails) == 1
    assert updated[0]["crossed"] is True   # 150000 < 200000, latched on the re-based figure

    sub["watches"] = updated
    updated2, emails2 = process_subscriber(sub, data_dir, 6.58)
    assert emails2 == []                   # rebaselining is a one-time event
    assert updated2 == updated             # and idempotent


def test_rebaselined_watch_scales_normally_on_the_new_basis(tmp_path):
    """After re-basing, ordinary same-basis scaling resumes by itself — the
    fix must not leave the watch permanently frozen."""
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [500000] * 12, basis=CURRENT)
    sub = _legacy_sub(
        [{"metric": "equity", "direction": "above", "threshold": 1_000_000,
          "crossed": False, "basis": LEGACY}],
        {"value": 400000, "baselineMedian": 350000, "bal": 250000},
    )
    updated, _ = process_subscriber(sub, data_dir, 6.58)

    # Same basis, median up 10%: value 400000 → 440000, equity 190000.
    (tmp_path / "later").mkdir()
    moved = _make_data_dir(tmp_path / "later", "20906", "MD", [550000] * 12, basis=CURRENT)
    sub["watches"] = updated
    updated2, emails2 = process_subscriber(sub, moved, 6.58)
    assert emails2 == []                   # 190000 is still short of the threshold
    assert updated2[0]["baselineMedian"] == 500000   # untouched by a same-basis run
    assert round(compute_metric("equity", {"value": 400000, "baselineMedian": 500000,
                                           "bal": 250000}, 550000, 6.58,
                                CURRENT, CURRENT)) == 190000


def test_rebaseline_is_silent_when_nothing_was_being_scaled(tmp_path):
    """The paused world: no published price history, so the old baseline was
    scaling nothing. Recording the basis moves no number the subscriber has
    seen, so it must not mail every legacy watch on the book."""
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [None] * 12, basis=CURRENT)
    sub = _legacy_sub(
        [{"metric": "equity", "direction": "below", "threshold": 200000,
          "crossed": False, "basis": LEGACY}],
        {"value": 400000, "baselineMedian": 350000, "bal": 250000},
    )
    updated, emails = process_subscriber(sub, data_dir, 6.58)
    assert emails == []
    assert updated[0]["baselineBasis"] == CURRENT
    assert "baselineMedian" not in updated[0]      # nothing re-anchored, nothing invented


def test_legacy_watch_on_a_legacy_reading_is_left_alone(tmp_path):
    """Nothing changes today: while the reading is still the legacy one, a
    legacy baseline matches it and no notice goes out."""
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [385000] * 12)
    sub = _legacy_sub(
        [{"metric": "equity", "direction": "above", "threshold": 1_000_000,
          "crossed": False, "basis": LEGACY}],
        {"value": 400000, "baselineMedian": 350000, "bal": 250000},
    )
    updated, emails = process_subscriber(sub, data_dir, 6.58)
    assert emails == []
    # Stamped as legacy — which is what it truthfully is — and left unscaled
    # in every other respect.
    assert updated[0]["baselineBasis"] == LEGACY
    assert "baselineValue" not in updated[0]


def test_an_unstamped_watch_is_rebaselined_rather_than_adopted(tmp_path):
    """An unstamped watch must REBASELINE, never adopt the current basis.

    This asserted the opposite until 2026-08-25, on the premise that a watch
    with no basis key "came out of the same published data". The premise is
    false: `basis` is written in only two places, both on a basis CHANGE, and
    no tranche had been released — so no watch has ever carried it.
    save-watch/index.ts writes {metric, direction, threshold, crossed} and
    nothing else, which makes absence the state of the ENTIRE live book rather
    than the signature of a fresh save.

    Adopting the current basis stamped closed-sale baselines as asking-price
    ones, let scale_value through, and would have mailed the cross-basis figure
    to the whole book on the first run after a release — a $350,000 equity
    crossing where the honest figure was $200,000. HEAD emitted nothing."""
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [385000] * 12, basis=CURRENT)
    sub = {"email": "a@example.com", "zip": "20906", "access_token": "tok",
           "calc_inputs": {"value": 400000, "baselineMedian": 350000, "bal": 250000},
           "watches": [{"metric": "equity", "direction": "above",
                        "threshold": 1_000_000, "crossed": False}]}
    updated, emails = process_subscriber(sub, data_dir, 6.58)
    # After rebaselining, the stamp SHOULD read the current basis — that is
    # what re-anchoring means. What must never happen is a silent adoption
    # that lets scale_value form a ratio across two different measurements.
    # So assert the user was told, and that the figure is the honest one.
    assert emails, "a rebaseline must notify; silent re-basing is the defect"
    subject = emails[0][0] if isinstance(emails[0], tuple) else emails[0]
    assert "recalculated" in subject.lower(), subject
    body = emails[0][1] if isinstance(emails[0], tuple) else ""
    assert "$150,000" in body, "the honest unscaled value must be the one shown"
    assert "$350,000" not in body, "the cross-basis figure reached the email"


def test_velocity_watch_still_rebaselines_silently_on_a_basis_flip(tmp_path):
    """Velocity compares a state word, not a median — no ratio, nothing to
    refuse — so its original migration behaviour is unchanged."""
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [500000] * 12, basis=CURRENT)
    sub = {"email": "a@example.com", "zip": "20906", "access_token": "tok",
           "calc_inputs": {}, "_vel_state": "drifting",
           "watches": [{"metric": "velocity", "direction": "escalates", "threshold": 0,
                        "crossed": False, "baseline": "stable", "basis": LEGACY}]}
    updated, emails = process_subscriber(sub, data_dir, 6.58)
    assert emails == []                       # no escalation email across a basis flip
    assert updated[0]["baseline"] == "drifting"
    assert updated[0]["basis"] == CURRENT
    assert "baselineBasis" not in updated[0]  # meaningless for a state watch


def test_median_free_metrics_get_no_basis_notice(tmp_path):
    """rate / rategap / lockin are computed without a ZIP median, so a basis
    change does not change how they are computed and must not mail anyone a
    notice saying it did."""
    data_dir = _make_data_dir(tmp_path, "20906", "MD", [500000] * 12, basis=CURRENT)
    sub = _legacy_sub(
        [{"metric": "rate", "direction": "below", "threshold": 3.0,
          "crossed": False, "basis": LEGACY},
         {"metric": "lockin", "direction": "above", "threshold": 10_000,
          "crossed": False, "basis": LEGACY}],
        {"value": 400000, "baselineMedian": 350000, "bal": 268000, "rate": 3.75},
    )
    updated, emails = process_subscriber(sub, data_dir, 6.58)
    assert emails == []                                    # neither crosses, neither is re-based
    assert all("baselineBasis" not in w for w in updated)


def test_lockin_never_raises_over_a_median_it_does_not_use():
    """Lock-in reads the saved balance and rate only. It must be computable
    across a basis change, not blocked by a scale it never performed."""
    inputs = {"value": 400000, "baselineMedian": 350000, "bal": 268000, "rate": 3.75}
    v = compute_metric("lockin", inputs, 500000, 6.58,
                       baseline_basis=LEGACY, current_basis=CURRENT)
    assert v is not None and v > 0
