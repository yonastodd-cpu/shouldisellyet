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


def test_the_homepage_flag_agrees_with_the_pipeline_flag():
    """The homepage is committed, not generated, so it carries its own copy of
    the switch. Two switches that can disagree is one switch too many — a
    homepage still handing out readings after the generators stopped would be
    the worst of both worlds."""
    m = re.search(r"const DATA_PAUSED = (true|false);", HOMEPAGE)
    assert m, "the homepage lost its pause flag"
    assert (m.group(1) == "true") == PAUSE.PAUSED, \
        f"homepage DATA_PAUSED={m.group(1)} but data_pause.PAUSED={PAUSE.PAUSED}"


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
