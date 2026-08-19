"""Interim Tier A/B/C ranking — gates, order, and the drift canary.

What can go wrong here costs money rather than crashing: a ZIP that enters
Tier A but has no page to render, a gate silently stopping firing so thin
ZIPs buy paid calls, or an unstable sort that reshuffles the paid tier
between runs and re-buys ZIPs already bought.

Run: python3 -m pytest pipeline/test_rank_interim.py -q
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import rank_interim
from rank_interim import (GATES, assign_tiers, build, gate, has_standing_page,
                          load_acs)

PLACES = {"11111": ("Town", "MD", "County"), "22222": ("Town", "MD", "County"),
          "33333": ("Town", "VA", "County"), "44444": ("Town", "VA", "County")}


def entry(mos=2.0, spy=0.1, dom=10.0, domy=1.0, reasons=(), fhfa=True,
          rdc=True, flagged=False, inv=50, st="MD"):
    e = {"m": {"mos": mos, "spy": spy, "dom": dom, "domy": domy},
         "r": list(reasons), "st": st}
    if fhfa:
        e["f"] = {"y": 2025, "a1": -3.4, "a3": 5.8}
    if rdc:
        e["x"] = {"p": "2026-07", "inv": inv}
        if flagged:
            e["x"]["q"] = 1
    return e


ACS = {"11111": (5000, 3000), "22222": (5000, 2000),
       "33333": (5000, 1000), "44444": (5000, 500)}


# ————— gates —————

def test_survivor_has_no_gate():
    assert gate("11111", entry(), ACS, PLACES) is None


@pytest.mark.parametrize("kwargs,expected", [
    ({"reasons": [("insufficient_data", 0, 1)]}, "no_page"),
    ({"mos": None}, "no_page"),
    ({"domy": None}, "no_page"),
    ({"fhfa": False}, "no_fhfa"),
    ({"rdc": False}, "no_rdc"),
    ({"flagged": True}, "rdc_flagged"),
])
def test_each_gate_fires(kwargs, expected):
    assert gate("11111", entry(**kwargs), ACS, PLACES) == expected


def test_missing_place_is_no_page():
    assert gate("99999", entry(), {"99999": (5000, 1)}, PLACES) == "no_page"


def test_missing_acs_row():
    assert gate("11111", entry(), {}, PLACES) == "no_acs"


def test_floor_is_inclusive_at_the_boundary():
    assert gate("11111", entry(), {"11111": (500, 1)}, PLACES, floor=500) is None
    assert gate("11111", entry(), {"11111": (499, 1)}, PLACES, floor=500) == "below_floor"


def test_gate_attribution_is_first_failure_not_all_failures():
    """A ZIP failing three gates counts once, against the first — otherwise
    the dropped totals overcount and stop summing to the universe."""
    e = entry(fhfa=False, rdc=False)
    assert gate("11111", e, {}, PLACES) == "no_acs"
    rows, dropped = build({"11111": e}, {}, PLACES)
    assert sum(dropped.values()) == 1 and dropped["no_acs"] == 1


def test_every_zip_lands_in_exactly_one_bucket():
    entries = {"11111": entry(), "22222": entry(fhfa=False),
               "33333": entry(flagged=True), "44444": entry(mos=None)}
    rows, dropped = build(entries, ACS, PLACES)
    assert len(rows) + sum(dropped.values()) == len(entries)


# ————— ordering —————

def test_ranked_by_owner_occupied_descending():
    entries = {z: entry() for z in ACS}
    rows, _ = build(entries, ACS, PLACES)
    assert [r["zip"] for r in rows] == ["11111", "22222", "33333", "44444"]


def test_listings_break_owner_ties():
    acs = {"11111": (5000, 1000), "22222": (5000, 1000)}
    entries = {"11111": entry(inv=5), "22222": entry(inv=90)}
    rows, _ = build(entries, acs, PLACES)
    assert [r["zip"] for r in rows] == ["22222", "11111"]


def test_zip_breaks_remaining_ties_so_runs_are_reproducible():
    """An unstable paid tier re-buys ZIPs it already bought."""
    acs = {"11111": (5000, 1000), "22222": (5000, 1000)}
    entries = {"22222": entry(inv=7), "11111": entry(inv=7)}
    first, _ = build(entries, acs, PLACES)
    second, _ = build(dict(reversed(list(entries.items()))), acs, PLACES)
    assert [r["zip"] for r in first] == [r["zip"] for r in second] == ["11111", "22222"]


def test_missing_owner_count_sinks_rather_than_crashes():
    acs = {"11111": (5000, None), "22222": (5000, 10)}
    rows, _ = build({z: entry() for z in acs}, acs, PLACES)
    assert [r["zip"] for r in rows] == ["22222", "11111"]


# ————— tiers —————

def test_tier_boundaries_are_exact():
    rows = [{"zip": f"{i:05d}", "owner": 1000 - i, "listings": 0} for i in range(10)]
    assign_tiers(rows, tier_a=2, tier_b=3)
    assert [r["tier"] for r in rows] == ["A", "A", "B", "B", "B", "C", "C", "C", "C", "C"]
    assert rows[0]["rank"] == 1 and rows[-1]["rank"] == 10


def test_short_eligible_list_does_not_invent_tiers():
    rows = [{"zip": "11111", "owner": 1, "listings": 0}]
    assign_tiers(rows, tier_a=1000, tier_b=4000)
    assert rows[0]["tier"] == "A"


# ————— loaders —————

def test_load_acs_treats_blank_owner_as_unknown(tmp_path):
    p = tmp_path / "acs.csv"
    p.write_text("zip,units,owner\n11111,5000,3000\n22222,900,\n")
    acs = load_acs(p)
    assert acs["11111"] == (5000, 3000) and acs["22222"] == (900, None)


# ————— drift canary —————

def test_eligibility_still_mirrors_build_pages():
    """has_standing_page duplicates build_pages.py's eligible loop, because
    that loop is inline in main() and cannot be called. If the conditions
    there change, this fails and points at the copy that must follow."""
    src = (Path(__file__).parent / "build_pages.py").read_text()
    loop = src[src.index("eligible, skipped = "):src.index("eligible.sort()")]
    assert 'r[0] == "insufficient_data"' in loop
    assert re.search(r'\("mos",\s*"spy",\s*"dom",\s*"domy"\)', loop)
    assert "if z not in places" in loop
    assert loop.count("skipped[") == 3, (
        "build_pages gained or lost an eligibility condition — mirror it in "
        "rank_interim.has_standing_page")


def test_real_data_ranking_is_sane():
    """Against the committed data, not fixtures: the tier that gets bought."""
    from build_pages import load_places as real_places
    entries = rank_interim.load_entries()
    rows, dropped = build(entries, load_acs(), real_places())
    assert len(rows) > 5000, "paid tier cannot be filled with quality ZIPs"
    assert len(rows) + sum(dropped.values()) == len(entries)
    assert all(r["owner"] >= rows[i + 1]["owner"] for i, r in enumerate(rows[:-1]))
    assert len({r["zip"] for r in rows}) == len(rows)
