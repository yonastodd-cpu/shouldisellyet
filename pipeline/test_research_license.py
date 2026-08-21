"""The research-file grant must say one thing, everywhere, and say it truly.

Prompt 4 narrowed the licence that ships with the monthly research releases:
the old text granted republication "including commercially" with citation, and
the new text grants attribution-only use while withholding dataset
redistribution and competing products.

Two ways that narrowing silently fails, both of which happened here:

1. THE GRANT LIVES IN SEVEN PLACES, NOT ONE. LICENSE.txt is generated, but so
   is the methodology page's "Use and citation" section, the footer on every
   research page, the note under the download buttons, and two passages in
   llms.txt — which robots.txt explicitly invites GPTBot, ClaudeBot and
   PerplexityBot to read. press.html is hand-maintained and no generator
   touches it. Two more are OUTBOUND: the monthly journalist pitch in
   growth_digest.py and the one-click pitch in admin.html, which a human copies
   into an email — a pitch that says "free with citation" makes the old grant
   directly to the recipient no matter what LICENSE.txt says. Narrowing some
   and not others publishes contradictory terms, and the broadest one wins the
   argument.

2. THE LICENCE CAN DESCRIBE A FOLDER THAT DOES NOT EXIST. The narrowed text
   enumerates what the files contain. zip-flips-{month}.csv is one row per ZIP
   carrying that ZIP's own before/after verdict — not a count, not a share.
   A licence whose self-description omits 2,403 rows of per-ZIP readings is
   inaccurate in the direction that matters, so test_licence_describes_what_
   the_csvs_actually_contain reads the real CSV headers and fails if a class of
   content ships that the licence does not name.

THE FIRST VERSION OF THIS FILE WAS BROKEN AND CI CAUGHT IT. Three tests read
web/research/ — which is gitignored and generated — so they passed locally only
because a build had just run. CI runs pytest BEFORE build_research.py, so the
tree was empty: two tests failed outright, and the third "passed" because its
glob returned nothing and the loop body never executed. A test that cannot fail
is worse than no test.

So nothing here reads the built tree. The licence and CSV assertions build
their own output from the committed pipeline/research/*.json via write_csvs()
(offline, no PIL, no network), and everything else asserts against generator
source. Both are the durable artifact anyway: web/research/ is rebuilt from
scratch on every deploy, so the generator is what actually ships.

Run: python3 -m pytest pipeline/test_research_license.py -q
"""

import csv
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import build_research as BR

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
RESEARCH = WEB / "research"

# The withdrawn grant, in every form it was ever written in. Any reappearance
# in a generator, a served file, or an outbound template is a regression.
WITHDRAWN = (
    "including commercially",
    "Free to use, republish, and chart",
    "Free to use with citation",
    "Free with citation",
    "free to use with citation",
    "free with citation",
    "are free to reuse",
)

# THE RESTRICTION, VERBATIM — not keywords. An earlier version of this file
# asserted merely that the words "dataset" and "competing" appeared somewhere
# in the licence, and a mutation test proved it would happily accept
# "...or use of them to build a competing data product or service, is fine by
# us." Presence of a word is not presence of a restriction, so these match the
# whole clause, whitespace-normalised so re-wrapping a line is not a failure.
LICENCE_RESTRICTION = ("Redistribution of these files as a dataset, or use of "
                       "them to build a competing data product or service, is "
                       "not permitted.")

# The same limit as each generated surface words it. Every one is load-bearing:
# drop any single entry and that surface silently reverts to an open grant.
SURFACE_RESTRICTIONS = {
    "build_research.py": [
        LICENCE_RESTRICTION,                                    # LICENSE.txt
        ("Redistributing the files as a dataset, or using them to build a "
         "competing data product or service, is not permitted"),  # methodology
        ("Redistributing them as a dataset, or using them to build a competing "
         "data product or service, is not permitted"),            # download note
        "Not for dataset redistribution or competing products",   # page footer
    ],
    "build_pages.py": [
        ("redistributing them as a dataset, or using them to build a competing "
         "data product or service, is not permitted"),            # llms.txt cite
        "use with attribution; no dataset redistribution",         # llms.txt pages
    ],
}


