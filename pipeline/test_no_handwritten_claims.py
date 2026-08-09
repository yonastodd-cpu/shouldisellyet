"""Guard: no hand-written performance number about our own signals.

This test exists because press.html carried a hand-typed backtest ladder that
DRIFTED from the computed truth — it published 155,612 ZIP-years and a
10.2/18.3/27.8 ladder while backtest_results.json said 182,644 and
11.3/18.9/28.1, with the published HOLD rate flattering us by a point. Nobody
noticed for months, because prose has no test.

Any figure the site states about how our signals performed must agree with the
computed artifact it came from. If you change the backtest, these pages update
themselves (they render from /data/backtest.json); this test fails only if
someone types a number back in.
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"


def _backtest():
    return json.loads((WEB / "data" / "backtest.json").read_text())


def _served(page):
    """Page text with HTML comments stripped. Comments legitimately record
    superseded values — press.html documents the wrong ladder it used to
    publish — and a guard that forbids naming an old mistake would push the
    explanation out of the file."""
    return re.sub(r"<!--.*?-->", "", page.read_text(encoding="utf-8", errors="replace"), flags=re.S)


def test_web_extract_matches_the_computed_results():
    src = json.loads((ROOT / "pipeline" / "backtest_results.json").read_text())
    ext = _backtest()
    assert ext["n_pairs"] == src["n_pairs"]
    for level, v in src["levels"].items():
        assert ext["ladder"][level]["decline_pct"] == v["decline_pct"], level


def test_no_page_hardcodes_a_stale_ladder_percentage():
    """Every 'saw prices fall ... N% of the time' figure in served HTML must
    match the computed ladder. The served fallback in press.html is allowed —
    it is generated from the same file — but it must be CURRENT."""
    bt = _backtest()
    allowed = {f'{v["decline_pct"]:.1f}' for v in bt["ladder"].values()}
    pat = re.compile(r"fall the next year ([0-9]+\.[0-9])% of the time")
    for page in WEB.glob("*.html"):
        for found in pat.findall(_served(page)):
            assert found in allowed, (
                f"{page.name} states a ladder figure {found}% that is not in the "
                f"computed backtest {sorted(allowed)} — render it from "
                f"/data/backtest.json instead of typing it")


def test_no_page_hardcodes_a_stale_pair_count():
    bt = _backtest()
    ok = {f'{bt["n_pairs"]:,}', str(bt["n_pairs"])}
    pat = re.compile(r"([0-9]{1,3}(?:,[0-9]{3})+) ZIP-years")
    for page in WEB.glob("*.html"):
        for found in pat.findall(_served(page)):
            assert found in ok, (
                f"{page.name} states {found} ZIP-years; the computed backtest has "
                f'{bt["n_pairs"]:,}')


def test_track_record_numbers_come_from_case_files_only():
    """No lead time may be typed into a page — the cards render from
    web/data/cases/*.json, which tools/backtest_cases.py recomputes."""
    pat = re.compile(r"(?:flagged|caught|warned)[^.]{0,40}?([0-9]{1,2}) months? (?:before|early|ahead)",
                     re.I)
    for page in list(WEB.glob("*.html")) + list(WEB.glob("*.js")):
        hits = pat.findall(_served(page) if page.suffix == ".html"
                           else page.read_text(encoding="utf-8", errors="replace"))
        assert not hits, f"{page.name} hard-codes a lead time {hits}; render it from a case JSON"
