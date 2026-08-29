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
from verdict_v2 import SPEC, disclosure
from verdict_copy import methodology_sentence

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
    assert "Three signals drawn from licensed market statistics" in s
    # the feed is licensed, not public, and the dial is time on market
    assert "public signal" not in s
    assert "take to sell" not in s


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


def test_the_client_dial_COLOURS_at_the_line_it_displays():
    """The label and the branch are two different numbers, and only one of them
    was checked.

    Both files rendered "strong line: −20% y/y" while branching on p <= -0.15,
    and coloured the danger state at p > 0.4 against a spec of +10%. The test
    above passed throughout, because a note string is not a threshold. A ZIP
    whose DOM rose 20% y/y was amber server-side and green client-side — the
    same ZIP, two colours, depending on which renderer drew it.

    Comments are stripped first: the fix documents the retired numbers on the
    line above the branch, and a guard that forbids naming an old mistake
    pushes the explanation out of the file.
    """
    stretch, shrink = SPEC["dom_stretch"], SPEC["dom_shrink"]
    for name in ("index.html", "market-render.js"):
        src = (ROOT / "web" / name).read_text()
        code = re.sub(r"//[^\n]*", "", src)          # line comments
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)

        branch = re.search(r"p\s*<=\s*(-?[\d.]+)\s*\?\s*\"s\"", code)
        assert branch, f"{name}: could not find the strong-DOM branch"
        assert float(branch.group(1)) == shrink, (
            f"{name} colours the strong dial at {branch.group(1)} but the spec "
            f"line is {shrink} — the label says {D['dom_shrink']}")

        danger = re.search(r"p\s*>\s*(-?[\d.]+)\s*\?\s*\"a\"", code)
        assert danger, f"{name}: could not find the DOM danger branch"
        assert float(danger.group(1)) == stretch, (
            f"{name} colours the danger dial at {danger.group(1)} but the spec "
            f"line is {stretch} — the label says {D['dom_stretch']}")


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


def test_the_frozen_spec_doc_states_the_calibrated_lines():
    """The doc a future reader opens to learn what the engine does.

    Its scoring table kept the pre-refit +40% / +50% / −15% long after the Tier
    B calibration moved them, while its own header correctly said the live
    numbers live in SPEC. That split — prose pointing at the code, a table
    quoting the code from memory — is exactly how a spec document rots without
    anyone noticing, and it is the same drift this file already guards on five
    other surfaces.
    """
    doc = (ROOT / "docs" / "migration" / "reading-methodology-v2.md").read_text()
    # Slice from the table itself, NOT from the "## The reading" heading. The
    # explanatory note under that heading quotes the retired figures on purpose
    # ("+40% → +10%"), and including it both muddied the stale-figure checks and
    # swallowed the mutation that proves this test works: reverting the table to
    # +40% left the note's own "+10%" satisfying the assertion.
    table = doc[doc.index("Danger signals, scored:"):doc.index("Recorded on every reading")]

    assert f"> {D['dom_stretch']}" in table, "the doc's DOM line is not the spec's"
    assert f"> {D['inventory_surge']}" in table, "the doc's inventory line is not the spec's"
    assert f"active DOM YoY ≤ {D['dom_shrink']}" in table, \
        "the doc's seller's-market DOM line is not the spec's"
    assert f"total listings YoY ≤ {D['inventory_drop']}" in table

    # The pre-refit figures, which are correct ABOVE this section as v1 history
    # and wrong inside it as current lines.
    for stale in ("> +40%", "> +50%"):
        assert stale not in table, f"the scoring table still states {stale!r}"


def test_the_methodology_page_states_every_line_the_engine_uses():
    """The site's own methodology page, created 2026-08-20.

    Until then /methodology redirected to /research/methodology.html — a
    document about the Warning-Sign Index, a deliberately FROZEN four-signal
    series. Every "see our methodology" link on the site delivered a reader to
    a paper about a different metric than the one their ZIP page shows.

    It is hand-written, like press.html, so it gets the same guard: every
    number on it must be the number the engine uses.
    """
    html = (ROOT / "web" / "methodology.html").read_text()
    for key in ("price_slow", "price_fast", "dom_stretch", "inventory_surge",
                "price_surge", "dom_shrink", "inventory_drop"):
        assert D[key] in html, f"the methodology page omits the {key} line ({D[key]})"
    assert f"<b>ACT</b> at {SPEC['red']} points" in html
    assert f"<b>WATCH</b> at {SPEC['yellow']}" in html
    assert f"fewer than {SPEC['min_known']} of the three signals" in html

    # The retired signals may be NAMED as retired; they may not be offered.
    for stale in ("all four", "four public signals", "four signals"):
        assert stale not in html.lower(), f"the methodology page offers {stale!r}"
    assert "Gone." in html, "the page no longer says the two lost signals are gone"


def test_the_methodology_page_does_not_claim_a_crosscheck_that_is_not_running():
    """The Realtor.com cross-check compared against the FORMER vendor's figures
    and was never rebuilt for the new source. web/market-render.js hides the
    strip when the record carries no cross-check field, which is every record.
    Copy asserting it in the present tense described something dormant."""
    html = (ROOT / "web" / "methodology.html").read_text()
    # Since 2026-08-29 the page says NOTHING about a cross-check at all
    # (operator decision: a switched-off feature gets no copy) — the property
    # this test protects is only that no PRESENT-TENSE claim of a running
    # cross-check exists.
    assert "cross-check is shown" not in html
    assert "cross-check against Realtor" not in html, \
        "the methodology page claims a cross-check that is not running"


