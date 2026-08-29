"""The two committed pages publish no figure with the prior vendor in it.

WHY THIS FILE EXISTS, AND WHY IT IS NOT test_pause_leaks.py.

test_pause_leaks asks a DISPLAY question: does a surface show a figure from the
withdrawn vendor, or name it? Four audits asked that question and all four
passed, because the largest exposures on these two pages are numbers we
computed ourselves out of the vendor's measurements — a case study's
peak-to-trough, a national percentile interpolated against their sold-price
deciles, an index built from 173 of their monthly readings. Not one of those
contains a vendor string, and no display test can reach a number that was
computed rather than copied.

So this file asks the LINEAGE question instead, on the only two pages in the
repository that are hand-written and committed rather than generated:
web/index.html and web/report.html. A pipeline change never reaches either of
them, which is exactly how both ended up serving withdrawn figures through a
pause that had closed ten other surfaces.

Each test below names the specific thing that shipped, so a later reader can
tell whether a failure is a regression or a rebuild.

WHAT IS DELIBERATELY NOT ASSERTED HERE. Narrative about the company's history
is allowed, and so is a link to a page that publishes its own figures. Only
FIGURES are in scope. The mandatory-copy assertions in test_homepage_voice.py
still own the wording; this file owns the numbers.

Run: python3 -m pytest pipeline/test_prior_vendor_serving_surfaces.py -q
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))

import figures_switch as FIG

INDEX = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
REPORT = (ROOT / "web" / "report.html").read_text(encoding="utf-8")


def code(src):
    """Source with comments removed.

    Documenting a withdrawal quotes the thing withdrawn — the comments below
    name the case panel's sentence, the index's own name and the v1 ladder on
    purpose, so a reader can see what went. A test that fired on its own
    rulebook would be deleted rather than obeyed (the trap
    test_threshold_disclosure hit when a note string passed for a threshold),
    so every assertion here runs on code and markup, never on commentary.
    """
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"//[^\n]*", " ", src)


INDEX_CODE = code(INDEX)
REPORT_CODE = code(REPORT)


# ————— item 6: the homepage case-study panel —————

def test_the_case_panel_flag_is_off():
    """It shipped ON by operator decision on 2026-08-09 and rotated one
    recomputed case into row 08's expansion for every visitor who expanded it:
    "<Metro> — our dials crossed in <YYYY-MM>; prices first fell <N> months
    later, then <X>% peak to trough." Every one of those four fields was
    computed from the prior vendor's hub exports."""
    m = re.search(r"const\s+SHOW_CASE_ROW\s*=\s*(true|false)\s*;", INDEX_CODE)
    assert m, "SHOW_CASE_ROW is gone; the decision it records is not"
    assert m.group(1) == "false", "the homepage case panel is publishing again"


def test_the_case_panel_has_no_query_string_bypass():
    """`?case=1` forced the panel on regardless of the flag. A preview switch
    and a withdrawal are different things, and the second one may not have a
    bypass anyone can type into a URL bar."""
    assert "case=1" not in INDEX_CODE, \
        "the homepage case panel can be re-armed from the query string"


def test_the_homepage_does_not_fetch_the_case_index():
    """data/cases/index.json is still committed and still world-readable, and
    every row in it — Boise −17.86%, Austin −25.58%, Cape Coral −17.75%, and
    the labelled miss Quincy IL-MO — is a ratio of two of the prior vendor's
    median prices. Not fetching it is this page's half of that; moving the file
    is somebody else's."""
    for url in re.findall(r'fetch\(\s*"([^"]+)"', INDEX_CODE):
        assert "data/cases" not in url, \
            f"the homepage still downloads the case index: {url}"


def test_no_case_figure_can_be_rendered():
    """The panel's own rendered vocabulary. If any of these come back, so has
    the panel — whatever the flag says.

    Scoped to the strings the panel PRINTED rather than to the case fields
    themselves: renderStory still names peak_to_trough and lead_months behind
    its own withdrawal flag, and the test below is what holds that shut. Two
    guards, two tests, so a failure says which one gave way."""
    for phrase in ("peak to trough", "our dials crossed", "pv-case",
                   "See how this was computed"):
        assert phrase not in INDEX_CODE, \
            f"the case panel's {phrase!r} is back on the homepage"


