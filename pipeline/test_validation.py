"""Fixture proofs for the forward-validation metrics."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from validation import (DECLINE_MAJOR, DECLINE_PRECISION, lead_times,
                        month_shift, price_change, score)


def _h(mult_12mo):
    """36-month price series ending at 100k * mult (12-mo change = mult−1)."""
    p = [100000] * 25 + [None] * 0
    p += [round(100000 * (1 + (mult_12mo - 1) * (i / 11))) for i in range(1, 12)]
    # index -13 = 100000, index -1 = 100000*mult
    return {"p": p[:24] + [100000] + p[25:] , "d": [30] * 36}


def test_price_change_arithmetic():
    h = {"p": [100000] * 24 + [100000] + [95000] * 11, "d": []}
    assert abs(price_change(h, 12) - (-0.05)) < 1e-9
    assert price_change({"p": [None] * 5}, 12) is None


def test_score_recall_precision_false_quiet():
    # Four ZIPs: A declined 6% and was flagged (caught); B declined 6% while
    # green (false quiet); C flagged but flat (precision miss); D green flat.
    snap = {"A": "yellow", "B": "green", "C": ["red", 4.1, -0.03, 40, 0.4, 50], "D": "green"}
    flat = {"p": [100000] * 37, "d": []}
    down = {"p": [100000] * 25 + [94000] * 12, "d": []}
    entries = {"A": {"h": down}, "B": {"h": down}, "C": {"h": flat}, "D": {"h": flat}}
    v = score(snap, entries, 12)
    assert v["zips_scored"] == 4 and v["declined"] == 2
    assert v["recall"] == 0.5            # caught A, missed B
    assert v["false_quiet"] == 1         # B
    assert v["flagged"] == 2 and v["precision"] == 0.5   # A right, C flat
    # v2 snapshot rows read identically to v1 strings (C was a v2 row)


def test_thresholds_are_the_published_ones():
    assert DECLINE_MAJOR == -0.05 and DECLINE_PRECISION == -0.02


def test_lead_times_needs_history_and_computes():
    months = [f"2026-{m:02d}" for m in range(1, 8)]     # 7 consecutive
    # ZIP flagged in month index 2; y/y first negative at index 4 → 2 months ≈ 60d
    snaps = {}
    for i, mn in enumerate(months):
        snaps[mn] = {"Z": "yellow" if i >= 2 else "green"}
    p = [100000] * 29 + [100000, 100000, 100000, 100000, 99000, 98000, 97000]
    entries = {"Z": {"h": {"p": p, "d": []}}}
    lead = lead_times(snaps, entries)
    assert lead == 60
    # under the gate → None, never a guess
    assert lead_times({m: snaps[m] for m in months[:5]}, entries) is None


def test_month_shift():
    assert month_shift("2026-06", 12) == "2025-06"
    assert month_shift("2026-02", 6) == "2025-08"
    assert month_shift("2026-05", -12) == "2027-05"
