"""What we tell readers the lines are must be what the engine uses.

The Tier B refit moved two thresholds — dom_stretch +40% to +10%,
inventory_surge +50% to +30% — and every surface went on quoting the old ones:
the ZIP pages, llms.txt, the press kit, the research note, and verdict_v2's own
module docstring. A reader was told a rule the engine does not apply.

Python derives its copy from verdict_v2.SPEC. Client JavaScript and committed
HTML cannot import it, so they keep literals and these tests fail when the two
disagree — the arrangement test_prices.py already uses for the two pricing
blocks that cannot import each other either.

Run: python3 -m pytest pipeline/test_threshold_disclosure.py -q
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from verdict_v2 import SPEC, disclosure, methodology_sentence

ROOT = Path(__file__).resolve().parents[1]
D = disclosure()


def test_disclosure_matches_the_spec_it_describes():
    assert D["dom_stretch"] == "+10%" and SPEC["dom_stretch"] == 0.10
    assert D["inventory_surge"] == "+30%" and SPEC["inventory_surge"] == 0.30
    assert D["price_slow"] == "−2%" and SPEC["price_slow"] == -0.02
    assert D["dom_shrink"] == "−20%" and SPEC["dom_shrink"] == -0.20
    assert D["signal_count"] == 3


def test_the_methodology_sentence_states_every_line():
    s = methodology_sentence()
    for line in (D["price_slow"], D["dom_stretch"], D["inventory_surge"]):
        assert line in s, f"the sentence omits {line}"
    assert "Three public signals" in s


def test_the_press_page_states_the_engines_lines():
    """It is in the sitemap and indexable — the one methodology surface a
    crawler is invited to read."""
    html = (ROOT / "web" / "press.html").read_text()
    assert "10% y/y" in html and "30% y/y" in html, "press states the old lines"
    for stale in ("4.0 months", "40% y/y", "above <b>35%</b>", "Four public signals"):
        assert stale not in html, f"press still states {stale!r}"
    assert "three signals" in html.lower()


def test_the_client_dials_agree_with_the_spec():
    """buildMetricRows in the homepage and market-render.js draw the same dials
    the Python renderer does, from the same lines."""
    for name in ("index.html", "market-render.js"):
        js = (ROOT / "web" / name).read_text()
        assert f"line: {D['inventory_surge']} y/y" in js, \
            f"{name} states the wrong inventory line"
        assert "0.30" in js or "0.3" in js, f"{name} lost the inventory threshold"
        assert f"strong line: {D['dom_shrink']} y/y" in js, \
            f"{name} states the wrong strong DOM line"


def test_no_reader_facing_python_copy_states_a_retired_signal():
    """Months of supply and price-cut share are not part of a current reading.
    Any sentence offering them to a reader as a current signal is wrong."""
    src = (ROOT / "pipeline" / "build_pages.py").read_text()
    for stale in ("Four public signals", "four signals for this ZIP",
                  "months of supply (4.0)", "+40% year over year"):
        assert stale not in src, f"build_pages still tells a reader {stale!r}"


def test_the_engine_docstring_matches_its_own_spec():
    """It stated `> +40%` after the refit moved it to +10% — the drift reached
    the file that defines the value."""
    doc = (ROOT / "pipeline" / "verdict_v2.py").read_text().split('"""')[1]
    assert "+10%" in doc and "+30%" in doc
    assert "> +40%" not in doc and "> +50%" not in doc


def test_the_research_index_says_its_basis_is_frozen():
    """Its four-signal table is CORRECT for a historical series that must stay
    comparable month to month. What was missing is that it says so, and that a
    current reading is computed differently."""
    src = (ROOT / "pipeline" / "build_research.py").read_text()
    assert "deliberately frozen" in src
    assert "three signals over active-listing" in src


def test_the_browser_smoke_allowlist_covers_every_disclosed_line():
    """The smoke test subtracts our published danger lines before scanning for
    figures, so its allowlist is a third copy of the same numbers. It went
    stale the moment the lines were recalibrated and reported the NEW +10% as
    a leak — the check catching its own drift, which is the good version of
    this failure but still a failure."""
    smoke = (ROOT / "scripts" / "smoke-browser.mjs").read_text()
    block = smoke[smoke.index("const DISCLOSED = ["):smoke.index("];", smoke.index("const DISCLOSED = ["))]
    for key in ("price_slow", "price_fast", "dom_stretch", "inventory_surge",
                "price_surge", "dom_shrink", "inventory_drop"):
        assert f'"{D[key]}"' in block, \
            f"the smoke allowlist is missing {key} ({D[key]}) and will report it as a leak"


def test_an_act_page_does_not_promise_multiple_signals():
    """With red at 3, price_falling_fast alone reaches ACT — under v1 no single
    check could. Copy promising a reader that "multiple signals" are past the
    line is false on every price-only ACT, and it shipped in the verdict card
    AND the FAQPage JSON-LD."""
    import verdict_v2 as v2
    single = v2.evaluate(v2.MarketV2(zip_code="x", list_price_yoy=-0.08, listings_yoy=0.0))
    assert single.word == "ACT" and len(single.reasons) == 1, \
        "the premise changed; re-check the copy"
    for path in ("pipeline/build_pages.py", "pipeline/data/verdict_copy.json"):
        src = (ROOT / path).read_text()
        assert "Multiple signals" not in src, \
            f"{path} promises multiple signals on a reading one can trigger"


def test_no_generator_offers_a_retired_signal_to_a_reader():
    """Months of supply and price-cut share are not part of a current reading.
    The research EXPLAINER named both, live on /research/methodology.html."""
    src = (ROOT / "pipeline" / "build_research.py").read_text()
    assert "four gauges" not in src
    assert "three gauges" in src