def test_the_macro_panel_states_its_condition_rather_than_half_filling():
    """Row 08's expansion carried three prior-vendor figures — the national
    percentile, the index level and the case study. Dropping one and keeping
    two would read as a working panel while still publishing what we said we
    had stopped publishing, so the box says what happened to all three."""
    # First-launch framing since 2026-08-29 (the site never had outside
    # customers, so "rebuild" narrated history no visitor ever saw). The
    # panel still STATES ITS CONDITION rather than half-filling — the copy is
    # now forward-looking coverage honesty instead of a rebuild notice.
    assert "once coverage is broad enough to support it" in INDEX_CODE, \
        "the macro panel's expansion lost its condition statement"
    assert "not a share of the country" in INDEX_CODE, \
        "row 08 lost its condition statement"
    # And it does not blame lateness or name the vendor.
    assert "redfin" not in INDEX_CODE.lower(), \
        "the homepage names the prior vendor in code or markup"


# ————— item 6: the v1 backtest ladder —————

def test_the_v1_backtest_ladder_is_absent_from_the_homepage():
    """10.2 / 18.3 / 27.8 over 155,612 ZIP-years, and the 24,619 scored-ZIP
    count that travelled with them. The signal side of that backtest is
    entirely the prior vendor's tracker, and it measured the retired five-
    signal engine besides.

    Verified absent when this was written, and pinned so it stays that way:
    the ladder is the figure most likely to be pasted back in by someone
    reaching for proof that the danger lines work."""
    for fig in ("10.2", "18.3", "27.8", "155,612", "155612", "24,619", "24619"):
        assert fig not in INDEX, f"the v1 backtest ladder figure {fig!r} is back"
    for phrase in ("ZIP-years", "zip-year", "fall the next year"):
        assert phrase not in INDEX, f"the v1 backtest population {phrase!r} is back"


def test_the_narrative_survives_and_says_what_it_rests_on():
    """The rule is figures out, narrative may stay — with the note. A trust
    claim that says the backtests are published, when they have been withdrawn,
    is worse than no claim at all."""
    # Reworded 2026-08-29 (first-launch framing): the paragraph now claims
    # only a calibration and PROMISES the backtest, rather than citing a
    # validation whose data belonged to the prior vendor — the property is
    # still that no published-backtest claim exists for the current engine.
    assert "a backtest of the current engine will be published" in INDEX, \
        "the neutrality section stopped saying the backtest is future work"
    # The mandatory clause test_homepage_voice pins, kept verbatim through the
    # rewrite — it is the sentence that admits the misses.
    assert "including the times a warning appeared and the market recovered" in INDEX
    assert "So are the thresholds and backtests" not in INDEX, \
        "the homepage still claims the withdrawn backtests are published"


# ————— the homepage's other prior-vendor figures —————

def test_the_national_price_percentile_cannot_be_computed():
    """"Prices here are rising faster than about 63% of U.S. ZIP codes." The
    input is ours and current; the eleven cut points it is ranked against are
    the prior vendor's SOLD-price deciles, so the output has them in it — and
    it compares asking prices against sold prices besides.

    The generated ZIP pages withheld this same sentence months ago
    (build_pages.py: "Withheld until the deciles are rebuilt on the active-
    listing basis"). The homepage expansion was missed by that change, which is
    why the refusal is asserted in the function rather than at the call site:
    there will be a second call site eventually, as there already was between
    this page and market-render.js."""
    assert re.search(r"const\s+NATIONAL_DECILES_WITHDRAWN\s*=\s*true\s*;", INDEX_CODE), \
        "the national-decile withdrawal flag is gone"
    assert re.search(r"function pvPercentile\([^)]*\)\s*\{\s*"
                     r"if \(NATIONAL_DECILES_WITHDRAWN\) return null;", INDEX_CODE), \
        "pvPercentile will compute a percentile against the prior vendor's deciles"


