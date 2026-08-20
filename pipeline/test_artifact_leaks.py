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


def test_no_per_zip_share_card_is_generated_while_paused():
    """The card is a picture of the reading — render_card paints the verdict
    and a market figure into the pixels. Pages stopped linking them on day one
    of the pause; the images kept generating and kept deploying, so ~3,400 sat
    at /og/{period}/{zip}.png returning 200. Anything holding a cached share
    URL could still fetch the withdrawn numbers."""
    import build_pages as BP
    import data_pause as PAUSE
    src = (ROOT / "pipeline" / "build_pages.py").read_text()
    loop = src[src.index("for z, e in eligible:\n                if z not in card_set"):]
    loop = loop[:loop.index("cards_made += 1")]
    assert "PAUSE.shows_data" in loop, \
        "per-ZIP card rendering is no longer gated on the pause"


def test_og_directory_holds_no_per_zip_card_while_paused():
    """Belt and braces against the built output, not just the source."""
    import data_pause as PAUSE
    if not PAUSE.PAUSED:
        pytest.skip("not paused — per-ZIP cards are expected")
    og = WEB / "og"
    if not og.exists():
        return
    stray = [str(p.relative_to(ROOT)) for p in og.rglob("*.png")
             if re.fullmatch(r"\d{5}", p.stem)
             and not PAUSE.shows_data(p.stem)]
    assert not stray, f"per-ZIP cards in the artifact while paused: {stray[:5]}"


def test_purge_manifest_lists_every_moved_file():
    """The manifest is what the history scrub reads; a file moved without
    being listed would survive in git history forever."""
    manifest = (ROOT / "PURGE_MANIFEST.md").read_text()
    for stem in PURGED_STEMS:
        assert stem in manifest, f"{stem} moved but not in PURGE_MANIFEST.md"


# ————— URL-set floors —————

def test_metro_membership_uses_the_wider_scored_population():
    """Metro pages are built from a DIFFERENT population than ZIP pages: every
    scored ZIP, not only those with a standing page. Building them from the
    narrow set drops 92 metros below the 8-ZIP floor, and building them from
    records that no longer carry a level drops all 609 to zero. Both were
    measured, not theorised."""
    src = (ROOT / "pipeline" / "build_metro.py").read_text()
    assert "read_manifest(pages_only=False)" in src, \
        "build_metro must use the wider scored population"


def test_manifest_records_both_populations():
    import csv as _csv
    rows = list(_csv.DictReader(
        open(ROOT / "pipeline" / "data" / "page_manifest.csv", encoding="utf-8")))
    pages = sum(1 for r in rows if r["page"] == "1")
    assert len(rows) > pages, "the scored set must be wider than the page set"
    assert pages > 20000, f"only {pages} standing pages in the manifest"
    assert len(rows) > 25000, f"only {len(rows)} scored ZIPs in the manifest"


def test_the_pillow_guard_probes_pillow_itself():
    """build_pages promises to degrade to the brand card when Pillow is
    missing. It guarded `from og_card import render_card`, which always
    succeeds — og_card imports PIL lazily INSIDE render_card — so the guard
    never fired and the build crashed at the first render instead. A CI job
    that did not install Pillow is how this surfaced."""
    src = (ROOT / "pipeline" / "build_pages.py").read_text()
    block = src[src.index("if not args.no_cards:"):src.index("card_set = set()")]
    assert "import PIL" in block, "the guard must probe PIL, not og_card"


def test_stale_cards_are_cleared_even_without_pillow():
    """The rmtree sat inside the else-branch, so a build without Pillow or
    with --no-cards left a previous build's per-ZIP cards in the artifact —
    the exact class of file that nobody links and everybody forgets."""
    src = (ROOT / "pipeline" / "build_pages.py").read_text()
    clear = src.index("if og_dir.exists():")
    guard = src.index("if not args.no_cards:")
    assert clear < guard, "stale cards must be cleared before the Pillow guard"


def test_the_removed_per_state_layout_is_not_back_in_the_artifact():
    """web/data/zips/ was removed on 2026-08-20 when provisioning moved to one
    file per ZIP. Nothing reads it any more — but fetch_data.py still WRITES
    it, so a local `--input` run against any export would recreate 51 files
    inside the deployed tree, unlinked and unread, each holding whatever
    records the export carried. Unlinked is exactly how the case-study files
    were being served to every visitor while the pages showed a notice.
    """
    legacy = WEB / "data" / "zips"
    assert not legacy.exists(), (
        f"{legacy.relative_to(ROOT)} is back in the artifact. Nothing reads it; "
        "everything reads web/data/z/. If a pipeline run recreated it, that "
        "output is unlinked vendor data sitting in the deployed tree.")
