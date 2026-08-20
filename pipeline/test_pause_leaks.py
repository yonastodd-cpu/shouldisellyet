"""Every surface that renders a figure must honour the pause.

These exist because three did not, and shipped to production for the whole of
Phase 0. Verified live on 2026-08-19 before the fix:

  /zip/20601/  body prose: "The typical home here sold for +0.2% compared with
               a year ago", "Homes are taking about 61 days to sell — 21 days
               slower than a year ago", "Prices here are rising faster than
               about 44% of U.S. ZIP codes" — under a header saying the
               reading was being refreshed.
  /zip/MD/     the state hub listed a verdict word per ZIP: 137 HOLD, 127 ACT,
               108 WATCH.
  /s/20601/    <title> "…housing market check: HOLD — no warning signs" and
               og:description "Homes here sell in 61 days."

The pattern in all three: the pause was applied where somebody remembered to
apply it. A blanking that covers the metadata and forgets the prose, or covers
the page and forgets the index that links to it, is not a blanking. So these
tests assert the ABSENCE of numbers on every surface rather than the presence
of the notice on one.

Run: python3 -m pytest pipeline/test_pause_leaks.py -q
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import build_pages as BP
import data_pause as PAUSE

PLACE = ("Waldorf", "MD", "Charles County")
META = {"period": "2026-06", "generated": "2026-08-10",
        "national": {"spy_deciles": [-1.0, -0.2, -0.1, -0.05, 0.0,
                                     0.02, 0.06, 0.11, 0.21, 0.49, 999.0]}}

# A legacy entry with every figure populated — the worst case for leakage.
ENTRY = {
    "l": "green", "s": 0, "r": [], "st": "MD",
    "m": {"mos": 3.8, "spy": 0.002, "pd": 0.297, "dom": 61.0, "domy": 21.0,
          "invy": 0.12, "inv": 108, "sold": 85},
    "h": {"s": "2023-07", "p": [434250] * 36, "d": [40] * 36},
    "f": {"y": 2025, "a1": 2.64, "a3": 5.25},
}

# The figures that must never appear on a paused surface, as rendered.
FIGURES = ("3.8", "61 days", "108", "29.7%", "0.2%", "+0.2")
VERDICT_WORDS = ("HOLD", "WATCH", "ACT")


def visible_text(html):
    body = html.split("<body", 1)[-1]
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body, flags=re.S | re.I)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", body))


@pytest.fixture(autouse=True)
def paused(monkeypatch):
    monkeypatch.setattr(PAUSE, "PAUSED", True)
    monkeypatch.setattr(PAUSE, "_allowlist", None)
    yield


# ————— the ZIP page —————

def test_paused_zip_page_publishes_no_prose_figures():
    """The leak that shipped: facts_html is built from the same withdrawn
    metrics as the dials and renders in the page body, and the pause branch
    cleared everything around it except itself."""
    html = BP.zip_page("20601", ENTRY, PLACE, META, [])
    text = visible_text(html)
    # Naming a metric and its published danger line is DISCLOSURE — the
    # methodology paragraph says "months of supply (4.0)" on every page and
    # should. What must never appear is this ZIP's own value.
    for phrase in ("sold for", "days to sell", "rising faster than"):
        assert phrase not in text, f"paused page still says {phrase!r}"
    for value in ("3.8 mo", "61 days", "29.7%", "+0.2%"):
        assert value not in text, f"paused page still publishes {value!r}"


def test_paused_zip_page_shows_the_notice_instead():
    text = visible_text(BP.zip_page("20601", ENTRY, PLACE, META, []))
    assert PAUSE.NOTICE_TITLE in text


def test_paused_zip_page_metadata_carries_no_verdict():
    html = BP.zip_page("20601", ENTRY, PLACE, META, [])
    head = html.split("</head>", 1)[0]
    for word in VERDICT_WORDS:
        assert f">{word}<" not in head
    assert "og/default.png" in head, "per-ZIP card must fall back to the brand image"


# ————— the state hub —————

def test_paused_state_hub_lists_no_verdict_words():
    """The hub builds its own rows in main() and was publishing the very
    readings the pages it links to refuse to show."""
    rows = [("20601", "Waldorf", "Charles County", "", "#6b6861"),
            ("20874", "Germantown", "Montgomery County", "", "#6b6861")]
    text = visible_text(BP.state_hub("MD", rows, META))
    # The hub's own explainer line says "A free HOLD / WATCH / ACT verdict for
    # each of the N markets" — that is the product description, not a reading.
    # What must not appear is a verdict word attached to a listed ZIP.
    listing = text.split("verdict for each", 1)[-1]
    for word in VERDICT_WORDS:
        assert f" {word} " not in listing, f"state hub still labels a ZIP {word}"


# ————— the share stub —————

def test_paused_share_stub_has_no_verdict_or_metric():
    """A share stub is pure metadata for scrapers, which is exactly why it
    must honour the pause — it had no pause check at all."""
    html = BP.share_stub("20601", ENTRY, PLACE, META, has_card=True)
    title = re.search(r"<title>(.*?)</title>", html, re.S).group(1)
    assert PAUSE.NOTICE_TITLE.split()[0].lower() in title.lower() or "refreshed" in title
    for word in VERDICT_WORDS:
        assert word not in title
    assert "sell in" not in html and "61 days" not in html


def test_paused_share_stub_falls_back_to_the_brand_card():
    """The per-ZIP OG image has the numbers painted into the pixels, so it
    goes with everything else."""
    html = BP.share_stub("20601", ENTRY, PLACE, META, has_card=True)
    assert "og/default.png" in html
    assert f"/og/{META['period']}/20601.png" not in html


# ————— the released path still works —————

def test_a_released_zip_still_renders_its_figures(monkeypatch, tmp_path):
    """The blanking must be conditional, not unconditional — otherwise Phase 4
    releases nothing."""
    tf = tmp_path / "tranches.json"
    tf.write_text('{"tranches":[{"name":"t","released_utc":"2026-08-20T00:00:00Z",'
                  '"zips":["20601"]}]}')
    monkeypatch.setattr(PAUSE, "TRANCHES", tf)
    monkeypatch.setattr(PAUSE, "_allowlist", None)
    v2 = dict(ENTRY, b="active listings",
              m={"spy": -0.075, "dom": 52.0, "domy": -3.0, "invy": 0.08, "inv": 979})
    text = visible_text(BP.zip_page("20601", v2, PLACE, META, []))
    assert PAUSE.NOTICE_TITLE not in text
    assert "days to sell" in text
