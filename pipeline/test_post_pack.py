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


def test_run_length_is_read_not_recomputed():
    """The card claimed "fifth month in a row" against a truth of three,
    because it counted every declining step in the twelve-month window instead
    of consecutive ones from the end. run_length has one home —
    research.detect_records() — and the card reads it."""
    pytest.importorskip("PIL")
    src = (ROOT / "pipeline" / "post_pack.py").read_text()
    body = src.split("def card_contrarian")[1].split("\ndef ")[0]
    assert "series[i][1] < series[i - 1][1]" not in body, "run length recomputed again"
    assert 'r.get("run_length")' in body

    # A rising series must never be described as falling.
    img = pp.card_contrarian({"render": {
        "wsi": 70.0, "run_length": 4, "run_direction": "up",
        "period_pretty": "June 2026",
        "series": [["2026-0%d" % i, 60 + i] for i in range(1, 7)]}})
    assert img.size == (1080, 1350)


def test_contrarian_falls_back_when_history_is_missing():
    """A line drawn from three points is not a trend. With too little history
    the card states the number plainly instead."""
    pytest.importorskip("PIL")
    img = pp.card_contrarian({"render": {"wsi": 62.2, "period_pretty": "June 2026",
                                         "series": []}})
    assert img.size == (1080, 1350)


def test_a_deploy_writes_redirects_for_every_period_not_just_the_current_one(tmp_path, monkeypatch):
    """web/go/ is gitignored and rebuilt from scratch on every deploy, and the
    period comes from web/data/meta.json. Writing only the current period meant
    that the first deploy after a data refresh shipped web/ with LAST month's
    redirects absent — and every link in every caption already posted that
    month started 404ing.

    Not hypothetical: the 2026-06 slate is scheduled to 2026-09-01, two data
    refreshes past the month its links belong to. Today there is one manifest,
    so only a synthetic second period exercises this.
    """
    mdir = tmp_path / "manifests"
    mdir.mkdir()
    web = tmp_path / "web"
    (web / "data").mkdir(parents=True)
    (web / "data" / "meta.json").write_text(json.dumps({"period": "2026-07"}))

    for per, tok in (("2026-06", "mq-old-post"), ("2026-07", "mq-new-post")):
        (mdir / f"pack-{per}.json").write_text(json.dumps({"period": per, "tasks": [{
            "utm_campaign": tok, "type": "post", "asset_path": None,
            "utm_url": f"https://shouldisellyet.com/research/{per}/?utm_campaign={tok}",
            "render": {}}]}))

    monkeypatch.setattr(pp, "MANIFEST_DIR", mdir)
    monkeypatch.setattr(pp, "ROOT", tmp_path)
    pp.main(["--render", "--period", "2026-07", "--out", str(tmp_path / "cards")])

    assert (web / "go" / "mq-new-post" / "index.html").exists(), "current period missing"
    assert (web / "go" / "mq-old-post" / "index.html").exists(), \
        "the previous period's short links vanished — every posted link would 404"
