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
    """A HEAD is meta tags and a title — attribute values, not text nodes.

    This asserted `f">{word}<" not in head`, which requires an element whose
    entire text is "HOLD". A head never contains that, so the assertion could
    not fail on any page, released or paused: it read as coverage while testing
    nothing. Verified dead before rewriting it.

    The head is where the leak actually mattered — a crawler, a social unfurl
    and a shared link read it rather than the body — so it is now checked field
    by field."""
    html = BP.zip_page("20601", ENTRY, PLACE, META, [])
    head = html.split("</head>", 1)[0]

    title = re.search(r"<title>(.*?)</title>", head, re.S).group(1)
    metas = dict(re.findall(r'<meta[^>]+(?:name|property)="([^"]+)"[^>]*content="([^"]*)"', head))
    ld = " ".join(re.findall(r'<script type="application/ld\+json">(.*?)</script>', head, re.S))

    fields = {"<title>": title, **{k: v for k, v in metas.items()
              if k in ("description", "og:title", "og:description", "og:image",
                       "og:image:alt", "twitter:title", "twitter:description")},
              "json-ld": ld}
    for name, value in fields.items():
        for word in VERDICT_WORDS:
            assert not re.search(rf"\b{word}\b", value), f"{name} carries {word}: {value[:70]}"
        for figure in FIGURES:
            assert figure not in value, f"{name} carries the figure {figure}: {value[:70]}"

    assert "og/default.png" in head, "per-ZIP card must fall back to the brand image"
    assert PAUSE.NOTICE_TITLE.split()[0].lower() in title.lower() or "refresh" in title.lower()


def test_paused_zip_page_credits_no_vendor():
    """The stamp published "Data through June 2026 · Data provided by Redfin,
    a national real estate brokerage" directly beneath the rebuilding banner,
    on all 22,874 pages. Attribution is required on a page that DISPLAYS a
    vendor's data; a paused page displays none, so the credit told a reader —
    and a crawler — that the page rests on data it is not showing, naming the
    one vendor data_pause's copy rule says the notice must never name."""
    text = visible_text(BP.zip_page("20601", ENTRY, PLACE, META, []))
    assert "Redfin" not in text, "a paused page credits the withdrawn vendor"
    assert not re.search(r"Data through \w+ \d{4}", text), \
        "a paused page asserts a data vintage it is not showing"


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
    assert "on the market about" in text, "a released ZIP must render its figures"
    # the dial measures time ON MARKET across unsold listings, not time-to-sell
    assert "days to sell" not in text and "TIME TO SELL" not in text


# ————— the two committed static pages —————
#
# Everything above tests GENERATED output. These two are committed files that
# ship in web/ exactly as written, so no pipeline change ever reached them and
# the pause never applied. On 2026-08-20, ten other surfaces closed, both were
# still live and both were in the submitted sitemap — two of its three URLs:
#
#   /report.html  a WATCH for ZIP 20906 ("Early signals moving in 20906") with
#                 the full withdrawn dial set — 2.6 months of supply, 243 homes
#                 sold, −5.7% prices, 43 days, 32% price cuts — plus a
#                 Realtor.com cross-check strip, the national verdict counts
#                 "15,471 ZIPs read HOLD · 7,110 WATCH · 9,485 ACT", and a
#                 Redfin credit. llms.txt advertised it as showing "a real ZIP".
#   /press.html   "HOLD 59% · WATCH 23% · ACT 11% · Verdict mix across all
#                 24,619 scored ZIP codes · data through May 2026".
#
# They are static, so these read the committed files directly rather than
# building anything. That is the point: a generator test could never have
# caught either one.

STATIC_PAGES = {
    "report.html": "the sample report",
    "press.html": "the press kit",
}

# A rating for a named market, the thing the pause exists to withhold.
RATING = re.compile(r"\b(HOLD|WATCH|ACT|STRONG)\b")

# Figures that only the withdrawn vendor data can produce.
WITHDRAWN_FIGURE = (
    re.compile(r"\b\d+\.\d+\s*mo\b"),                 # months of supply
    re.compile(r"\b\d{2,4}\s+homes\b"),               # listing / sold counts
    re.compile(r"\b\d+\s+days?\b"),                   # days on market
    re.compile(r"[\d,]{5,}\s+ZIPs?\s+read"),          # national verdict counts
    re.compile(r"fall the next year [\d.]+% of the time"),   # backtest ladder
    re.compile(r"[\d,]+\s+ZIP-years"),                # backtest population
    re.compile(r"\b24,619\b"),                        # the scored-ZIP count
)