def test_the_national_verdict_counts_are_withheld_unconditionally():
    """"Across the country right now: 15,471 ZIPs read HOLD · 7,110 WATCH ·
    9,485 ACT", frozen at the last run before ingestion stopped.

    The old gate withheld these only when the record's basis was "active
    listings". Two records still reached the other branch: the committed DEMO
    fallback, which carries no basis at all, and any legacy record. The counts
    are prior-vendor-derived whatever they sit beside, so the record was never
    the right thing to ask."""
    assert re.search(r"const\s+nc\s*=\s*null\s*;", INDEX_CODE), \
        "the homepage decides the national counts from the record again"


def test_the_index_level_is_neither_fetched_nor_rendered():
    """173 monthly values, every one computed from the prior vendor's
    measurements — named in LEGAL_HOLD.md as held material. The fetch ran on
    every page load whether or not anybody expanded the row, so the value
    reached every visitor's browser regardless of what was drawn."""
    assert "wsi.json" not in INDEX_CODE, \
        "the homepage downloads the index level again"
    assert "PV_WSI" not in INDEX_CODE, \
        "the homepage has somewhere to put the index level again"
    for phrase in ("Warning-Sign Index", "showed warning signs in"):
        assert phrase not in INDEX_CODE, f"{phrase!r} renders on the homepage again"


def test_the_committed_demo_records_carry_no_vendor_measurement():
    """Two hardcoded per-ZIP records in the source of the highest-traffic page,
    carrying raw v1 metric blocks — {mos, spy, dom, domy, pd}. `mos` and `pd`
    are fields the current source cannot produce, so they were closed-sale
    measurements, not derived indicators.

    Invisible to every tracer we had: the crawl gate reads innerText and these
    are JavaScript constants, so nothing rendered them until data/index.json
    failed — and then they rendered as a real reading, for exactly the two ZIPs
    the input placeholder invites."""
    block = re.search(r"const DEMO = \{(.*?)\n\};", INDEX_CODE, re.S)
    assert block, "the DEMO fallback is gone; lookup() still calls it"
    body = block.group(1)
    for key in ("mos:", "spy:", "dom:", "domy:", "pd:"):
        assert key not in body, \
            f"the DEMO fallback carries the vendor measurement {key!r} again"
    assert not re.search(r"-?\d*\.\d+", body), \
        "a measured value is back in the committed fallback records"


def test_the_homepage_story_renderer_refuses_rather_than_relying_on_empty_data():
    """It printed a case study's lead-in-months and peak-to-trough onto the
    front door. It draws nothing today for two accidental reasons — there is no
    id="story" element, and data/stories.json is empty because the story
    builder is paused — and neither is a decision anybody made about lineage.
    Restoring the markup or unpausing the builder would put the figures back
    with no code change and no review."""
    assert re.search(r"const\s+STORY_FIGURES_WITHDRAWN\s*=\s*true\s*;", INDEX_CODE), \
        "the story renderer is dark by accident again, not by decision"
    assert re.search(r"async function renderStory\(\)\s*\{\s*"
                     r"if \(STORY_FIGURES_WITHDRAWN\) return;", INDEX_CODE), \
        "renderStory no longer checks the withdrawal before fetching"


# ————— item 7: the sample report —————

def test_the_sample_report_makes_no_claim_about_purchased_reports():
    """It said: "Nothing has been deleted, and no report you have purchased is
    affected." The second half is not true. Parts of a purchased report are
    computed from the same withdrawn measurements — the stored approach-
    velocity rows behind its timing section, the danger-line validation
    sentence, and the source credit printed at its foot. Telling a paying
    customer their copy is unaffected, on the page whose entire job is
    explaining what they are buying, is the worst place for that claim."""
    assert "no report you have purchased is affected" not in REPORT, \
        "the sample report claims purchased reports are unaffected"
    # Checked on the served file, not just the rendered text: an HTML comment
    # ships to anything that reads the document instead of running it, so the
    # note recording this removal paraphrases the claim rather than quoting it.
    assert "purchased is affected" not in REPORT, \
        "the withdrawn claim survives somewhere in the served markup"
    # First-launch framing (2026-08-29): the preservation statement addressed
    # customers who had seen the withdrawn sample — an audience that never
    # existed. What stands in its place must still be true of purchased
    # reports: they are built live from current data, not restored history.
    assert "built live" in REPORT, \
        "the sample page no longer says what a purchased report actually is"


