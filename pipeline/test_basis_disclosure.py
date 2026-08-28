"""The prior vendor's name comes out; the disclosure that the basis changed stays.

Both directions matter, and they pull against each other. Strip the name and it
is easy to strip the sentence with it — at which point the site silently stops
telling readers that everything before August 2026 was measured a different way.
That would be a worse outcome than the credit line, not a better one.

So: the name is permitted NOWHERE in rendered output except the methodology
changelog (web/research/methodology.html's versioned table) — zero other
exceptions — AND the methodology page must still say the basis changed, in
prose, without naming or linking.

The sweep is recursive on purpose: the original globs stopped two levels deep,
which is how the archived research releases (web/research/2026-06/,
web/research/2026-07/) shipped the name for two months without a red gate.
"""
import glob
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"Redfin", re.I)

SURFACES = ["web/**/*.html", "web/**/*.js", "web/**/*.txt", "web/**/*.json",
            "web/**/*.webmanifest", "web/**/*.xml",
            "pipeline/build_*.py", "supabase/functions/**/*.ts"]

# The one place policy permits the name: the versioned methodology changelog.
# (It currently uses the unnamed form there too; this is permission, not
# presence.) Nothing else — not the site methodology page, not archived
# research releases, not paid surfaces.
PERMITTED = {"web/research/methodology.html"}


def _visible(path):
    """Source with comments stripped — a comment is not a reachable surface."""
    t = Path(path).read_text(encoding="utf-8", errors="replace")
    t = re.sub(r"<!--.*?-->", "", t, flags=re.S)          # html
    t = re.sub(r'"""[\s\S]*?"""', "", t)                   # python docstrings
    t = re.sub(r"^\s*#.*$", "", t, flags=re.M)             # python line comments
    t = re.sub(r"/\*[\s\S]*?\*/", "", t)                   # block comments
    t = re.sub(r"//[^\n]*", "", t)                         # js/ts line comments
    return t


def test_the_vendor_name_appears_on_no_reachable_surface():
    offenders = []
    for pat in SURFACES:
        for f in glob.glob(str(ROOT / pat), recursive=True):
            rel = str(Path(f).relative_to(ROOT))
            if rel in PERMITTED:
                continue                                   # the changelog, and only it
            if rel == "web/methodology.html":
                continue                                   # checked below, must be clean too
            hits = NAME.findall(_visible(f))
            if hits:
                offenders.append(f"{rel}: {len(hits)}")
    assert not offenders, (
        "the prior vendor is named outside the methodology changelog:\n  "
        + "\n  ".join(offenders))


def test_the_methodology_page_does_not_name_or_link_it_either():
    t = _visible(ROOT / "web" / "methodology.html")
    assert not NAME.search(t), "methodology names the prior vendor"
    assert "redfin.com" not in t.lower(), "methodology links to the prior vendor"


def test_but_the_basis_change_is_still_disclosed():
    """The permitted reference. Removing the mark must not remove the fact."""
    t = (ROOT / "web" / "methodology.html").read_text(encoding="utf-8")
    assert "prior data vendor" in t, (
        "the methodology page no longer says the readings changed basis — "
        "stripping the credit must not strip the disclosure with it")
    assert "sold-home statistics" in t, (
        "the disclosure no longer says WHAT the earlier basis was")
    assert "August 2026" in t, "the disclosure gives no date for the change"


def test_the_disclosure_says_the_old_basis_is_no_longer_published():
    t = (ROOT / "web" / "methodology.html").read_text(encoding="utf-8")
    assert re.search(r"no longer published|are no longer|is no longer", t), (
        "a reader is told the basis changed but not that the old figures are gone")