ROOT = Path(__file__).resolve().parents[1]


def _static(name):
    return (ROOT / "web" / name).read_text(encoding="utf-8", errors="replace")


def test_the_sample_report_publishes_no_reading():
    """It served a WATCH for a named ZIP through the whole of the pause."""
    text = visible_text(_static("report.html"))
    found = RATING.findall(text)
    assert not found, f"the sample report still states a rating: {set(found)}"
    assert "20906" not in text, \
        "the sample report still names the real ZIP whose reading it published"
    for pat in WITHDRAWN_FIGURE:
        assert not pat.search(text), \
            f"the sample report still publishes {pat.search(text).group()!r}"


def test_the_press_kit_publishes_no_withdrawn_figure():
    """It served the national verdict mix and the v1 backtest ladder."""
    text = visible_text(_static("press.html"))
    for pat in WITHDRAWN_FIGURE:
        m = pat.search(text)
        assert not m, f"the press kit still publishes {m.group()!r}"
    assert not re.search(r"(HOLD|WATCH|ACT)\s+\d+%", text), \
        "the press kit still charts the verdict mix"


def test_neither_static_page_credits_the_withdrawn_vendor():
    """data_pause's copy rule: a paused surface must not name the vendor whose
    data it is no longer showing. Guarded on ZIP pages since 2026-08-19; these
    two were never brought under it."""
    for name, label in STATIC_PAGES.items():
        src = _static(name)
        assert PAUSE.PAUSED_SOURCE not in src.lower(), \
            f"{label} still credits {PAUSE.PAUSED_SOURCE} while paused"


def test_the_sample_report_is_not_offered_for_indexing():
    """It is a data-display page with no data to display while paused, and it
    was one of three URLs in the submitted sitemap."""
    assert 'content="noindex' in _static("report.html"), \
        "the sample report is indexable while showing no reading"
    src = (ROOT / "pipeline" / "build_pages.py").read_text()
    block = src[src.index("urls = [f\"{SITE}/\""):]
    block = block[:block.index("]") + 1]
    assert "report.html" not in block or "PAUSE" in block, \
        "a noindexed page is still submitted in the sitemap"


def test_a_page_is_indexable_only_when_it_may_show_its_reading():
    """The head and the body must answer the same question.

    robots_meta() asked only whether the ZIP was in a released tranche, while
    the body asked shows_data(zip, basis) — released AND the record actually
    carrying a v2 reading. The two disagreed on 2026-08-20: the store was
    unreachable from CI, every record fell back to {"st": "XX"}, and the 1,000
    released pages shipped "this reading is being refreshed" in the body with
    no noindex in the head. A thousand pages offered to crawlers with nothing
    on them — strictly worse than paused, which at least told the truth twice.
    """
    released, unreleased = "20601", "99999"
    PAUSE._allowlist = None
    try:
        PAUSE._allowlist = {released}
        # released, but the record carries no v2 reading yet
        assert not PAUSE.indexable(released, basis=PAUSE.LEGACY_BASIS), \
            "a released ZIP with no reading is offered for indexing"
        assert "noindex" in PAUSE.robots_meta(released, False, PAUSE.LEGACY_BASIS)
        # released AND the reading is there
        assert PAUSE.indexable(released, basis=PAUSE.RELEASED_BASIS)
        assert PAUSE.robots_meta(released, False, PAUSE.RELEASED_BASIS) == ""
        # never released
        assert not PAUSE.indexable(unreleased, basis=PAUSE.RELEASED_BASIS)
        # and the head agrees with the body, for every combination
        for z in (released, unreleased):
            for b in (PAUSE.LEGACY_BASIS, PAUSE.RELEASED_BASIS):
                assert PAUSE.indexable(z, False, b) == PAUSE.shows_data(z, b), \
                    f"head and body disagree for {z} on basis {b!r}"
    finally:
        PAUSE._allowlist = None


