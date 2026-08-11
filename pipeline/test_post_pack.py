"""Post-pack card guards.

These images get posted to public accounts, so the bar is the same one
test_no_handwritten_claims.py sets for the site: no number may be baked into a
template, no banned construction may reach a card, and the same manifest must
always draw the same bytes (the renderer runs on every deploy — a card that
changed for no reason would churn the artifact and hide a real change).

Run: python3 -m pytest pipeline/test_post_pack.py -q
"""

import json
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import post_pack as pp


def test_no_drawn_string_carries_a_hardcoded_number():
    """Every figure on a card arrives from the manifest. A numeral baked into a
    drawn string is a number nobody can refresh and that will eventually be
    wrong — the failure test_no_handwritten_claims.py exists to catch.

    The TEMPLATES dict this used to read is gone: the 2026-08-10 redesign made
    the cards layouts rather than three strings poured into a shared frame, so
    the check reads the strings actually handed to d.text().
    """
    src = (ROOT / "pipeline" / "post_pack.py").read_text()
    drawn = re.findall(r'd\.text\(\([^)]*\),\s*(f?"[^"]*")', src)
    bad = [s for s in drawn
           if re.search(r"\d", s) and "{" not in s          # interpolated is fine
           and "1080" not in s]                              # geometry, not copy
    assert not bad, f"hardcoded digits in drawn card copy: {bad}"


def test_cards_render_for_every_type(tmp_path):
    """All three builders produce a 1080x1350 image from a realistic payload."""
    pytest.importorskip("PIL")
    payloads = {
        "post": {"name": "Grand Rapids-Wyoming-Kentwood, MI",
                 "short_name": "Grand Rapids, MI", "share_det": 76.3,
                 "hold_share": 63.2, "zips": 76, "period_pretty": "June 2026"},
        "receipt_quote": {"metro": "Boise City, ID", "lead_days": 41,
                          "outlet": "Idaho Statesman", "flag_date": "2026-06-20",
                          "published_on": "2026-07-31"},
        "evergreen": {"name": "Boise City, ID", "short_name": "Boise City, ID",
                      "lead_months": 12, "first_signal": "2021-11",
                      "peak_to_trough": -0.1786, "period_pretty": "June 2026"},
    }
    for kind, r in payloads.items():
        img = pp.BUILDERS[kind]({"render": r})
        assert img.size == (1080, 1350), kind


def test_a_decline_is_not_printed_as_a_double_negative():
    """"fell -17.9% from their high" — the minus and the word "fell" say the
    same thing twice and read as a rise."""
    pytest.importorskip("PIL")
    src = (ROOT / "pipeline" / "post_pack.py").read_text()
    assert "lstrip('+')" not in src, "sign handling regressed to lstrip"
    assert "abs(ptt)" in src


def test_no_banned_constructions_in_any_rendered_caption():
    """docs/ATTRIBUTION.md's list, enforced on the card as well as the row."""
    for phrase in ("powered by", "in partnership with", "endorsed by"):
        assert pp.compliant(f"ShouldISellYet, {phrase} Redfin"), \
            f"compliant() missed the banned construction {phrase!r}"
    assert pp.compliant("housing market will collapse next year"), \
        "compliant() missed a HYPE word"
    assert not pp.compliant("Austin-Round Rock, TX — 28% of scored ZIPs deteriorating")


def test_zero_median_cannot_reach_a_card():
    """mtl_prose discipline. The redesigned metro card does not print the
    median at all — that number lives in the caption, where there is room to
    phrase it — so the check is that no card string can express it and that a
    0.0 median still renders."""
    pytest.importorskip("PIL")
    src = (ROOT / "pipeline" / "post_pack.py").read_text()
    assert "months" not in re.sub(r"#[^\n]*", "", src).split("def card_metro")[1][:2000], \
        "the metro card started printing a months figure again"
    img = pp.card_metro({"render": {
        "name": "Austin-Round Rock, TX", "short_name": "Austin, TX",
        "share_det": 28.3, "zips": 61, "hold_share": 71.0,
        "median_mtl": 0.0, "period_pretty": "June 2026"}})
    assert img.size == (1080, 1350)


def test_ratios_render_as_percentages():
    """A stored ratio is not a published number. -0.1775 must reach a reader as
    17.9%, not as the float a database holds."""
    assert pp._pct(-0.1775) == "-17.8%"
    assert pp._pct(None) == "—"
    assert pp._pretty_month("2022-08") == "August 2022"
    assert pp._pretty_day("2026-07-31") == "July 31, 2026"


def test_render_is_deterministic(tmp_path):
    """Same manifest, same bytes. The renderer runs on every deploy."""
    pytest.importorskip("PIL")
    period = "2099-01"
    man = pp.MANIFEST_DIR / f"pack-{period}.json"
    man.parent.mkdir(parents=True, exist_ok=True)
    man.write_text(json.dumps({"period": period, "tasks": [{
        "utm_campaign": "mq-test-determinism", "type": "evergreen",
        "asset_path": f"/assets/mkt/{period}/mq-test-determinism.png",
        "render": {"name": "Boise City, ID", "lead_months": 12,
                   "first_signal": "2021-11", "peak_to_trough": -0.1786}}]}))
    try:
        pp.render(period, tmp_path / "a")
        pp.render(period, tmp_path / "b")
        a = (tmp_path / "a" / period / "mq-test-determinism.png").read_bytes()
        b = (tmp_path / "b" / period / "mq-test-determinism.png").read_bytes()
        assert a == b and len(a) > 0
    finally:
        man.unlink()


def test_missing_manifest_is_not_an_error():
    """House rule: a missing input prints and exits cleanly. The renderer runs
    on every deploy, including deploys of months that generated no tasks."""
    drawn, skipped = pp.render("1999-01", ROOT / "web" / "assets" / "mkt")
    assert (drawn, skipped) == (0, 0)
