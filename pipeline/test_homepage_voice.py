"""The homepage speaks to a homeowner, and keeps doing so.

web/index.html is the only committed, hand-written page on the site, and until
now nothing guarded its copy — so the 2026-08-12 simplification could be undone
one well-meaning edit at a time. These tests encode the rules that simplification
established, and the two sentences that earlier briefs marked as mandatory.

Run: python3 -m pytest pipeline/test_homepage_voice.py -q
"""

import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
HTML = (REPO / "web" / "index.html").read_text()

# The reader-facing markup only: everything before the single <script>. The
# script legitimately contains engine vocabulary (verdict keys, level codes)
# that never reaches the page as prose.
MARKUP = HTML.split("<script>")[0]
# CSS is not copy either — the stylesheet carries engine vocabulary in its own
# comments (".pv-open … percentile, WSI and the research link"), and a rule
# about what a reader is shown must not be tripped by a selector name.
TEXT = re.sub(r"<style.*?</style>", " ", MARKUP, flags=re.S)
TEXT = re.sub(r"<!--.*?-->", " ", TEXT, flags=re.S)        # comments are for us
TEXT = re.sub(r"<[^>]+>", " ", TEXT)                        # tags are not copy
TEXT = re.sub(r"\s+", " ", TEXT)


def test_the_surveillance_answer_is_still_on_the_page():
    """Marked mandatory when step 4 was written: it answers the surveillance
    read of an alert product head-on. Step 4 was folded into step 3 in the
    simplification; the sentence came with it and is not optional."""
    assert "We monitor the market, not you." in TEXT


def test_the_danger_lines_are_still_disclosed_beside_the_readers_numbers():
    """The four numeric thresholds left the front door in the simplification.
    A 2026-08-08 note called them DISCLOSURES, and the defence of removing the
    cards is that buildMetricRows() still prints every one next to the reader's
    OWN figure the moment a ZIP is checked. If that stops being true, the cards
    have to come back."""
    script = HTML.split("<script>", 1)[1]
    for line in ("4.0 mo", "−2% y/y", "35%", "+50% y/y"):
        assert line in script, f"danger line {line!r} no longer reaches the verdict card"


def test_no_acronyms_or_index_vocabulary_in_homepage_copy():
    """WSI belongs on the research page, which is written for press and
    analysts. A stranger checking their ZIP should never meet it."""
    for word in ("WSI", "Warning-Sign Index", "warning-sign index"):
        assert word not in TEXT, f"{word!r} reached homepage copy"


def test_no_internal_vocabulary_in_homepage_copy():
    """Words the engine uses about itself, which mean nothing to a homeowner."""
    for word in ("flipped verdicts", "scored ZIPs", "verdict engine",
                 "insufficient_data", "months-to-line"):
        assert word.lower() not in TEXT.lower(), f"internal vocabulary {word!r} in copy"
    # …including in the strings the proof line builds at runtime.
    assert "flipped verdicts" not in HTML


def test_no_numeric_danger_thresholds_in_the_static_copy():
    """The thresholds are homework before a reader has a reason to care. They
    belong beside the reader's own number, and on the methodology page."""
    for line in ("Danger line", "Danger lines"):
        assert line not in TEXT, f"{line!r} is back in the static copy"


def test_the_honesty_band_still_points_at_the_methodology():
    """The band's whole claim is 'nothing is hidden'. It has to link."""
    assert "smoke detector, not a fortune teller" in TEXT
    assert 'href="/methodology/"' in MARKUP


def test_the_hit_rate_date_is_rendered_and_never_typed():
    """It lives in web/data/validation.json, which the methodology page states
    it from. Typing it here lets the two disagree the first time it moves — in
    the one band on the page whose job is being trustworthy."""
    assert re.search(r"\b20\d\d\b", TEXT.split("smoke detector")[1][:400]) is None, \
        "a hard-coded year appeared in the honesty band"
    assert 'id="hitrate"' in MARKUP
    assert "data/validation.json" in HTML


def test_banned_attribution_constructions_never_appear():
    """docs/ATTRIBUTION.md, enforced on the one page anybody actually reads."""
    # Checked on reader-facing copy, not the raw file: the sources-strip comment
    # states the rule by quoting the very phrase it forbids ('no logos, no
    # wordmarks, no "powered by"'), and a lint that fires on its own rulebook
    # gets deleted rather than obeyed.
    for phrase in ("powered by", "in partnership with", "partnered with",
                   "official partner", "official data source", "endorsed by",
                   "sponsored by"):
        assert phrase not in TEXT.lower(), f"banned construction {phrase!r} in copy"


@pytest.mark.parametrize("section", ["why", "how", "signals", "alerts", "pricing"])
def test_the_page_still_has_its_sections_in_order(section):
    assert f'id="{section}"' in MARKUP


def test_sections_appear_in_the_simplified_order():
    """Claim, then how it works, then the honesty band, then the ask. Pricing
    must not climb back above the free check."""
    order = [s for s in ("why", "how", "signals", "alerts", "pricing")]
    positions = [MARKUP.index(f'id="{s}"') for s in order]
    assert positions == sorted(positions), f"sections out of order: {order}"
