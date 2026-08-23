"""Committed release reports must not name individual ZIPs and their ratings.

The release page says, in terms: "We do not publish the list. Naming individual
markets and their ratings is the same distribution the CSV was withdrawn for."
That was true of the rendered page and false of the JSON behind it — which is
committed to a PUBLIC repository and was fetchable from raw.githubusercontent.com,
2,403 named ZIPs for July 2026 alone. The withdrawal of 2026-08-21 took the CSV
off the website and left more of the same data reachable from the repo.

No gate could have caught this. The crawl gate reads rendered pages from a served
site; these files are neither rendered nor served.
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESEARCH = ROOT / "pipeline" / "research"
ZIP_RE = re.compile(r"^\d{5}$")


def _release_reports():
    return sorted(RESEARCH.glob("research-*.json"))


def test_release_reports_exist_to_be_checked():
    assert _release_reports(), "no release reports found — this test would pass vacuously"


def test_no_release_report_names_zips_with_ratings():
    bad = []
    for p in _release_reports():
        d = json.loads(p.read_text(encoding="utf-8"))
        for key in ("flips_to_warning",):
            entries = d.get(key) or []
            named = [e for e in entries if isinstance(e, dict) and ZIP_RE.match(str(e.get("zip", "")))]
            if named:
                bad.append(f"{p.name}:{key} names {len(named)} ZIPs")
    assert not bad, (
        "release reports name individual markets and their ratings while the "
        "release page says they are not published:\n  " + "\n  ".join(bad))


def test_the_count_survives_so_pages_do_not_understate():
    """Stripping the list must not silently turn 2,403 into 0 on the page."""
    import sys
    sys.path.insert(0, str(ROOT / "pipeline"))
    import research as RS
    for p in _release_reports():
        d = json.loads(p.read_text(encoding="utf-8"))
        assert RS.flip_count(d) > 0, f"{p.name} lost its flip count"


def test_top_streaks_is_trimmed_to_what_is_actually_read():
    """Only [0] is ever consumed — by the spotlight card and the digest."""
    for p in _release_reports():
        d = json.loads(p.read_text(encoding="utf-8"))
        assert len(d.get("top_streaks") or []) <= 1, (
            f"{p.name} carries {len(d['top_streaks'])} named ZIPs; only the first is read")


def test_the_generator_does_not_reemit_them():
    src = (ROOT / "pipeline" / "research.py").read_text(encoding="utf-8")
    assert '"flips_to_warning": [],' in src, "the writer would repopulate the list next month"
    assert '"flips_to_warning_count": len(flips),' in src
    assert '"top_streaks": top_streaks[:1],' in src
