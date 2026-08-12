"""The metro page agrees with itself, and the research page agrees with its own seam.

Both failures these cover shipped to production and were visible on the page:
a hero that contradicted the table underneath it, and a streak claim that
reached sixteen months across a seam the same page discloses.

Run: python3 -m pytest pipeline/test_metro_and_research.py -q
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))

import build_metro as bm
import build_research as br

METRO_DIR = REPO / "web" / "metro"
RESEARCH = REPO / "web" / "research"
REPORT = json.loads((REPO / "pipeline" / "research" / "research-2026-06.json").read_text())


def _pages(limit=150):
    return sorted(METRO_DIR.glob("*/index.html"))[:limit]


@pytest.mark.skipif(not METRO_DIR.exists(), reason="metro pages not built")
def test_the_metro_hero_agrees_with_the_table_beneath_it():
    """It used to read pipeline/research/history.json — the research INDEX,
    four signals over its own scored set — while the table listed the site's
    five-signal verdicts. Across 915 metros the two disagreed by 13.4 points on
    average and by more than 2 points in 722 of them. Grand Rapids shipped
    "30% rate WATCH or ACT" above a table with 28 of 76 rows so tagged.

    The hero is now counted from those rows, so this is checkable by counting
    the page — which is the entire point."""
    bad = []
    for f in _pages():
        h = f.read_text()
        hero = re.search(r'<div class="mhero">(\d+)%</div>', h)
        cap = re.search(r'<div class="mcap">of the (\d+) ZIP codes', h)
        tags = re.findall(r'<span class="tag [^"]*">(WATCH|ACT|HOLD|STRONG|—)</span>', h)
        if not hero or not tags:
            continue
        counted = round(100 * sum(1 for t in tags if t in ("WATCH", "ACT")) / len(tags))
        if int(hero.group(1)) != counted or (cap and int(cap.group(1)) != len(tags)):
            bad.append((f.parent.name, hero.group(1), counted, len(tags)))
    assert not bad, f"hero disagrees with its own table on {len(bad)} page(s): {bad[:3]}"


@pytest.mark.skipif(not METRO_DIR.exists(), reason="metro pages not built")
def test_holds_plus_warning_equals_scored():
    """The note under the table and the hero must describe one arithmetic."""
    for f in _pages(60):
        h = f.read_text()
        line = re.search(r'(\d+) of (\d+) rate HOLD or better', h)
        tags = re.findall(r'<span class="tag [^"]*">(WATCH|ACT|HOLD|STRONG|—)</span>', h)
        if not line or not tags:
            continue
        holds, scored = int(line.group(1)), int(line.group(2))
        assert holds + sum(1 for t in tags if t in ("WATCH", "ACT")) == scored, f.parent.name


@pytest.mark.skipif(not METRO_DIR.exists(), reason="metro pages not built")
def test_identical_printed_values_are_never_two_different_colours():
    """Red means "past its published danger line". 0.354 and 0.349 both print
    "35%", and comparing the raw float drew one red and one black in the same
    table, under a note telling the reader what red means."""
    from collections import defaultdict
    seen = defaultdict(set)
    for f in _pages(200):
        for row in re.findall(r"<tr>.*?</tr>", f.read_text(), re.S):
            for i, (past, val) in enumerate(re.findall(r'<td class="num( past)?">([^<]+)</td>', row)):
                if val != "—":
                    seen[(i, val)].add(bool(past.strip()))
    ambiguous = [k for k, v in seen.items() if len(v) > 1]
    assert not ambiguous, f"printed both red and black: {ambiguous[:5]}"


def test_the_colour_test_is_made_at_printed_precision():
    """The guard above only holds while the comparison uses the shown value."""
    for key, _label, line, op, fmt, shown in bm.DIALS:
        assert callable(shown)
    mos = next(d for d in bm.DIALS if d[0] == "mos")
    assert mos[5](4.04) == 4.0, "a value printing as 4.0 must compare as 4.0"
    pd = next(d for d in bm.DIALS if d[0] == "pd")
    assert pd[5](0.354) == pd[5](0.349), "0.354 and 0.349 both print 35%"


@pytest.mark.skipif(not METRO_DIR.exists(), reason="metro pages not built")
def test_the_table_headers_are_readable_by_a_civilian():
    h = (METRO_DIR / "grand-rapids-mi" / "index.html").read_text()
    for label in ("Months of supply", "Price vs. last year", "Listings cutting price"):
        assert f"<th class=\"num\">{label}" in h or f">{label}<" in h, label
    assert ">Supply<" not in h and ">Cutting price<" not in h


@pytest.mark.skipif(not METRO_DIR.exists(), reason="metro pages not built")
def test_every_metro_page_carries_a_receipt():
    h = (METRO_DIR / "grand-rapids-mi" / "index.html").read_text()
    assert "Behind this number" in h
    for part in ("What goes in", "The maths", "Why there is a line", "Where it comes from"):
        assert part in h, part


@pytest.mark.skipif(not METRO_DIR.exists(), reason="metro pages not built")
def test_the_sparkline_says_it_is_a_different_measure():
    """It is drawn from the research index and cannot be relabelled into the
    hero's measure — no history of the site's own verdicts exists. Saying so is
    the difference between a second reading and a second, contradictory number."""
    h = (METRO_DIR / "grand-rapids-mi" / "index.html").read_text()
    assert "different signal set" in h
    assert "Warning-sign share, last" not in h, "the old caption is back"


def test_the_methodology_shim_preserves_the_fragment():
    """/methodology#backtest is only useful if the hash survives the redirect,
    and that route is the one every receipt and social post uses."""
    src = (REPO / "pipeline" / "build_metro.py").read_text()
    assert "+ location.hash" in src
    live = REPO / "web" / "methodology" / "index.html"
    if live.exists():
        assert "location.hash" in live.read_text()


@pytest.mark.skipif(not (RESEARCH / "methodology.html").exists(), reason="not built")
def test_the_methodology_page_has_the_anchors_that_were_asked_for():
    h = (RESEARCH / "methodology.html").read_text()
    ids = set(re.findall(r'<h2 id="([a-z-]+)"', h))
    for want in ("backtest", "danger-lines", "seam"):
        assert want in ids, f"#{want} missing (have {sorted(ids)})"
    assert len(ids) == len(re.findall(r'<h2 id="', h)), "duplicate anchor on one page"


def test_a_streak_claim_never_reaches_across_the_seam():
    """streaks.json advances over the whole archive including the reconstructed
    months before the seam, so every one of this month's top 25 exceeded the
    73-month continuous basis. The live page published "89 consecutive months"
    — a run starting sixteen months the wrong side of a seam disclosed two
    sections further down, on the page written to be cited."""
    basis = (REPORT.get("records") or {}).get("basis_months")
    raw = [s["months"] for s in REPORT["top_streaks"]]
    assert max(raw) > basis, "fixture no longer exercises the clamp"
    for m in raw:
        span, clamped = br.streak_span(m, REPORT)
        assert span <= basis
        assert clamped == (m > basis)
    bullet = next(b for b in br.three_bullets(REPORT) if "streak" in b)
    assert str(max(raw)) not in bullet, "the unclamped figure is still published"


@pytest.mark.skipif(not (RESEARCH / "2026-06").exists(), reason="not built")
def test_the_release_page_has_narrative_prose_and_a_way_out_for_homeowners():
    h = (RESEARCH / "2026-06" / "index.html").read_text()
    nar = re.search(r'<div class="narrative">(.*?)</div>', h, re.S)
    assert nar, "the release page lost its narrative"
    assert len(re.findall(r"<p>", nar.group(1))) >= 3
    assert "Check your own ZIP code" in h
    assert "Check your own ZIP code" in (RESEARCH / "index.html").read_text()


def test_the_narrative_reads_the_report_rather_than_summarising_the_tables():
    """Every figure in it has to be one the report computed."""
    n = br.narrative(REPORT)
    rec = REPORT["records"]
    assert f"{rec['wsi']:.1f}%" in n
    assert f"{len(REPORT['flips_to_warning']):,}" in n
    assert f"{REPORT['national']['scored']:,}" in n
    assert br.narrative({}) == "", "narrative invented prose from nothing"
