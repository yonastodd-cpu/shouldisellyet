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


def test_templates_carry_no_literal_numbers():
    """Every figure arrives from the manifest. A numeral in a template is a
    number that cannot be refreshed and will eventually be wrong."""
    offenders = {k: v for k, v in pp.TEMPLATES.items() if re.search(r"\d", v)}
    assert not offenders, f"hardcoded digits in card templates: {offenders}"


def test_no_banned_constructions_in_any_rendered_caption():
    """docs/ATTRIBUTION.md's list, enforced on the card as well as the row."""
    for phrase in ("powered by", "in partnership with", "endorsed by"):
        assert pp.compliant(f"ShouldISellYet, {phrase} Redfin"), \
            f"compliant() missed the banned construction {phrase!r}"
    assert pp.compliant("housing market will collapse next year"), \
        "compliant() missed a HYPE word"
    assert not pp.compliant("Austin-Round Rock, TX — 28% of scored ZIPs deteriorating")


def test_zero_median_never_renders_zero_months():
    """mtl_prose discipline: a 0.0 median is 'already at its danger line'.
    These strings get pasted into press emails."""
    head, sub, body = pp.card_metro({"render": {
        "name": "Austin-Round Rock, TX", "share_det": 28.3, "zips": 61,
        "hold_share": 71.0, "median_mtl": 0.0}})
    joined = " ".join([head, sub, body])
    assert not re.search(r"\b0(\.0)? months?\b", joined), joined
    assert "danger line" in joined
    assert not pp.compliant(joined)


def test_ratios_render_as_percentages():
    """A stored ratio is not a published number. -0.1775 must reach the card
    as -17.8%, or the card has published nothing a reader can use."""
    head, sub, body = pp.card_case({"render": {
        "name": "Cape Coral-Fort Myers, FL", "lead_months": 10,
        "first_signal": "2022-08", "peak_to_trough": -0.1775}})
    assert "-17.8%" in body, body
    assert "-0.1775" not in body
    assert "August 2022" in body, "ISO dates are for databases, not cards"


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
