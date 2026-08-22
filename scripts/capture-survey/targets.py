#!/usr/bin/env python3
"""The leaked-surface URL set, derived from the repository.

WHY DERIVED AND NOT TYPED. The set is 45,749 URLs at full scope. A hand-kept
list of that size is wrong the day after it is written, and the failure is
silent: a survey handed to counsel with 300 URLs missing looks exactly like a
survey with none missing. So the bulk comes from the two files that already
decide what this site publishes —

    pipeline/data/page_manifest.csv   the committed URL contract: zip,state,page
    pipeline/research/research-*.json which research months were released

— and only the six one-off pages are written out by hand, each tied to the
entry in pipeline/surfaces.py that identified it. A test asserts each of those
six still corresponds to something in the repository.

THE IMPORT RULE: nothing in scripts/capture-survey/ imports from pipeline/.
Reading a CSV by path is inert. Importing a pipeline module is not — the
sibling script scripts/audit-og.py does `from fetch_data import _ssl_context`,
which drags a network client into the import graph of a tool that had no
business holding one. This tree is required to reach no network without an
explicit flag, and the cheapest way to keep that true is to import nothing
that could. test_capture_survey.py enforces it.

WHAT IS NOT HERE, DELIBERATELY. The per-ZIP OG images (/og/{period}/{zip}.png)
and the bulk records (/data/z/{zip}.json) were leaking surfaces too, but the
memo's survey question is about PAGES a third party could have cached and a
platform could have previewed. Add them as a fourth tier if counsel asks; the
Target shape already carries them.
"""

import csv
import re
from pathlib import Path

SITE = "https://shouldisellyet.com"
ROOT = Path(__file__).resolve().parents[2]

PAGE_MANIFEST = ROOT / "pipeline" / "data" / "page_manifest.csv"
RESEARCH_DIR = ROOT / "pipeline" / "research"
PRIORITY_URLS = ROOT / "scripts" / "og-priority-urls.txt"
SITEMAP_DIR = ROOT / "web" / "sitemaps"

SCOPES = ("core", "priority", "all")
DEFAULT_SCOPE = "priority"


class Target:
    """One URL to survey, and everything a row about it has to state.

    `variants` matters more than it looks. Archives key captures on the exact
    request URL, so a capture of /s/77494 is invisible to an exact-match query
    for /s/77494/. The share stub is served from a directory but its own
    og:url is written without the trailing slash (build_pages.share_stub), so
    both spellings are in circulation and both get queried.
    """

    __slots__ = ("url", "variants", "surface", "memo_round", "windows", "tier", "note")

    def __init__(self, url, surface, memo_round, windows, tier, note="", variants=()):
        self.url = url
        self.variants = tuple(variants) or (url,)
        self.surface = surface
        self.memo_round = memo_round
        self.windows = tuple(windows)
        self.tier = tier
        self.note = note

    def __repr__(self):
        return f"<Target {self.url} r{self.memo_round} {self.tier}>"


def _slash_variants(url):
    """A directory URL and the same URL without its trailing slash."""
    return (url, url.rstrip("/")) if url.endswith("/") else (url,)


# ————— the six one-off pages —————
#
# Round numbers are the memo's. Round 1 is the 19–20 August sweep of the nine
# leaking surfaces; round 2 is the tenth surface plus the two committed static
# pages and the index above them, found on 20 August after ten had been
# closed; round 3 is the 21 August withdrawal of bulk distribution.
#
# Each entry names the pipeline/surfaces.py row that found it, because the
# provenance of "how do you know this leaked" is the first thing counsel will
# ask about a URL on this list.
SINGLETONS = (
    Target(f"{SITE}/", "homepage body + alt", 1,
           ("consumer_figures", "vendor_credits"), "core",
           "surfaces.py 'homepage body + alt' (runtime). A chip, an alt "
           "attribute, a caption and prose naming the vendor; an onerror hid "
           "the chip client-side, so the markup still reached anything "
           "reading HTML — which is exactly what an archive crawler does.",
           _slash_variants(f"{SITE}/")),
    Target(f"{SITE}/zip/", "markets index /zip/", 2,
           ("consumer_figures", "vendor_credits"), "core",
           "surfaces.py 'markets index /zip/'. No pause branch while the "
           "state hubs below it had one. Promised 'HOLD / WATCH / ACT "
           "verdicts for 22,874 U.S. ZIP codes' in the present tense.",
           _slash_variants(f"{SITE}/zip/")),
    Target(f"{SITE}/report.html", "sample report page", 2,
           ("consumer_figures", "vendor_credits"), "core",
           "surfaces.py 'sample report page'. Served a WATCH for a named ZIP "
           "with the full withdrawn dial set. Committed static page, so no "
           "pipeline change ever reached it."),
    Target(f"{SITE}/press.html", "press kit page", 2,
           ("consumer_figures", "vendor_credits"), "core",
           "surfaces.py 'press kit page'. Served the national verdict mix."),
    Target(f"{SITE}/llms.txt", "machine-readable crawler file", 2,
           ("consumer_figures",), "core",
           "Advertised /report.html to crawlers as showing 'a real ZIP' "
           "(ABSENCE_TEST_AUDIT.md). Generated at deploy time, so a checkout "
           "does not prove what any given day served — the archive does."),
)