def test_no_page_promises_act_means_multiple_lines():
    """With red at 3, price_falling_fast alone reaches ACT. The homepage FAQ
    JSON-LD — the most quotable methodology statement on the site, served to
    answer engines — asserted the opposite. The existing guard scanned only
    build_pages.py and verdict_copy.json for the capitalised string, so it
    could not see this."""
    import verdict_v2 as v2
    single = v2.evaluate(v2.MarketV2(zip_code="x", list_price_yoy=-0.08, listings_yoy=0.0))
    assert single.word == "ACT" and len(single.reasons) == 1, "the premise changed"
    # Match the CLAIM, not one phrasing of it. The first version of this test
    # looked for "multiple danger lines are crossed" — the JSON-LD wording —
    # and passed while press.html's legend said "multiple lines crossed" four
    # words differently, on the page this file calls the one methodology
    # surface a crawler is invited to read.
    claim = re.compile(r"multiple[^<.]{0,30}lines", re.I)
    for path in list((ROOT / "web").glob("*.html")) + \
                [ROOT / "pipeline" / "data" / "verdict_copy.json",
                 ROOT / "pipeline" / "build_pages.py"]:
        m = claim.search(path.read_text(encoding="utf-8", errors="replace"))
        assert not m, (f"{path.name} promises {m.group()!r} on a reading a "
                       "single signal can trigger")


# ————— Terms of Service —————

def test_the_terms_disclose_sources_basis_and_cadence():
    """Counsel Q5 asked what the terms must disclose about (a) the new data
    sources, (b) the shift from sold-home to for-sale measurements, and (c) the
    varying refresh cadence. Before 2026-08-20 the terms disclosed none of the
    three, and named a vendor we had stopped taking data from."""
    tos = (ROOT / "web" / "terms.html").read_text()
    assert "differ from final sale prices" in tos, "(b) the basis shift is undisclosed"
    assert "currently listed for sale" in tos
    assert "Freshness varies by ZIP code" in tos, "(c) the cadence variance is undisclosed"
    assert "public domain" in tos, "(a) the supporting sources are unnamed"
    assert "not an appraisal or valuation" in tos
    assert "should not be the basis of a decision to sell" in tos
    assert "Consult a licensed real-estate professional" in tos


def test_the_terms_do_not_name_a_vendor_we_no_longer_use():
    import data_pause as PAUSE
    tos = (ROOT / "web" / "terms.html").read_text().lower()
    assert PAUSE.PAUSED_SOURCE not in tos, \
        f"the terms still name {PAUSE.PAUSED_SOURCE} as a current data source"


def test_no_existing_disclaimer_was_dropped_when_the_terms_were_strengthened():
    """A strengthening pass that quietly removes a protection is a weakening
    pass. These are the clauses the pre-2026-08-20 terms carried; every one
    must still be there."""
    tos = " ".join(re.sub(r"<[^>]+>", " ",
                          (ROOT / "web" / "terms.html").read_text()).split()).lower()
    for clause in ("not financial", "not an appraisal", "no guarantee",
                   "consult licensed professionals", "general information",
                   "not an offer", "not a prediction", "as is", "as available",
                   "without warranties of any kind",
                   "does not account for your circumstances",
                   "decisions about your home are yours",
                   "licensed professional who knows your specific facts"):
        assert clause in tos, f"the terms lost the {clause!r} protection"


def test_the_homepage_promises_no_freshness_the_site_cannot_keep():
    """The methodology page says the refresh cadence is not settled. The
    homepage said the opposite in three places at once — "readings refresh the
    moment new figures land", "refreshed on publication", "readings recompute
    automatically when new figures publish" — beside a step describing a
    licensed vendor's statistics as "public housing-market data".

    Comments are stripped: the fixes quote the retired wording on purpose, and
    a guard that forbids naming an old mistake pushes the explanation out.
    """
    src = (ROOT / "web" / "index.html").read_text()
    code = re.sub(r"//[^\n]*", "", src)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    for claim in ("refresh the moment new figures land",
                  "refreshed on publication",
                  "recompute automatically",
                  "latest public housing-market data"):
        assert claim not in code, (
            f"the homepage claims {claim!r} while the methodology page says the "
            "cadence is not settled and the source is licensed")


def test_no_headline_stat_is_computed_from_the_withdrawn_counts():
    """meta.national.counts is Redfin-derived and frozen at the last v1 run.
    The result card stopped showing it; the coverage line and the "1 in N ZIP
    codes changed rating" stat were still summing it, so the same withdrawn
    figure kept reaching the page by another route."""
    src = (ROOT / "web" / "index.html").read_text()
    assert 'd.b === "active listings"' in src, "the result card can still show it"
    i = src.index("async function renderChangedStat")
    body = src[i:i + 1400]
    assert re.search(r"^\s*return;\s*$", body, re.M), \
        "the changed-rating stat is computed again from withdrawn inputs"