# ————— what a RELEASED page may say about its own data —————
#
# Tranche 1 published 1,000 pages that were right about the reading and wrong
# about everything around it, because meta.json is frozen at the last Redfin
# run and nothing downstream asked which basis the record was on:
#
#   "Data through June 2026"                      — the readings are August
#   "Data provided by Redfin"                     — they are RentCast, two
#                                                   weeks after Redfin stopped
#   "The typical home here sold for +9.3%"        — that is an ASKING price
#   "rising faster than about 66% of U.S. ZIPs"   — ranked against Redfin
#                                                   SOLD-price deciles
#   "15,471 ZIPs read HOLD · 7,110 WATCH…"        — withdrawn Redfin counts
#
# None of it was visible while everything was paused, because a paused page
# blanks its stamp and prose. The release is what made the stale half render.

V2 = "active listings"


def _released_page(zip_code="95608"):
    p = ROOT / "web" / "zip" / zip_code / "index.html"
    if not p.exists():
        pytest.skip("pages not built")
    src = p.read_text(encoding="utf-8")
    if "being refreshed" in src:
        pytest.skip(f"{zip_code} is not released in this build")
    return src


def test_a_released_page_credits_the_source_its_reading_came_from():
    """The disclosure requirement is unchanged — a page showing a reading must
    say where the reading came from. What changed on 2026-08-22 is the FORM:
    the vendor's licence bars use of its marks "in advertising, publicity or any
    other commercial manner" without written consent and requires no
    attribution, so the name is confined to /methodology.html and every other
    surface credits the source generically. This asserts the credit is present,
    not that it names anyone."""
    src = _released_page()
    assert "Market statistics from a licensed data provider" in src, \
        "the page does not name the source of its reading"
    assert "RentCast" not in src, \
        "the vendor is named outside /methodology.html — see docs/ATTRIBUTION.md"
    assert "redfin" not in src.lower(), \
        "a reading is credited to Redfin — a vendor whose data was withdrawn"


def test_a_released_page_dates_itself_from_its_own_reading():
    """Not from meta.json, which is frozen at the last v1 run."""
    import json
    rec = json.loads((ROOT / "web" / "data" / "z" / "95608.json").read_text())
    if rec.get("b") != V2:
        pytest.skip("95608 not released")
    month = rec.get("p")
    assert month, "the record carries no as-of month"
    pretty = f"{BP.MONTHS[int(month[5:7]) - 1]} {month[:4]}"
    src = _released_page()
    assert f"Data through {pretty}" in src, \
        f"the page is dated from meta.json, not from its reading ({pretty})"


def test_a_released_page_does_not_call_an_asking_price_a_sale_price():
    """v2 reads active listings. Asking prices run higher than sale prices —
    the distinction the methodology page exists to make."""
    src = _released_page()
    assert "sold for" not in src, \
        "the page describes an asking-price change as a sale price"


def test_a_released_page_publishes_no_cross_basis_comparison():
    """spy_deciles ranks SOLD-price changes. A v2 spy is an ASKING-price
    change. Ranking one against the other is not a national percentile."""
    src = _released_page()
    assert not re.search(r"rising faster than about \d+%", src), \
        "a v2 reading is ranked against v1 sold-price deciles"


def test_the_homepage_withholds_the_withdrawn_national_counts():
    js = (ROOT / "web" / "index.html").read_text()
    assert 'd.b === "active listings"' in js, \
        "the homepage still shows Redfin national counts beside a v2 reading"


def test_the_client_rendered_stamp_also_follows_the_record():
    """The ZIP pages are server-rendered; the homepage card and the paid report
    are drawn in the browser and kept their own copy of the same bug. Fixing
    build_pages left "Data through 2026-06 · Data provided by Redfin" under a
    live RentCast reading on the front door — found by opening the site, not by
    any gate."""
    for name in ("index.html", "my-report.html"):
        js = (ROOT / "web" / name).read_text(encoding="utf-8")
        assert 'active listings' in js and "a licensed data provider" in js, \
            f"{name} still stamps every reading with the v1 attribution"
        # The vendor name is confined to methodology.html pending counsel on
        # RentCast's trademark clause. Source COMMENTS may still name it — this
        # checks rendered copy, which is what the clause reaches.
        visible = re.sub(r"//[^\n]*|/\*.*?\*/|<!--.*?-->", "", js, flags=re.S)
        assert "RentCast" not in visible, f"{name} names the vendor in rendered copy"