def test_the_sample_report_is_not_selling_while_the_sample_is_withdrawn():
    """This page exists to show a buyer what they get before they pay, and it
    cannot do that today — what replaced the sample is a notice. The buttons
    are REMOVED rather than styled as disabled: a disabled look with a live
    href is still a live href to anything that reads the markup instead of
    rendering it, which is the same mistake the withdrawn figures made in this
    page's <head>."""
    assert "subscribe.html" not in REPORT_CODE, \
        "the sample report links checkout while showing no sample"
    assert "purchase_click" not in REPORT_CODE, \
        "the sample report still carries a purchase CTA"
    assert not re.search(r"\$\d+\.\d\d", REPORT_CODE), \
        "the sample report quotes a price beside a withdrawn sample"
    # The free check is not a sale and must survive — removing it would leave a
    # page with no way forward at all.
    assert "index.html#check" in REPORT_CODE, \
        "the free ZIP check went with the paid CTAs"


def test_the_sample_reports_social_unfurl_promises_nothing_it_cannot_show():
    """The <meta name="description"> was updated when the sample was withdrawn
    and og:description was missed — the surface nobody rechecks, because it
    renders in someone else's feed and never in a tab of ours. It still
    promised "Real market data" and "the four market dials", which is also the
    v1 gauge count; a current reading has three."""
    og = re.search(r'<meta property="og:description" content="([^"]*)"', REPORT)
    assert og, "the sample report lost its og:description"
    text = og.group(1)
    assert "Real market data" not in text, \
        "the unfurl promises market figures the page has withdrawn"
    assert "four market dials" not in text, \
        "the unfurl states the v1 gauge count"


# ————— item 3b: the figures kill switch reaches this page —————

def test_the_sample_report_asks_the_switch_instead_of_copying_it():
    """figures_switch.py named this page as a surface the switch could not
    reach: it computes `val / (1 + m.spy)` and prints a dollar figure, and
    referenced the switch nowhere.

    It asks market-render.js rather than declaring its own literal. The three
    renderers are pinned to each other by test_figures_switch; a fourth
    hand-typed copy would be the one nobody edits on the day the switch is
    flipped, which is the exact failure that pin exists to prevent."""
    assert "MARKET.showsFigures()" in REPORT_CODE, \
        "the sample report does not ask whether figures may be shown"
    assert not re.search(r"const\s+FIGURES_OFF\s*=", REPORT_CODE), \
        "the sample report declares a fourth copy of the flag"


def test_the_sample_report_withholds_the_record_not_each_sink():
    """Eight separate places on this page print something derived from `m` or
    `h`: the dials, the peak callout, the from-peak percentage, the 12- and
    3-month changes, the days-on-market chart, the "cleared fastest in <month>"
    line, the year-ago dollar figure and the stress-test row. Gating them one
    at a time is eight chances to miss one — and the seasonality line contains
    no numeral at all, so it is the one that would be missed.

    Withholding at the record instead routes every block down the absent-data
    path it already has, which runs for most of the country every day rather
    than being a branch nobody has executed."""
    assert re.search(r"const m = SHOWS_FIGURES \? d\.m : \{\}, "
                     r"h = SHOWS_FIGURES \? d\.h : null", REPORT_CODE), \
        "the sample report reads the vendor halves of the record ungated"


def test_the_withheld_line_is_the_modules_wording():
    """One withholding, one sentence. If this page writes its own copy, the
    Python surfaces and this one will eventually say two different things about
    the same decision."""
    assert FIG.WITHHELD_LINE in REPORT, \
        "the sample report states the withholding in its own words"


def test_the_switch_still_ships_off():
    """Nothing here flips it. This file withdraws PRIOR-vendor figures, which
    is a different question from withholding the CURRENT vendor's — and a
    change to one that quietly moved the other would be a change nobody
    reviewed."""
    assert FIG.FIGURES_OFF is False
    assert re.search(r"const\s+FIGURES_OFF\s*=\s*false\s*;", INDEX_CODE)
