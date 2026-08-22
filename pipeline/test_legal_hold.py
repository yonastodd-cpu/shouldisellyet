"""The legal hold must be enforced by code, not by intention.

A standing preservation instruction took effect 22 August 2026: Redfin-derived
material is preserved and not deleted without counsel's direction. Two places
in this repo could delete such material. These tests assert both are guarded,
and that the guard is switched by LEGAL_HOLD.md actually existing — a hold that
depends on everyone remembering it is not a hold.
"""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_the_hold_file_exists_and_says_what_it_is():
    p = ROOT / "LEGAL_HOLD.md"
    assert p.exists(), "LEGAL_HOLD.md is the switch; without it the guards go quiet"
    t = p.read_text(encoding="utf-8")
    assert "We do not delete it" in t
    assert "#4688700" in t, "the hold must record that the GitHub ticket stays paused"
    assert "lineage, not display" in t, "scope must be lineage, not displayed figures"


def test_backtest_cases_moves_aside_rather_than_unlinking_under_hold():
    src = (ROOT / "tools" / "backtest_cases.py").read_text(encoding="utf-8")
    assert 'LEGAL_HOLD.md").exists()' in src, \
        "the prune must consult the hold file, not a constant"
    # the unlink must be reachable ONLY on the not-held branch
    block = src[src.index("_hold = ("):]
    block = block[:block.index("\n\n")] if "\n\n" in block else block
    assert "f.rename(" in block and "f.unlink()" in block, "both branches must exist"
    assert block.index("f.rename(") < block.index("f.unlink()"), \
        "the held branch must come first and short-circuit"


def test_ci_keeps_a_blocked_terms_capture_as_evidence():
    y = (ROOT / ".github" / "workflows" / "update.yml").read_text(encoding="utf-8")
    assert 'rm -f "$DIR/redfin-data-center.html"' not in y, \
        "a blocked capture is evidence that retrieval was attempted; do not delete it"
    assert "redfin-data-center.BLOCKED.html" in y


def test_no_sql_deletes_the_tagged_rows():
    """The DB rows tagged source='redfin' are in scope for the hold."""
    for f in (ROOT / "supabase").glob("*.sql"):
        t = f.read_text(encoding="utf-8").lower()
        for stmt in ("delete from market_stats", "truncate market_stats",
                     "drop table market_stats"):
            assert stmt not in t, f"{f.name} would remove held rows"


def test_readme_surfaces_the_hold_before_the_first_section():
    t = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "LEGAL_HOLD.md" in t
    assert t.index("LEGAL_HOLD.md") < t.index("## Architecture"), \
        "a contributor must meet the hold before the setup instructions"
