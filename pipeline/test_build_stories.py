"""The story page tells the truth the case file tells.

This page is built for cold audiences — the people least equipped to catch a
wrong number and least likely to forgive one. Every figure it shows has to come
from web/data/cases/{id}.json, and the staged reveal has to not contradict its
own prose.

Run: python3 -m pytest pipeline/test_build_stories.py -q
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))

import build_stories as bs

CASE = json.loads((REPO / "web" / "data" / "cases" / "boise-2021.json").read_text())
MISS = json.loads((REPO / "web" / "data" / "cases" / "miss-39500.json").read_text())


def test_the_headline_facts_match_the_case_file():
    """Not a spot check — the three numbers the whole story rests on."""
    page = bs.story_page(CASE, MISS)
    assert f"{CASE['lead_months']} months" in page
    assert bs.money(CASE["peak_price"]) in page
    assert bs.money(CASE["trough_price"]) in page
    assert bs.pretty(CASE["first_signal"]) in page


def test_peak_to_trough_is_the_stored_value_not_a_recomputation():
    """The card that recomputed a run once published 'fifth month in a row'
    against a truth of three. The same discipline applies here: the drop is
    read, and it agrees with the prices it is drawn between."""
    computed = (CASE["trough_price"] - CASE["peak_price"]) / CASE["peak_price"]
    assert abs(computed - CASE["peak_to_trough"]) < 0.0005, \
        "the case file's peak_to_trough disagrees with its own peak and trough"
    assert bs.pct(CASE["peak_to_trough"], 1) in bs.story_page(CASE, MISS)


def test_the_first_panel_does_not_show_the_crash():
    """Beat one says prices are at record highs and still climbing. Drawing the
    whole series under it shows the fall before the sentence claiming nothing
    looks wrong — the one thing the panel must not do."""
    months = [r["month"] for r in CASE["series"]]
    sig_i = months.index(CASE["first_signal"])
    p1 = bs.panel(CASE, 1)
    pts = re.search(r'<polyline points="([^"]+)" fill="none" stroke="#1f3a5f"', p1)
    assert pts, "no price line in panel 1"
    assert len(pts.group(1).split()) == sig_i + 1, \
        "panel 1 draws past the signal month and gives away the ending"


def test_the_panels_share_one_x_scale():
    """The reveal only reads as one chart revealing itself if the drawn portion
    never moves. Same first point in every stage."""
    firsts = []
    for stage in (1, 2, 3):
        pts = re.search(r'<polyline points="([^"]+)" fill="none" stroke="#1f3a5f"',
                        bs.panel(CASE, stage))
        firsts.append(pts.group(1).split()[0])
    assert len(set(firsts)) == 1, f"the price line moves between stages: {firsts}"


def test_early_panels_never_label_a_price_the_line_has_not_reached():
    """$515K printed above a line that stops at $464K sits directly under a
    sentence about record highs and quietly contradicts it."""
    months = [r["month"] for r in CASE["series"]]
    sig_i = months.index(CASE["first_signal"])
    reached = bs.money(CASE["series"][sig_i]["price"])
    peak = bs.money(CASE["peak_price"])
    p1 = bs.panel(CASE, 1)
    assert reached in p1
    assert peak not in p1, "panel 1 labels the eventual peak"
    assert peak in bs.panel(CASE, 3), "panel 3 should reveal the peak"


def test_the_tell_is_described_in_plain_words_with_its_line():
    """A danger line the reader cannot interpret is decoration."""
    p2 = bs.panel(CASE, 2)
    assert "How much longer homes sat than a year earlier" in p2
    assert "danger line" in p2
    line = CASE["crossings"]["dom_stretch"]["line"]
    assert bs.pct(line) in p2


def test_every_panel_carries_alt_text_that_states_the_fact():
    """A screen reader should get the story, not the word 'chart'."""
    for stage in (1, 2, 3):
        alt = re.search(r'aria-label="([^"]+)"', bs.panel(CASE, stage))
        assert alt and len(alt.group(1)) > 40
        assert CASE["name"] in alt.group(1) or "same" in alt.group(1).lower()


def test_the_coda_names_the_miss_and_refuses_to_invent_one():
    """A track record with no misses is a sales page. The coda reads the miss
    case, so it can never describe a market the data does not support."""
    coda = bs.coda(MISS)
    assert MISS["name"] in coda
    assert bs.pretty(MISS["first_signal"]) in coda
    assert bs.coda(None) == "", "the coda invented a miss out of nothing"


def test_main_refuses_to_publish_without_a_miss_case(tmp_path, monkeypatch, capsys):
    """The honesty coda is not optional decoration. With no miss on disk the
    build declines to write a story at all rather than shipping one that
    implies a perfect record."""
    empty = tmp_path / "cases"
    empty.mkdir()
    (empty / "boise-2021.json").write_text(json.dumps(CASE))
    monkeypatch.setattr(bs, "CASES", empty)
    monkeypatch.setattr(bs, "ROOT", tmp_path)
    bs.main()
    assert "refusing" in capsys.readouterr().out
    assert not (tmp_path / "web" / "stories").exists()


def test_render_is_deterministic():
    """Same case, same bytes. This runs on every deploy."""
    assert bs.story_page(CASE, MISS) == bs.story_page(CASE, MISS)


def test_the_page_carries_article_json_ld_and_a_canonical():
    page = bs.story_page(CASE, MISS)
    ld = json.loads(re.search(r'application/ld\+json">(.*?)</script>', page, re.S).group(1))
    assert ld["@type"] == "Article"
    assert ld["url"].endswith("/stories/boise/")
    assert 'rel="canonical"' in page


def test_no_banned_attribution_constructions():
    page = bs.story_page(CASE, MISS).lower()
    for phrase in ("powered by", "in partnership with", "endorsed by", "sponsored by"):
        assert phrase not in page


def test_the_homepage_teaser_types_no_numbers():
    """It renders from web/data/stories.json for the same reason the story page
    reads the case file: two places stating one number is one place too many."""
    html = (REPO / "web" / "index.html").read_text()
    section = re.search(r'<section class="band" id="story".*?</section>', html, re.S)
    assert section, "the story teaser is gone from the homepage"
    # Copy only — tag names carry digits of their own ("<h2>") and an element
    # name is not a claim about the housing market.
    copy = re.sub(r"<[^>]+>", " ", section.group(0))
    assert not re.search(r"\d", copy), f"a figure was typed into the teaser copy: {copy!r}"
    assert "data/stories.json" in html