def _flat(s):
    """Whitespace-normalised, so a re-wrapped line is not a false failure."""
    return " ".join(s.split())

GENERATORS = (
    ROOT / "pipeline" / "build_research.py",
    ROOT / "pipeline" / "build_pages.py",
    ROOT / "pipeline" / "growth_digest.py",
)
HAND_MAINTAINED = (WEB / "press.html", WEB / "admin.html")


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """Real release output, built here from committed data.

    write_csvs() writes the four CSVs AND LICENSE.txt, and needs neither
    Pillow nor the network — so this runs identically on a laptop and on a
    cold CI checkout, which is the whole point.
    """
    out = tmp_path_factory.mktemp("research")
    series = BR.national_series(BR.load_history())
    reports = sorted(BR.RESEARCH_DIR.glob("research-*.json"))
    assert reports, "no committed research reports to build from"
    for rp in reports:
        rep = json.loads(rp.read_text(encoding="utf-8"))
        d = out / rep["month"]
        d.mkdir()
        BR.write_csvs(rep, [(m, v) for m, v in series if m <= rep["month"]], d)
    return out


def _texts(paths):
    return [(p, p.read_text(encoding="utf-8")) for p in paths if p.exists()]


def test_no_generator_still_stamps_the_withdrawn_grant():
    for path, text in _texts(GENERATORS):
        for phrase in WITHDRAWN:
            assert phrase not in text, (
                f"{path.name} still stamps the withdrawn grant: {phrase!r}. "
                "Narrowing LICENSE.txt alone leaves this one publishing the "
                "old terms on the next build.")


def test_hand_maintained_pages_carry_the_narrowed_grant():
    # No generator writes these, so a pipeline change cannot fix them and they
    # are the surfaces most likely to be left behind.
    for path, text in _texts(HAND_MAINTAINED):
        for phrase in WITHDRAWN:
            assert phrase not in text, f"{path.name} still states {phrase!r}"


def test_outbound_pitches_do_not_grant_more_than_the_licence():
    # A pitch email is a grant to its recipient. growth_digest builds the
    # monthly journalist mail; admin.html builds the one-click version.
    for path in (ROOT / "pipeline" / "growth_digest.py", WEB / "admin.html"):
        text = path.read_text(encoding="utf-8")
        assert "not permitted" in text or "not for dataset" in text.lower(), (
            f"{path.name} pitches the CSVs without naming the restriction — "
            "the recipient is told they are free to use with citation.")


def _license_files(built):
    files = sorted(built.glob("*/LICENSE.txt"))
    assert files, "write_csvs() stopped writing LICENSE.txt"
    return files


def test_every_shipped_licence_withholds_dataset_and_competing_use(built):
    for path in _license_files(built):
        text = path.read_text(encoding="utf-8")
        for phrase in WITHDRAWN:
            assert phrase not in text, f"{path.name} still grants {phrase!r}"
        assert _flat(LICENCE_RESTRICTION) in _flat(text), (
            f"{path.name} no longer withholds dataset redistribution and "
            "competing products in full — that clause IS the narrowing, and "
            "weakening its wording gives the grant back")
        assert "no third-party vendor data" in text
        assert "shouldisellyet.com" in text


def test_every_generated_surface_states_the_restriction_in_full():
    """Absence of the old wording is not presence of the new.

    The footer, the methodology section, the download note and both llms.txt
    passages are generator string literals, so scanning source is what makes
    this run on a cold checkout — and matching the whole clause is what makes
    it able to fail.
    """
    for name, clauses in SURFACE_RESTRICTIONS.items():
        text = _flat((ROOT / "pipeline" / name).read_text(encoding="utf-8"))
        for clause in clauses:
            assert _flat(clause) in text, (
                f"{name} no longer states: {clause!r} — that surface has "
                "reverted to granting reuse without limit")


# The columns the narrowed licence enumerates, and the column classes it does
# NOT cover. A new export column that is neither is a licence that has stopped
# describing its own folder.
AGGREGATE = {"state", "cbsa", "metro", "month", "series", "scored_zips",
             "hold", "watch", "act", "strong", "warning_share_pct",
             "delta_pts", "wsi_pct"}
