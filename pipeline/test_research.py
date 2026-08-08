"""Synthetic-fixture tests for the Warning-Sign Index machinery.

The records logic is the part of the research product that writes headlines
("highest since March 2022"), so it is the part that must be provably right:
a superlative the archive contradicts is how an index loses the only thing
it sells. Every fixture here is hand-computable.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from research import (advance_streaks, counts_of, detect_records,
                      region_share, wsi_of)


# ————— WSI arithmetic —————

def test_wsi_definition_excludes_strong_from_numerator_only():
    c = {"green": 40, "yellow": 30, "red": 20, "strong": 10}
    # (30+20) / 100 — strong is in the denominator, never the numerator.
    assert wsi_of(c) == 50.0
    assert region_share(c) == 50.0


def test_wsi_empty_is_none():
    assert wsi_of({"green": 0, "yellow": 0, "red": 0, "strong": 0}) is None


def test_counts_ignores_unknown_levels():
    c = counts_of({"a": "green", "b": "yellow", "c": "purple"})
    assert c == {"green": 1, "yellow": 1, "red": 0, "strong": 0}


# ————— records: the headline machinery —————

def _series(vals, start_year=2020):
    months = []
    y, m = start_year, 1
    for _ in vals:
        months.append(f"{y}-{m:02d}")
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return list(zip(months, vals))


def test_highest_since_names_the_last_month_at_or_above():
    # 14, 12, 11, 13 → current 13; last month ≥ 13 is the 14 in month 0.
    rec = detect_records(_series([14.0, 12.0, 11.0, 13.0]))
    assert rec["highest_since"] == "2020-01"
    assert rec["wsi"] == 13.0
    assert rec["delta"] == 2.0


def test_record_high_when_nothing_prior_reaches_it():
    rec = detect_records(_series([10.0, 12.0, 11.0, 11.5, 13.0]))
    assert rec["highest_since"] == "record"


def test_tie_counts_as_reached_not_exceeded():
    # A month equal to the current value blocks the "record" claim — an index
    # must never say "highest ever" about a value the archive has seen.
    rec = detect_records(_series([13.0, 11.0, 13.0]))
    assert rec["highest_since"] == "2020-01"


def test_lowest_since_mirrors():
    rec = detect_records(_series([9.0, 12.0, 11.0, 8.0]))
    assert rec["lowest_since"] == "record"
    rec = detect_records(_series([7.0, 12.0, 11.0, 8.0]))
    assert rec["lowest_since"] == "2020-01"


def test_run_length_counts_consecutive_same_direction_moves():
    # 10 → 11 → 12 → 13: three consecutive rises ending now.
    rec = detect_records(_series([10.0, 11.0, 12.0, 13.0]))
    assert rec["run_length"] == 3 and rec["run_direction"] == "up"
    # A flat month ends the run.
    rec = detect_records(_series([10.0, 12.0, 12.0, 13.0]))
    assert rec["run_length"] == 1
    # A reversal ends it too.
    rec = detect_records(_series([13.0, 12.0, 11.0, 12.0]))
    assert rec["run_length"] == 1 and rec["run_direction"] == "up"


def test_single_month_series_survives():
    rec = detect_records(_series([12.4]))
    assert rec["wsi"] == 12.4
    assert rec["highest_since"] == "record"
    assert "delta" not in rec


# ————— streaks —————

def test_streaks_accumulate_only_in_warning_and_reset_on_exit():
    s = advance_streaks({}, {"20874": "yellow", "20906": "green"})
    assert s == {"20874": 1}
    s = advance_streaks(s, {"20874": "red", "20906": "yellow"})
    assert s == {"20874": 2, "20906": 1}       # yellow→red keeps the streak
    s = advance_streaks(s, {"20874": "green", "20906": "yellow"})
    assert s == {"20906": 2}                    # recovery drops the ZIP
    s = advance_streaks(s, {"20874": "yellow", "20906": "yellow"})
    assert s == {"20874": 1, "20906": 3}        # re-entry starts at 1


def test_streaks_drop_zips_that_vanish_from_scoring():
    s = advance_streaks({"11111": 5}, {"22222": "red"})
    assert s == {"22222": 1}                    # unscored month breaks a streak


# ————— segment discipline: records never reach across the source seam —————

def test_continuous_segment_excludes_pre_seam_months():
    from research import national_series
    h = {"seam": "2019-06", "months": ["2019-04", "2019-05", "2019-06", "2019-07"],
         "national": {"2019-04": [10, 80, 10, 0],   # 90% — a pre-seam spike
                      "2019-05": [10, 80, 10, 0],
                      "2019-06": [80, 10, 10, 0],   # 20%
                      "2019-07": [70, 15, 15, 0]}}  # 30%
    seg = national_series(h, segment="continuous")
    assert [m for m, _ in seg] == ["2019-06", "2019-07"]
    # On the segment, 30% is a record high — the 90% months before the seam
    # must not block the claim, because they are a different universe…
    rec = detect_records(seg)
    assert rec["highest_since"] == "record"
    # …and the full series (chart context) still carries all four months.
    assert len(national_series(h)) == 4
