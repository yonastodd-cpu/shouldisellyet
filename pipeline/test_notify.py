"""Tests for the alert engine diff/render logic. Run: pytest -q"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from notify_changes import diff_verdicts, load_dir, render_email


def L(level, basis=""):
    """A load_dir value: (level, basis). Legacy readings carry no basis."""
    return (level, basis)


def test_diff_only_reports_changes():
    old = {"20874": L("green"), "20906": L("yellow"), "78701": L("red")}
    new = {"20874": L("green"), "20906": L("red"), "78701": L("yellow"),
           "99999": L("green")}
    d = diff_verdicts(old, new)
    assert d == {"20906": ("yellow", "red"), "78701": ("red", "yellow")}
    # brand-new ZIP (no baseline) must not alert


def test_diff_suppresses_a_basis_change(tmp_path):
    """The migration re-scores released ZIPs on active-listing data. A level
    that moves for that reason is a SOURCE change, and mailing somebody
    "your market moved to ACT" when what moved was our data vendor is the
    worst email this site could send — in a burst, on tranche day."""
    old = {"20874": L("green"), "20906": L("yellow")}
    new = {"20874": L("red", "active listings"),      # re-scored: suppressed
           "20906": L("red")}                         # same basis: alerts
    assert diff_verdicts(old, new) == {"20906": ("yellow", "red")}


def test_alerts_resume_once_both_sides_are_the_new_basis():
    """No global switch to remember to turn back on: the second run on the
    new basis compares like with like and behaves normally again."""
    old = {"20874": L("green", "active listings")}
    new = {"20874": L("red", "active listings")}
    assert diff_verdicts(old, new) == {"20874": ("green", "red")}


def test_load_dir(tmp_path):
    (tmp_path / "MD.json").write_text(json.dumps(
        {"20874": {"l": "green", "s": 0},
         "20906": {"l": "yellow", "s": 3, "b": "active listings"}}))
    (tmp_path / "bad.json").write_text("not json")
    assert load_dir(str(tmp_path)) == {"20874": ("green", ""),
                                       "20906": ("yellow", "active listings")}


def test_render_email_deterioration():
    subject, html = render_email("20906", "yellow", "red", address="1234 Main St, Silver Spring, MD", token="00000000-0000-0000-0000-000000000000")
    assert "ACT" in subject
    assert "deteriorated" in html and "1234 Main St" in html
    assert "my-report.html?token=" in html
    assert "Redfin" in html          # attribution required
    assert "Not financial advice" in html


def test_render_email_improvement():
    subject, html = render_email("20874", "yellow", "green")
    assert "HOLD" in subject
    assert "improved" in html
