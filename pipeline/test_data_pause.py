"""The sunset switch does what it claims, on every surface.

Phase 0 of the Redfin→RentCast migration takes every vendor-derived number off
the site without deleting a page. The failure mode this file exists to prevent
is a *partial* blanking that reads as done: a banner over the gauges while the
verdict is still in the title, the OG tags, the JSON-LD and the sitemap.

Run: python3 -m pytest pipeline/test_data_pause.py -q
"""

import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))

import data_pause as PAUSE

HOMEPAGE = (REPO / "web" / "index.html").read_text()


def test_the_homepage_decides_per_zip_not_per_page():
    """This replaces a check that the homepage's DATA_PAUSED constant agreed
    with data_pause.PAUSED. Two switches that could disagree was one too many —
    but ONE switch turned out to be one too few. A page-level boolean knows
    nothing about which ZIP was asked for, so Phase 4 could not release a
    tranche through it: released ZIPs would still read "being refreshed", and
    the only other lever republished everything.

    The homepage now decides from the record. A ZIP outside a released tranche
    is provisioned as {"st":"MD"} with no level, and no level means no reading.

    It also has to be crash-safe. KINDS[d.l] on a record with no level was
    undefined and the next line threw inside the reveal timeout, so a visitor
    saw the spinner disappear and nothing replace it — verified broken in
    production on 2026-08-19, on every one of the 22,874 pages whose CTA lands
    on /?zip=NNNNN."""
    assert "const DATA_PAUSED" not in HOMEPAGE, \
        "the page-level flag is back; Phase 4 cannot release a tranche through it"
    assert "const hasReading = !!(d.l && KINDS[d.l])" in HOMEPAGE, \
        "the homepage must decide from the record, and guard KINDS lookup"
    assert "if (!hasReading) {" in HOMEPAGE, \
        "the notice branch must key off the record"
    # and the guard must precede the first use of k
    assert HOMEPAGE.index("const hasReading") < HOMEPAGE.index("$(\"v-head\").style.background = k.soft"), \
        "the level guard must come before k is dereferenced"


@pytest.mark.skipif(not PAUSE.PAUSED, reason="only meaningful while paused")
def test_a_paused_zip_page_leaks_no_verdict_anywhere():
    """Body, head AND structured data. The head is the one that matters most:
    a crawler, a social unfurl and a shared link read the title, description
    and OG tags, never the banner."""
    pages = sorted((REPO / "web" / "zip").glob("*/index.html"))
    if not pages:
        pytest.skip("no ZIP pages built in this checkout")
    h = pages[0].read_text()
    head = h[:h.index("</head>")]
    for word in ("HOLD", "WATCH", "ACT", "STRONG"):
        assert word not in head, f"{word} still in the <head> of a paused page"
    for blob in re.findall(r'<script type="application/ld\+json">(.*?)</script>', h, re.S):
        s = json.dumps(json.loads(blob))
        for word in ("HOLD", "WATCH", "ACT", "STRONG", "months of supply"):
            assert word not in s, f"{word} still in JSON-LD on a paused page"
    assert 'content="noindex' in h, "a paused page is missing its robots meta"


@pytest.mark.skipif(not PAUSE.PAUSED, reason="only meaningful while paused")
def test_paused_pages_stay_crawlable_and_return_200():
    """noindex only works if the crawler can fetch the page and read it.
    robots.txt must NOT disallow the paused paths, and nothing may 404, 410 or
    redirect them — that is what keeps the URLs re-enableable in Phase 4."""
    rt = REPO / "web" / "robots.txt"
    if rt.exists():
        body = rt.read_text()
        for path in ("/zip/", "/metro/", "/research/"):
            assert f"Disallow: {path}" not in body, \
                f"robots.txt blocks {path} — the noindex would never be read"


@pytest.mark.skipif(not PAUSE.PAUSED, reason="only meaningful while paused")
def test_paused_urls_are_out_of_the_sitemap():
    sm = sorted((REPO / "web" / "sitemaps").glob("*.xml"))
    if not sm:
        pytest.skip("no sitemap built in this checkout")
    urls = "".join(p.read_text() for p in sm)
    assert "/zip/2" not in urls and "/metro/" not in urls, \
        "paused pages are still being submitted for indexing"


def test_ingestion_is_actually_stopped_not_just_documented():
    """The guard has to be on the network path of every entry point — the
    workflow gate does not disarm a script somebody runs by hand."""
    for f, needle in (("pipeline/fetch_data.py", "guard_fetch"),
                      ("tools/backtest_cases.py", "guard_fetch"),
                      ("pipeline/backtest_thresholds.py", "guard_fetch")):
        assert needle in (REPO / f).read_text(), f"{f} can still fetch"
    wf = (REPO / ".github" / "workflows" / "update.yml").read_text()
    i = wf.index("Decide rebuild vs deploy-only")
    gate = wf[i:i + 2000]
    assert 'echo "changed=false"' in gate and "REDFIN SUNSET" in gate
    assert 'echo "deploy=true"' in gate, \
        "the deploy path must stay open — generated dirs are rebuilt each deploy"


def test_the_stop_time_is_recorded():
    assert re.match(r"\d{4}-\d{2}-\d{2}T", PAUSE.INGESTION_STOPPED_UTC)
    assert (REPO / "docs" / "REDFIN-SUNSET.md").exists()
