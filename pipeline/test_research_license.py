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

Run: python3 -m pytest pipeline/test_research_license.py -q
"""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

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

# The two restrictions that ARE the narrowing. Losing either one gives the
# grant back without anyone editing the word "commercially".
RESTRICTIONS = ("dataset", "competing")

GENERATORS = (
    ROOT / "pipeline" / "build_research.py",
    ROOT / "pipeline" / "build_pages.py",
    ROOT / "pipeline" / "growth_digest.py",
)
HAND_MAINTAINED = (WEB / "press.html", WEB / "admin.html")


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


def _license_files():
    files = sorted(RESEARCH.glob("*/LICENSE.txt"))
    assert files, ("no release LICENSE.txt found — run pipeline/build_research.py "
                   "first; web/research/ is generated and gitignored")
    return files


def test_every_shipped_licence_withholds_dataset_and_competing_use():
    for path in _license_files():
        text = path.read_text(encoding="utf-8")
        for phrase in WITHDRAWN:
            assert phrase not in text, f"{path} still grants {phrase!r}"
        for word in RESTRICTIONS:
            assert word in text, (
                f"{path} no longer withholds {word!r} use — that restriction "
                "IS the narrowing")
        assert "no third-party vendor data" in text
        assert "shouldisellyet.com" in text


def test_every_research_page_states_the_same_terms():
    pages = sorted(RESEARCH.rglob("index.html")) + [RESEARCH / "methodology.html"]
    for path in pages:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for phrase in WITHDRAWN:
            assert phrase not in text, (
                f"{path.relative_to(WEB)} still shows the withdrawn grant "
                f"({phrase!r}) while LICENSE.txt says something narrower")


def test_llms_txt_does_not_hand_answer_engines_the_old_grant():
    # robots.txt Allows GPTBot/ClaudeBot/PerplexityBot/CCBot, so this file is
    # read by the machines most able to act on a redistribution grant.
    path = WEB / "llms.txt"
    if not path.exists():
        return  # generated by build_pages.py; the generator test covers source
    text = path.read_text(encoding="utf-8")
    for phrase in WITHDRAWN:
        assert phrase not in text, f"llms.txt still states {phrase!r}"
    assert "not permitted" in text


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


def test_licence_describes_what_the_csvs_actually_contain():
    csvs = sorted(RESEARCH.glob("*/*.csv"))
    assert csvs, "no release CSVs found — run pipeline/build_research.py first"
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

    for path in _license_files():
        text = path.read_text(encoding="utf-8")
        if ships_per_zip_levels:
            assert "individual ZIP markets whose" in text, (
                f"{path} enumerates only aggregates, but the folder ships "
                "per-ZIP verdict readings. The licence must describe them or "
                "they must stop shipping.")
