"""Nothing we publish may call the market feed public. It is licensed.

The copy sweep of 2026-08-22 fixed the site and missed the documentation,
because the sweep was partitioned over web/*.html and pipeline/build_*.py and
the repo's own README was in neither. That README is the front page of a PUBLIC
repository and it said readings were "computed from public housing-market data"
— the same provenance misstatement, on the most-read page we have.

The crawl gate cannot catch this: it reads rendered pages from a served site,
and none of these files is served. So it is asserted here instead.

Genuinely public inputs (ACS, FHFA, GeoNames, Census) are public domain and are
NOT what this test is about — the exemptions below are deliberate.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Describing the feed as public. Not "public domain", not a negation.
CLAIM = re.compile(
    r"public\s+(?:housing-market\s+data|housing\s+data|market\s+data|data|signals)\b",
    re.I)
NEGATED = re.compile(
    r"\b(?:not|never|no longer|rather than|isn't|is not|was not|instead of|"
    r"used to|previously|stopped|domain)\b[^.;]{0,70}$", re.I)

DOCS = [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md"))


def _offenders(path):
    text = path.read_text(encoding="utf-8")
    out = []
    for m in CLAIM.finditer(text):
        before = text[max(0, m.start() - 90):m.start()]
        if NEGATED.search(before):
            continue                      # "not public data", "public domain"
        if "public domain" in text[m.start():m.start() + 40].lower():
            continue
        line = text[:m.start()].count("\n") + 1
        out.append(f"{path.name}:{line}: {m.group(0)}")
    return out


def test_no_document_calls_the_licensed_feed_public():
    bad = [o for p in DOCS if p.exists() for o in _offenders(p)]
    assert not bad, "the market feed is licensed, not public:\n  " + "\n  ".join(bad)


def test_the_readme_front_matter_is_accurate():
    """The first paragraph of a public repo is read more than any page we ship."""
    head = (ROOT / "README.md").read_text(encoding="utf-8")[:600]
    assert "licensed market statistics" in head
    assert not CLAIM.search(head), "README front matter misstates provenance"
    assert "traffic-light verdict" not in head, "the output is a reading, not a verdict"