PER_ZIP_LEVEL = {"from_verdict", "to_verdict"}
IDENTIFIER = {"zip", "city"}
VENDOR = {"median_price", "price", "dom", "days_on_market", "inventory",
          "price_cut_share", "ppsf", "price_per_sqft", "months_supply"}


def test_research_exports_are_aggregates_only(built):
    """RELEASE GATE. No per-ZIP rows, no vendor-metric columns.

    zip-flips-{month}.csv named every market that crossed into warning and
    what it was rated — 2,135 rows in June, 2,403 in July — under a licence
    granting reuse. Withdrawn 2026-08-21 for three reasons: it distributed the
    core product output in bulk while the site serves readings a page at a
    time; it published ratings for ZIP codes whose own pages withhold them
    (1,946 of the 2,403 July rows); and counsel's review of the grant is
    pending, with the aggregates the defensible subset.

    An export may describe the SET — counts, shares, changes. It may not
    enumerate its members.
    """
    csvs = sorted(built.glob("*/*.csv"))
    assert csvs, "write_csvs() stopped writing release CSVs"
    for path in csvs:
        with path.open(encoding="utf-8") as f:
            rows = list(csv.reader(f))
        header = rows[0]
        assert "zip" not in [h.lower() for h in header], (
            f"{path.name} has a zip column — an export that names individual "
            "markets is a directory of them, whatever else is in the row")
        for col in header:
            assert col not in VENDOR, (
                f"{path.name} ships {col!r}, a third-party vendor measurement")
        # A five-digit value anywhere is the same thing by another route —
        # except a CBSA code, which is also five digits and identifies a metro
        # area, not a ZIP. Skipping that column by name rather than loosening
        # the pattern, so a stray ZIP elsewhere still fails.
        cbsa_at = [i for i, h in enumerate(header) if h.lower() == "cbsa"]
        for row in rows[1:]:
            for i, cell in enumerate(row):
                if i in cbsa_at:
                    continue
                assert not re.fullmatch(r"\d{5}", cell.strip()), (
                    f"{path.name} contains a bare ZIP code ({cell}) outside a "
                    "zip column")


def test_no_release_page_names_a_zip_and_its_rating(built):
    """The same withdrawal, in page clothing. The release page rendered 55
    per-ZIP rating rows — 47 of them for ZIPs the site was declining to rate —
    so removing only the file would have left the contents on the page."""
    pages = sorted((ROOT / "web" / "research").glob("*/index.html"))
    if not pages:
        pytest.skip("research not built")
    for f in pages:
        html = f.read_text(encoding="utf-8")
        named = set(re.findall(r"/zip/(\d{5})/", html))
        assert not named, (
            f"{f.parent.name} names {len(named)} ZIP(s) on the release page: "
            f"{sorted(named)[:5]}")


def test_licence_describes_what_the_csvs_actually_contain(built):
    csvs = sorted(built.glob("*/*.csv"))
    assert csvs, "write_csvs() stopped writing release CSVs"
    ships_per_zip_levels = False
    for path in csvs:
        with path.open(encoding="utf-8") as f:
            header = next(csv.reader(f))
        for col in header:
            assert col not in VENDOR, (
                f"{path.name} ships {col!r}, a third-party vendor measurement, "
                "while every LICENSE.txt states the files contain no "
                "third-party vendor data")
            assert col in AGGREGATE | PER_ZIP_LEVEL | IDENTIFIER, (
                f"{path.name} ships an unclassified column {col!r} — decide "
                "whether it is an aggregate, a per-ZIP reading, or a vendor "
                "metric, and make LICENSE.txt say so before publishing it")
            if col in PER_ZIP_LEVEL:
                ships_per_zip_levels = True

    for path in _license_files(built):
        text = path.read_text(encoding="utf-8")
        if ships_per_zip_levels:
            assert "individual ZIP markets whose" in text, (
                f"{path} enumerates only aggregates, but the folder ships "
                "per-ZIP verdict readings. The licence must describe them or "
                "they must stop shipping.")
        else:
            # They stopped shipping. The licence must stop claiming them too,
            # or it describes a folder that no longer exists — the same defect
            # in the other direction.
            assert "individual ZIP markets whose" not in text, (
                f"{path} still describes a per-ZIP list that is no longer "
                "published")