def read_page_manifest(path=None):
    """[(zip, state, page)] from the committed URL contract."""
    out = []
    with Path(path or PAGE_MANIFEST).open(newline="") as f:
        for row in csv.DictReader(f):
            out.append((row["zip"], row["state"], int(row["page"])))
    return out


def states(manifest=None):
    """The distinct states with a hub page. 51 — the 50 plus DC."""
    return sorted({st for _, st, _ in (manifest or read_page_manifest()) if st})


def paged_zips(manifest=None):
    """The ZIPs that had a standing /zip/ page, and therefore a share stub."""
    return [z for z, _, page in (manifest or read_page_manifest()) if page == 1]


def research_months(directory=None):
    """Released research months, from the committed release JSONs."""
    d = Path(directory or RESEARCH_DIR)
    return sorted(m.group(1) for m in
                  (re.fullmatch(r"research-(\d{4}-\d{2})\.json", p.name)
                   for p in d.iterdir()) if m)


def priority_zips(path=None):
    """ZIPs already ranked for re-scrape, in their existing order.

    Reuses scripts/og-priority-urls.txt rather than re-deriving a ranking.
    That file carries its own warning — the order is a housing-supply proxy,
    not a traffic ranking, because Search Console had no impression data — and
    that caveat travels with the ZIPs into this survey's plan output.
    """
    p = Path(path or PRIORITY_URLS)
    seen, out = set(), []
    for line in p.read_text().splitlines():
        m = re.search(r"/(?:zip|s)/(\d{5})/?\s*$", line.strip())
        if m and not line.lstrip().startswith("#") and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def state_hub_targets(manifest=None):
    return [Target(f"{SITE}/zip/{st}/", "state hub rows", 1,
                   ("consumer_figures", "vendor_credits"), "core",
                   "surfaces.py 'state hub rows'. The hub built its rows in "
                   "main(), outside the branch that blanks a page.",
                   _slash_variants(f"{SITE}/zip/{st}/"))
            for st in states(manifest)]


def zip_targets(zips, tier):
    """A ZIP page and its share stub, which leaked differently.

    Both carried the rating in share metadata, but the stub had no pause check
    at ALL until 19 August, and its og:image:alt was missed by the first pass
    of its own fix. It is also the URL that exists only to be shared, which
    makes it the likeliest of the two to sit in a social cache.
    """
    out = []
    for z in zips:
        page = f"{SITE}/zip/{z}/"
        stub = f"{SITE}/s/{z}/"
        out.append(Target(page, "zip page head/meta/OG", 1,
                          ("consumer_figures", "vendor_credits"), tier,
                          "surfaces.py 'zip page head/meta/OG' and 'zip page "
                          "stamp/credit'.", _slash_variants(page)))
        out.append(Target(stub, "share stub /s/{zip}", 1,
                          ("consumer_figures",), tier,
                          "surfaces.py 'share stub /s/{zip}' and 'share stub "
                          "og:image:alt'. Exists only to be shared.",
                          _slash_variants(stub)))
    return out


def research_targets(months=None):
    """The withdrawn per-ZIP ratings files.

    These are the only targets whose exposure end is exact to the second, and
    the only ones that were published under a grant of reuse rather than
    merely displayed — which is why a cached copy of one is a different kind
    of exhibit from a cached page.
    """
    out = []
    for month in (months or research_months()):
        url = f"{SITE}/research/{month}/zip-flips-{month}.csv"
        out.append(Target(url, "research per-ZIP ratings file", 3,
                          ("research_zip_file",), "core",
                          f"REMEDIATION_DATES.md — withdrawn "
                          f"2026-08-21T03:22:25Z. Published under an "
                          f"attribution reuse grant, so a cached copy carries "
                          f"the grant with it."))
        out.append(Target(f"{SITE}/research/{month}/", "research release page", 3,
                          ("research_zip_file",), "core",
                          "The same rows were rendered on the release page as "
                          "HTML — 55 per-ZIP rating rows. Withdrawing the file "
                          "and leaving the page would have been a change of "
                          "format, not of practice.",
                          _slash_variants(f"{SITE}/research/{month}/")))
    return out


def build(scope=DEFAULT_SCOPE, manifest=None):
    """The target set for a scope. Order is stable: core, then ZIP pages."""
    if scope not in SCOPES:
        raise ValueError(f"scope must be one of {SCOPES}, got {scope!r}")
    rows = read_page_manifest() if manifest is None else manifest
    out = list(SINGLETONS) + state_hub_targets(rows) + research_targets()
    if scope == "priority":
        out += zip_targets(priority_zips(), "priority")
    elif scope == "all":
        out += zip_targets(paged_zips(rows), "bulk")
    return out


def sitemap_urls(directory=None):
    """Every <loc> in the built sitemaps, or () when there is no build.

    A completeness cross-check, not an authority. web/sitemaps/ is generated
    at deploy time and gitignored, so a checkout's copy is whatever the last
    local build produced — it may predate the pause and it may postdate a
    tranche release. Used only to show the operator how many published URLs
    fall outside the target set, so an unexpected number gets looked at.
    """
    d = Path(directory or SITEMAP_DIR)
    if not d.is_dir():
        return ()
    out = []
    for p in sorted(d.glob("*.xml")):
        out += re.findall(r"<loc>([^<]+)</loc>", p.read_text())
    return tuple(out)
