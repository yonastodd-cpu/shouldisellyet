"""Tests for the alert engine diff/render logic. Run: pytest -q"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from notify_changes import diff_verdicts, load_dir, render_email


def test_diff_only_reports_changes():
    old = {"20874": "green", "20906": "yellow", "78701": "red"}
    new = {"20874": "green", "20906": "red", "78701": "yellow", "99999": "green"}
    d = diff_verdicts(old, new)
    assert d == {"20906": ("yellow", "red"), "78701": ("red", "yellow")}
    # brand-new ZIP (no baseline) must not alert


def test_load_dir(tmp_path):
    (tmp_path / "MD.json").write_text(json.dumps(
        {"20874": {"l": "green", "s": 0}, "20906": {"l": "yellow", "s": 3}}))
    (tmp_path / "bad.json").write_text("not json")
    assert load_dir(str(tmp_path)) == {"20874": "green", "20906": "yellow"}


def test_render_email_deterioration():
    subject, html = render_email("20906", "yellow", "red")
    assert "ACT" in subject and "20906" in subject
    assert "deteriorated" in html
    assert "shouldisellyet.com/?zip=20906" in html
    assert "Redfin" in html          # attribution required
    assert "Not financial advice" in html


def test_render_email_improvement():
    subject, html = render_email("20874", "yellow", "green")
    assert "HOLD" in subject
    assert "improved" in html
