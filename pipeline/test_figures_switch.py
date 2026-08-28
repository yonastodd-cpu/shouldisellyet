"""FIGURES_KILL_SWITCH: the word survives, every vendor figure does not.

Two failure modes, and the second is the dangerous one.

  1. The switch does nothing. Easy to notice.
  2. The switch does MOST of it. A page with blanked dials whose <title>,
     meta description, og:description, JSON-LD and share stub still carry the
     numbers reads as done and is not — that is precisely what Phase 0 shipped
     three times (see test_pause_leaks.py) before anyone checked the head.

So these tests assert the ABSENCE of this ZIP's figures across body, head and
structured data, and separately assert the PRESENCE of the reading word — the
separation is the claim, and a switch that quietly took the word with it would
also be broken.

The three renderers are pinned to each other at the bottom. Client JavaScript
cannot import a Python module, so index.html and market-render.js keep
literals and this file fails when any of the three disagrees — the arrangement
test_threshold_disclosure.py already uses for the thresholds.

Run: python3 -m pytest pipeline/test_figures_switch.py -q
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import build_pages as BP
import data_pause as PAUSE
import figures_switch as FIG

ROOT = Path(__file__).resolve().parents[1]
PLACE = ("Waldorf", "MD", "Charles County")
META = {"period": "2026-08", "generated": "2026-08-22",
        "national": {"spy_deciles": [-1.0, -0.2, -0.1, -0.05, 0.0,
                                     0.02, 0.06, 0.11, 0.21, 0.49, 999.0]}}

# A released v2 reading with every figure populated — the worst case, and the
# shape provision_readings actually writes (see .build/readings/01007.json).
ENTRY = {
    "p": "2026-08", "l": "yellow", "s": 1,
    "r": [["inventory_surge", 1, 0.5909]], "b": "active listings", "st": "MD",
    "m": {"spy": 0.0586, "dom": 57.27, "domy": -6.4, "invy": 0.5909,
          "inv": 105.0, "ppsfy": 0.0956, "nly": -0.3125},
    "h": {"s": "2025-09",
          "p": [425000, 435000, 425000, 415000, 389000, 389000,
                419000, 455000, 455000, 420000, 449900, 449900],
          "d": [64, 57, 57, 61, 76, 81, 72, 64, 47, 42, 52, 57]},
}

# Every figure in ENTRY as some renderer would format it. Substrings, because
# a leak that rounds differently is still a leak.
FIGURES = ("5.9%", "5.86", "57 days", "57.27", "105", "59%", "0.5909",
           "9.6%", "31%", "6 days", "425,000", "449,900", "$449", "$425")

RENDERERS = ("index.html", "market-render.js")


@pytest.fixture
def figures_off(monkeypatch):
    """The switch on, and the pause off for this ZIP so the pause cannot be
    the thing doing the hiding. Every test below would pass trivially if the
    page were merely paused."""
    monkeypatch.setattr(FIG, "FIGURES_OFF", True)
    monkeypatch.setattr(PAUSE, "PAUSED", False)
    yield


@pytest.fixture
def figures_on(monkeypatch):
    monkeypatch.setattr(FIG, "FIGURES_OFF", False)
    monkeypatch.setattr(PAUSE, "PAUSED", False)
    yield


def visible_text(html):
    body = html.split("<body", 1)[-1]
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


def head_of(html):
    return html[:html.index("</head>")]


def ld_of(html):
    return " ".join(json.dumps(json.loads(b)) for b in re.findall(
        r'<script type="application/ld\+json">(.*?)</script>', html, re.S))


# ————— the switch is off by default —————

@pytest.mark.skipif(FIG.FIGURES_OFF,
                    reason="the switch is on — this checks the resting state")
def test_the_resting_state_is_unchanged_behaviour():
    """Someone must be able to deploy this and see no difference. The flag
    ships off; the tests turn it on.

    Deliberately skipped rather than inverted once the switch is thrown, the
    way test_data_pause skips its paused-only assertions. Flipping a kill
    switch during an incident must not also require editing a test to make CI
    green — that is how a switch stops being usable at the moment it is
    needed."""
    assert FIG.shows_figures() is True
    for name in RENDERERS:
        src = (ROOT / "web" / name).read_text()
        assert re.search(r"const\s+FIGURES_OFF\s*=\s*false\s*;", src), \
            f"{name} does not ship the switch off"


def test_figures_render_normally_when_the_switch_is_off(figures_on):
    html = BP.zip_page("20601", ENTRY, PLACE, META, [])
    text = visible_text(html)
    assert "57 days" in text, "the dials stopped rendering with the switch OFF"
    assert "WATCH" in text


# ————— the ZIP page —————

def test_no_figure_reaches_the_zip_page_body(figures_off):
    html = BP.zip_page("20601", ENTRY, PLACE, META, [])
    text = visible_text(html)
    for v in FIGURES:
        assert v not in text, f"{v!r} still in the body with figures withheld"
    # The prose facts are built from the same withheld metrics and render in
    # the body — the leak that shipped during the pause for exactly this
    # reason (test_pause_leaks.py). Naming a metric is fine; stating this
    # ZIP's value for it is not.
    for phrase in ("is asking", "sold for", "have been on the market about",
                   "rising faster than"):
        assert phrase not in text, f"paged still says {phrase!r}"


def test_no_figure_reaches_the_zip_page_head_or_structured_data(figures_off):
    """The half that reads as done and is not: a crawler, a social unfurl and
    a shared link never see the body."""
    html = BP.zip_page("20601", ENTRY, PLACE, META, [])
    for where, blob in (("head", head_of(html)), ("JSON-LD", ld_of(html))):
        for v in FIGURES:
            assert v not in blob, f"{v!r} still in the {where}"


def test_the_reading_word_survives_everywhere(figures_off):
    """The whole point. We told counsel the word is ours and separable; a
    switch that took it too would not be that claim."""
    html = BP.zip_page("20601", ENTRY, PLACE, META, [])
    assert "WATCH" in visible_text(html), "the reading pill lost its word"
    assert "WATCH" in head_of(html), "the reading word left the metadata"
    assert "Early signals moving in 20601" in html, "the headline went with it"
    # and the page is still an indexable page with something true on it
    assert 'content="noindex' not in html, \
        "withholding figures noindexed the page — that is the pause's job"


def test_the_disclosed_danger_lines_survive(figures_off):
    """Publishing OUR rule is not publishing THEIR figure. The methodology
    sentence states every line on every page and must go on doing so."""
    text = visible_text(BP.zip_page("20601", ENTRY, PLACE, META, []))
    assert BP.DISCLOSED["inventory_surge"] in text
    assert "How this reading is computed" in text


def test_the_answer_sentence_states_the_reading_not_the_pause(figures_off):
    """An answer engine lifts this line whole. Falling through to the pause
    copy would tell it the reading is being rebuilt, which is false."""
    html = BP.zip_page("20601", ENTRY, PLACE, META, [])
    answer = re.search(r'<p class="answer">(.*?)</p>', html, re.S).group(1)
    assert "WATCH" in answer
    assert PAUSE.NOTICE_TITLE not in answer, \
        "a reading with withheld figures is claiming to be a paused reading"
    for v in FIGURES:
        assert v not in answer


def test_the_zip_page_stops_pointing_at_the_rendered_card(figures_off):
    """The card has its stat painted into the pixels, so no later branch can
    blank it — and cards rendered BEFORE the flip are still on disk."""
    html = BP.zip_page("20601", ENTRY, PLACE, META, [], has_card=True)
    assert "/og/2026-08/20601.png" not in html
    assert "/og/default.png" in html


# ————— the share stub —————

def test_no_figure_reaches_the_share_stub(figures_off):
    """Pure metadata, read by scrapers and nothing else — which is why it was
    the surface the pause forgot."""
    html = BP.share_stub("20601", ENTRY, PLACE, META, has_card=True)
    for v in FIGURES:
        assert v not in html, f"{v!r} still in the share stub"
    assert "/og/2026-08/20601.png" not in html
    assert "WATCH" in html, "the stub lost the reading word too"


# ————— the OG card —————

def test_the_rendered_card_carries_no_figure(figures_off, tmp_path):
    """The card is re-rendered under the switch with a figure-free evidence
    line, so what is on disk after a build is safe even though the pages no
    longer link to it."""
    stat = BP.card_stat(FIG.metrics(ENTRY["m"]))
    for v in FIGURES:
        assert v not in stat
    assert not re.search(r"\d", stat), f"card stat still numeric: {stat!r}"


# ————— the module —————

def test_metrics_and_history_are_withheld_together(figures_off):
    assert FIG.metrics(ENTRY["m"]) == {}
    assert FIG.history(ENTRY["h"]) is None
    assert FIG.shows_figures() is False


def test_strip_removes_values_and_keeps_the_reading(figures_off):
    """For anything that SHIPS a record. Hiding a figure the client already
    downloaded is not withholding it — the Realtor cross-check shipped inside
    every public per-ZIP file that way."""
    out = FIG.strip(ENTRY)
    assert "m" not in out and "h" not in out
    assert out["l"] == "yellow" and out["b"] == "active listings"
    assert out["r"] == [["inventory_surge", 1]], \
        "the reason CODE is our rule's name and stays; its value is theirs"
    assert json.dumps(ENTRY) == json.dumps(ENTRY), "strip mutated its input"


def test_strip_is_a_no_op_while_the_switch_is_off(figures_on):
    assert FIG.strip(ENTRY) is ENTRY


# ————— the three renderers agree —————

def test_all_three_renderers_carry_the_same_switch():
    """One flag, three copies, and this is what makes that true. Flipping the
    Python and forgetting index.html leaves the homepage — which renders from
    a record fetched at runtime, so the static build cannot reach it — drawing
    every dial the ZIP pages just stopped drawing."""
    py = FIG.FIGURES_OFF
    for name in RENDERERS:
        src = (ROOT / "web" / name).read_text()
        m = re.search(r"const\s+FIGURES_OFF\s*=\s*(true|false)\s*;", src)
        assert m, f"{name} has no {FIG.JS_CONST} literal"
        assert (m.group(1) == "true") == py, (
            f"{name} says FIGURES_OFF={m.group(1)} while "
            f"pipeline/figures_switch.py says {py} — the switch is not one switch")


def test_every_client_figure_renderer_is_behind_the_switch():
    """Comments stripped first, so documenting the switch cannot be mistaken
    for honouring it — the trap test_threshold_disclosure hit when a note
    string passed for a threshold."""
    def code(name):
        src = (ROOT / "web" / name).read_text()
        src = re.sub(r"//[^\n]*", "", src)
        return re.sub(r"/\*.*?\*/", "", src, flags=re.S)

    home = code("index.html")
    assert re.search(r"function buildMetricRows[^{]*\{\s*if \(FIGURES_OFF\) return \[\];", home), \
        "index.html draws its dials without asking the switch"
    assert re.search(r"const h = FIGURES_OFF \? null : d\.h;", home), \
        "index.html's masked preview still reads the history series"
    assert re.search(r"const spy = FIGURES_OFF \? null : ", home), \
        "index.html still computes the national price percentile"

    mr = code("market-render.js")
    assert re.search(r"function buildMetricRows[^{]*\{\s*if \(FIGURES_OFF\) return \[\];", mr), \
        "market-render.js draws its dials without asking the switch"
    assert re.search(r"function lineSVG[^{]*\{\s*if \(FIGURES_OFF\) return \"\";", mr), \
        "market-render.js still plots the twelve-month series"
    # STRONGER THAN FIGURES_OFF, deliberately. The prior vendor's sold-price
    # deciles were first refused behind a hard `false &&`, then (2026-08-28)
    # the interpolation was DELETED outright when the box was rebuilt on the
    # live current-basis distribution (web/data/distribution.json). The pin is
    # now absence: no code path may reference the prior-vendor decile field.
    assert "spy_deciles" not in mr, \
        "market-render.js references the prior vendor's deciles again — "\
        "the national percentile must come from the live distribution only"
    assert "showsFigures()" in mr, \
        "the report pages have no way to ask, so they will type their own copy"


def test_the_switch_is_not_the_pause():
    """Different questions, different modules, and neither may quietly become
    the other. The pause decides whether a ZIP has a reading at all; this
    decides whether the figures behind a reading may be published."""
    src = (Path(__file__).parent / "figures_switch.py").read_text()
    body = src.split('"""', 2)[-1]          # past the module docstring
    assert "noindex" not in body, \
        "figures_switch is deciding indexability; that is data_pause's call"
    assert "import data_pause" not in src, \
        "figures_switch reaching into the pause makes one flag into two"
