"""Digest section 3: the marketing queue replaced a dead filename.

growth_digest.py had no tests at all before this file. These cover the one
thing this change could get wrong in a way nobody would notice: printing
"0 tasks this week" when the truth is "we could not read the queue". A zero is
a measurement; a gap is not. The repo says this out loud in three other places
(growth_digest's own header, the Gaps box, perf_checks NULL vs 0) and it is
the rule most worth a test here.

Run: python3 -m pytest pipeline/test_growth_digest.py -q
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import growth_digest as gd

# render_digest reads all four flip buckets by name, so the fixture carries
# them empty rather than omitting them — an absent bucket is a KeyError, which
# is a fixture bug that would look like a code bug.
FLIPS = {"to_act": [], "to_watch": [], "to_hold": [], "to_strong": []}

BASE = dict(period="2026-06", entries={}, flips=FLIPS, angles=[], hook=None,
            hook_csv=None, counts=None, gaps=[], rate_now=None, rate_prior=None,
            rate_asof="", places={}, baseline=False, demo=False, research_html="")

QUEUE = {"n": 4, "headlines": [
    "WSI hit 62.2% — the lowest share since December 2025.",
    "Austin-Round Rock-San Marcos, TX just crossed the line.",
    "Homes in 20904 are taking 12 days longer to sell than a year ago.",
]}


def test_queue_renders_count_link_and_top3_only():
    html = gd.render_digest(queue=QUEUE, **BASE)
    assert "Your marketing queue: 4 tasks this week" in html
    assert "/admin.html#marketing" in html
    for h in QUEUE["headlines"]:
        assert h in html, f"missing headline: {h}"
    # Top THREE. A digest that lists the whole queue is the queue, and the
    # operator already has a screen for that.
    assert html.count("<li>") <= 3 + html.count('<li style=')


def test_singular_task_reads_correctly():
    html = gd.render_digest(queue={"n": 1, "headlines": ["One thing."]}, **BASE)
    assert "1 task this week" in html
    assert "1 tasks" not in html


def test_unreadable_queue_is_a_gap_never_a_zero():
    """queue=None means we could not ask. It must never render as 0 tasks."""
    html = gd.render_digest(queue=None, **BASE)
    assert "Marketing queue unavailable this refresh" in html
    assert "0 tasks this week" not in html
    assert "marketing queue: 0" not in html.lower()


def test_empty_queue_is_allowed_to_say_zero():
    """A real, readable, empty week is a measurement and may say so."""
    html = gd.render_digest(queue={"n": 0, "headlines": []}, **BASE)
    assert "0 tasks this week" in html


def test_archive_folder_prose_is_gone():
    """The line this change removed pointed at a gitignored directory that
    expires after 90 days and was never a link."""
    html = gd.render_digest(queue=QUEUE, **BASE)
    assert "archive folder" not in html


def test_summary_returns_none_without_config(monkeypatch):
    """House rule: no Supabase config is a gap, not a crash and not a zero."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert gd.marketing_queue_summary("2026-06") is None
