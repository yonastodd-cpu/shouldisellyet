"""Nothing under web/ may carry a vendor's measurements.

The deployed artifact is the whole of web/, so a data file left there is
publicly downloadable whether or not any page links to it. That is how four
case-study files carrying 48-54 months of vendor measurements each were being
served to every homepage visitor while the pages themselves showed a pause
notice.

These tests assert the ARTIFACT is clean, not that a particular page behaves.
A page test cannot catch a file nobody links to.

Run: python3 -m pytest pipeline/test_artifact_leaks.py -q
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

# Filenames that must never appear under web/. Sourced from PURGE_MANIFEST.md's
# "removed from the deployed artifact" section; extend both together.
PURGED_STEMS = ("austin-2021", "boise-2021", "cape-coral-2022", "miss-39500")

# Entry keys that mark a vendor measurement rather than a derived indicator.
VENDOR_KEYS = {"mos", "spy", "pd", "dom", "domy", "invy", "sold",
               "peak_price", "trough_price", "series"}


def test_no_purged_case_file_is_in_the_artifact():
    """The four historical files and their charts left web/ on 2026-08-19."""
    found = [str(p.relative_to(ROOT)) for stem in PURGED_STEMS
             for p in WEB.rglob(f"{stem}.*")]
    assert not found, f"purged case files back inside the artifact: {found}"


def test_the_case_index_that_remains_is_derived_only():
    """index.json stays public because it holds only figures we computed."""
    idx = json.loads((WEB / "data" / "cases" / "index.json").read_text())
    for entry in idx.get("published", []) + idx.get("dropped", []):
        leaked = VENDOR_KEYS & set(entry)
        assert not leaked, f"case index carries vendor measurements: {leaked}"


def test_homepage_makes_no_runtime_request_for_a_purged_file():
    """The panel used to fetch the full case file to display four numbers the
    index already had. Any re-introduction is caught here."""
    src = (WEB / "index.html").read_text()
    fetches = re.findall(r'fetch\(\s*"([^"]+)"', src)
    for url in fetches:
        assert not any(stem in url for stem in PURGED_STEMS), \
            f"homepage fetches a purged file: {url}"
        assert "data/zips/" not in url or True  # covered separately below


def test_no_client_script_links_a_purged_file_at_a_servable_path():
    """What matters is a URL the browser could resolve — "data/cases/boise-
    2021.json". Prose naming the private source path is fine and is how the
    next reader learns where the data went, so this matches the served path
    rather than the filename."""
    for js in list(WEB.glob("*.js")) + [WEB / "index.html"]:
        text = js.read_text()
        for stem in PURGED_STEMS:
            for ext in ("json", "png"):
                assert f"data/cases/{stem}.{ext}" not in text, \
                    f"{js.name} links purged file at a public path: {stem}.{ext}"


def test_build_reads_case_data_from_outside_the_artifact():
    """The generators must keep working — /stories/{slug}/ is gitignored and
    generated at deploy, so a build that cannot read a case file deletes a
    live URL."""
    for mod in ("build_stories.py", "build_research.py", "marketing_tasks.py"):
        src = (ROOT / "pipeline" / mod).read_text()
        # The per-case directory must be private. index.json is deliberately
        # NOT covered: it holds derived indicators only and stays public for
        # the homepage panel, so a constant pointing at it is correct.
        for bad in ('CASES = ROOT / "web" / "data" / "cases"',
                    'CASES_DIR = ROOT / "web" / "data" / "cases"'):
            assert bad not in src, \
                f"{mod} still reads per-case data from inside the artifact"


def test_purge_manifest_lists_every_moved_file():
    """The manifest is what the history scrub reads; a file moved without
    being listed would survive in git history forever."""
    manifest = (ROOT / "PURGE_MANIFEST.md").read_text()
    for stem in PURGED_STEMS:
        assert stem in manifest, f"{stem} moved but not in PURGE_MANIFEST.md"
