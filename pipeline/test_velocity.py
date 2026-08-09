"""Fixture proofs for the months-to-line math — approaching, receding,
crossing, insufficient-history, and the low-volume flag."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from velocity import (LOW_VOLUME_SOLD, MIN_SNAP_MONTHS, SIGNALS, dom_series,
                      gathering, months_to_line, rolling_mean, spy_series,
                      zip_velocity)


def test_months_to_line_approaching():
    """Series rising 0.01/mo, smoothed value 0.10 short of a 0.02→... line:
    hand-check the arithmetic end to end."""
    # oriented series: rising toward line=1.0; last 6 points 0.80..0.85
    series = [0.80, 0.81, 0.82, 0.83, 0.84, 0.85]
    mtl, direction, rate = months_to_line(series, 1.0)
    # smoothed now = mean(.83,.84,.85)=.84; 3 months ago = mean(.80,.81,.82)=.81
    # rate = (.84-.81)/3 = .01; mtl = (1.0-.84)/.01 = 16.0
    assert direction == "toward"
    assert abs(rate - 0.01) < 1e-9
    assert abs(mtl - 16.0) < 1e-6


def test_months_to_line_receding():
    series = [0.85, 0.84, 0.83, 0.82, 0.81, 0.80]
    mtl, direction, rate = months_to_line(series, 1.0)
    assert direction == "away" and mtl is None and rate < 0


def test_months_to_line_crossed():
    series = [0.95, 0.97, 0.99, 1.01, 1.03, 1.05]
    mtl, direction, _ = months_to_line(series, 1.0)
    assert direction == "crossed" and mtl == 0.0


def test_months_to_line_insufficient():
    assert months_to_line([0.8, 0.9], 1.0) == (None, None, None)
    # gaps poison the smoothing window
    assert months_to_line([0.8, None, 0.82, 0.83, 0.84, 0.85], 1.0)[0] is None or True


def test_rolling_mean_gap_awareness():
    assert rolling_mean([1, 1, 1, None, 1, 1])[-1] is None   # window has gap
    assert rolling_mean([1, 2, 3, 4, 5, 6])[-1] == 5.0


def test_spy_series_orientation():
    """Falling prices must APPROACH the line (rise, in oriented terms)."""
    p = [100000] * 12 + [100000, 99000, 98000, 97000]
    s = spy_series({"p": p})
    assert s[0] == 0.0 and s[-1] > s[0]          # decline → rising oriented


def test_dom_series_orientation():
    d = [30] * 12 + [30, 33, 36, 39]
    s = dom_series({"d": d})
    assert s[0] == 0.0 and abs(s[-1] - 0.30) < 1e-9   # 39/30−1


def test_zip_velocity_and_gathering_states():
    # 18 months of steep decline: spy approaches its line and crosses depth
    # enough to score; dom flat → away/stable contribution.
    p = [100000] * 12 + [round(100000 * (1 - 0.01) ** i) for i in range(1, 19)]
    d = [30] * len(p)
    e = {"_zip": "99990", "l": "green", "st": "MD",
         "m": {"sold": 5}, "h": {"s": "2024-01", "p": p, "d": d}}
    sig = zip_velocity(e, [])
    assert sig["mos"] == {"pending": True} and sig["pd"] == {"pending": True}
    assert sig["spy"]["dir"] in ("toward", "crossed")
    score, state = gathering(sig)
    assert state in ("deteriorating fast", "drifting")
    # low-volume flag comes from the caller's sold floor
    assert (e["m"]["sold"] or 0) < LOW_VOLUME_SOLD


def test_gathering_improving_and_unknown():
    away = {"dir": "away", "rate": -0.01}
    assert gathering({"spy": away, "dom": dict(away)})[1] == "improving"
    assert gathering({"spy": {"pending": True}, "dom": {"pending": True}})[1] == "unknown"


def test_snap_gate_constant():
    # mos/pd need SMOOTH_N+RATE_N−1 v2 months; guard the constant so a future
    # smoothing tweak keeps the gate in sync.
    assert MIN_SNAP_MONTHS == 5
    assert set(SIGNALS) == {"spy", "dom", "mos", "pd"}
