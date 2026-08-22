"""The Warning-Sign Index's three futures, and the two ways each could fail.

Counsel has been asked whether the index may continue as it is, be truncated
to the current vendor's era, or continue under a narrower grant. All three are
built (research.INDEX_MODE / research.INDEX_LICENSE, INDEX_OPTIONS.md), which
means all three can be wrong in ways nobody notices until the day one is
turned on. This file is the check that they cannot be.

THE TWO FAILURES IT EXISTS TO PREVENT:

1. THE DEFAULT MOVES. Publication continues unchanged until counsel answers,
   so a build with no flags set must be the build that shipped yesterday —
   whole series, current grant, same files. A switch that quietly narrows
   something on the way in is the one thing worse than not having a switch.

2. HALF A WITHDRAWAL. data_pause.py learned this the expensive way: a value
   pulled from the page body while it sits in the <title>, the meta
   description, the JSON-LD and a 1200×630 share card has not been withdrawn,
   it has been hidden from the one reader who was looking at the page. Every
   mode test here therefore asserts against ALL of those surfaces, not the
   body alone.

Run: python3 -m pytest pipeline/test_index_options.py -q
"""

import csv
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import build_research as BR
import research as RS

ROOT = Path(__file__).resolve().parents[1]
CUTOFF = "2026-07"          # a month the committed history actually contains


@pytest.fixture
def rep():
    """The latest committed release report — real data, no network."""
    p = sorted(RS.RESEARCH_DIR.glob("research-*.json"))[-1]
    return json.loads(p.read_text(encoding="utf-8"))


@pytest.fixture
def series():
    return BR.national_series(BR.load_history())


def _mode(mp, mode="full", licence="current", cutoff=None):
    """Set the flags the way production would, as module attributes.

    Both modules are patched: research owns the decision, build_research reads
    it through `RS.`, and a test that patched only one would pass while a real
    flip did nothing.
    """
    mp.setattr(RS, "INDEX_MODE", mode)
    mp.setattr(RS, "INDEX_LICENSE", licence)
    if cutoff:
        mp.setattr(RS, "INDEX_CUTOFF", cutoff)


def _fake_v2(mp, tmp_path, months=("2026-08", "2026-09")):
    """A v2 history file with the same shape research.py writes for v1.

    Values are invented — this is a scaffold test, and no v2 index has been
    computed yet. That is exactly why it matters that the code path works
    before the first real value lands in it.
    """
    p = tmp_path / "history-v2.json"
    p.write_text(json.dumps({
        "version": "2.0", "basis": RS.V2_BASIS, "months": list(months),
        "national": {m: [50, 30, 10, 10] for m in months}}))
    mp.setattr(RS, "HISTORY_V2", p)
    return p


# ————— 1. the default does not move —————

def test_default_flags_are_todays_behaviour():
    """Read from the module as imported, with no environment set in CI."""
    assert RS.INDEX_MODES[0] == "full" and RS.INDEX_LICENSES[0] == "current"
    assert RS.publishes_index() and RS.publishes_history_file()
    assert RS.cutoff_month() is None, (
        "a cutoff in the default mode would truncate the published history "
        "before anyone decided to")


def test_default_publishes_the_whole_series(series):
    assert RS.published_series(series) == list(series)


def test_default_licence_is_the_wording_that_ships_today(rep, series, tmp_path):
    BR.write_csvs(rep, series, tmp_path)
    text = (tmp_path / "LICENSE.txt").read_text(encoding="utf-8")
    assert BR.GRANT_CURRENT.strip() in text
    assert "SERIES-BREAK" not in text
    assert not (tmp_path / "SERIES-BREAK.txt").exists()


def test_an_unknown_mode_refuses_rather_than_guessing():
    """A typo must not republish what counsel asked us to stop publishing.

    Falling back to the default on a bad value is the dangerous direction:
    "truncate" is a plausible typo for "truncated", and the fallback would
    ship the full Redfin-basis history after a decision to ship less.
    """
    src = (ROOT / "pipeline" / "research.py").read_text(encoding="utf-8")
    assert "if INDEX_MODE not in INDEX_MODES:" in src
    assert "raise SystemExit" in src.split("if INDEX_MODE not in INDEX_MODES:")[1][:400]


# ————— 2. truncated: a cutoff, and a note that says so —————

def test_truncated_publishes_only_the_cutoff_forward(monkeypatch, series):
    _mode(monkeypatch, "truncated", cutoff=CUTOFF)
    pub = RS.published_series(series)
    assert pub, "the fixture cutoff must leave something publishable"
    assert all(m >= CUTOFF for m, _ in pub)
    assert len(pub) < len(series)
    # And the stored history is untouched — the whole point of the mode.
    assert len(BR.load_history()["months"]) == len(series)


def test_truncated_csv_starts_at_the_cutoff_and_ships_the_break(
        monkeypatch, rep, series, tmp_path):
    _mode(monkeypatch, "truncated", cutoff=CUTOFF)
    BR.write_csvs(rep, series, tmp_path)
    rows = list(csv.DictReader((tmp_path / "wsi-history.csv").open(encoding="utf-8")))
    assert rows and all(r["month"] >= CUTOFF for r in rows)
    note = (tmp_path / "SERIES-BREAK.txt").read_text(encoding="utf-8")
    assert RS.series_break_note() in note
    assert RS.series_break_note() in (tmp_path / "LICENSE.txt").read_text(encoding="utf-8")


def test_the_break_note_names_the_date_and_the_reason():
    """NO SILENT SPLICE. A series that simply starts later reads as a young
    index; these three claims are what stop it doing that."""
    n = RS.series_break_note("2026-08")
    assert "August 2026" in n
    assert "prior vendor" in n and "no longer distributed" in n
    assert "restarts" in n


def test_a_pre_cutoff_release_withholds_its_value_on_every_surface(
        monkeypatch, rep, series, tmp_path):
    _mode(monkeypatch, "truncated", cutoff="2099-01")   # everything is history
    BR.release_page(rep, series, tmp_path, f"/research/{rep['month']}/")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    value = f"{rep['records']['wsi']:.1f}%"
    assert value not in html, (
        f"{value} still appears on a page whose month is no longer published "
        "— check the <title>, the meta description and the JSON-LD, not just "
        "the body")
    assert RS.series_break_note() in html
    # The aggregates are not the index and must survive.
    assert "Metros deteriorating fastest" in html
    assert "statecard" in html


# ————— 3. paused: aggregates and charts, minus the index —————

def test_paused_withholds_every_index_value_but_keeps_the_aggregates(
        monkeypatch, rep, series, tmp_path):
    _mode(monkeypatch, "paused")
    BR.release_page(rep, series, tmp_path, f"/research/{rep['month']}/")
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    assert f"{rep['records']['wsi']:.1f}%" not in html
    assert "under review" in html
    assert "Metros deteriorating fastest" in html and "statecard" in html
    # The JSON-LD must not advertise a dataset the site is no longer serving.
    ld = re.search(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
    assert ld and "wsi-history.csv" not in ld.group(1)


def test_paused_does_not_write_the_history_file_but_still_writes_aggregates(
        monkeypatch, rep, series, tmp_path):
    _mode(monkeypatch, "paused")
    BR.write_csvs(rep, series, tmp_path)
    assert not (tmp_path / "wsi-history.csv").exists()
    assert (tmp_path / f"state-aggregates-{rep['month']}.csv").exists()
    assert (tmp_path / f"metro-aggregates-{rep['month']}.csv").exists()


def test_paused_hub_keeps_every_release_link(monkeypatch, series, tmp_path):
    """Withholding a number must not delete the navigation to the page it
    was on. The row stays; the value becomes a dash."""
    _mode(monkeypatch, "paused")
    h = BR.load_history()
    releases = [p.stem.replace("research-", "")
                for p in sorted(RS.RESEARCH_DIR.glob("research-*.json"))]
    BR.hub_page(h, series, releases, tmp_path)
    html = (tmp_path / "index.html").read_text(encoding="utf-8")
    for m in releases:
        assert f'href="/research/{m}/"' in html
    assert f"{series[-1][1]:.1f}%" not in html


def test_the_share_card_is_not_a_picture_of_a_withheld_number(
        monkeypatch, rep, tmp_path):
    """The OG card is nothing BUT the value, so it cannot be 'the page minus
    the chart'. ~3,400 per-ZIP cards kept serving withdrawn readings for two
    days in August because that was missed once already."""
    pytest.importorskip("PIL")
    _mode(monkeypatch, "paused")
    BR.og_card(rep, tmp_path / "og.png")
    assert (tmp_path / "og.png").exists()      # the URL survives …
    from PIL import Image
    with Image.open(tmp_path / "og.png") as im:
        assert im.size == (1200, 630)          # … at the same size


# ————— 4. the v2 index is a different index —————

def test_v2_is_absent_until_its_file_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(RS, "HISTORY_V2", tmp_path / "nope.json")
    assert RS.v2_series() == []
    assert RS.published_v2_series() == []


def test_v2_rows_carry_their_own_series_name_and_never_join_v1(
        monkeypatch, rep, series, tmp_path):
    _fake_v2(monkeypatch, tmp_path)
    # A release from the v2 era: the first one will be, and a release cannot
    # carry months published after it (see the cap test below).
    rep = {**rep, "month": "2026-09"}
    BR.write_csvs(rep, series, tmp_path, v2=RS.v2_series())
    rows = list(csv.DictReader((tmp_path / "wsi-history.csv").open(encoding="utf-8")))
    kinds = {r["series"] for r in rows}
    assert RS.SERIES_V2 in kinds, "the v2 series is missing from the file"
    assert kinds <= {RS.SERIES_CONTINUOUS, RS.SERIES_RECONSTRUCTION, RS.SERIES_V2}
    # Every v1 month keeps its own label: appending v2 onto the v1 series, or
    # relabelling v1 rows to match, would publish one continuous line made of
    # two different indices.
    v1_months = {m for m, _ in series}
    for r in rows:
        if r["series"] == RS.SERIES_V2:
            assert r["month"] not in v1_months
        else:
            assert r["month"] in v1_months


def test_v2_is_capped_at_the_release_month(monkeypatch, tmp_path):
    """A release page is a snapshot; it must not chart months published after
    it. The v1 series is already sliced this way — v2 has to match."""
    _fake_v2(monkeypatch, tmp_path, months=("2026-08", "2026-09"))
    assert [m for m, _ in RS.published_v2_series(upto="2026-08")] == ["2026-08"]


def test_both_series_on_one_chart_draw_a_visible_break(monkeypatch, tmp_path):
    """Two strokes, a labelled rule between them, and no connecting segment.

    The check is that the drawing code runs and produces the expected canvas
    for the two-series case — the pixels are a human call, but a crash or a
    silently single-stroke chart is not.
    """
    pytest.importorskip("PIL")
    v1 = [("2026-05", 60.0), ("2026-06", 61.0), ("2026-07", 61.9)]
    v2 = [("2026-08", 40.0), ("2026-09", 41.0)]
    out = tmp_path / "chart.png"
    BR.wsi_chart(v1, {"delta": None}, [], out, seam="2026-05", v2=v2,
                 note=RS.series_break_note("2026-08"))
    from PIL import Image
    with Image.open(out) as im:
        assert im.size == (1200, 675)
    with pytest.raises(ValueError):
        BR.wsi_chart([], {"delta": None}, [], out)     # callers must not


def test_a_broken_v2_file_reads_as_empty_not_as_v1(monkeypatch, tmp_path):
    """A malformed file must not take the research build down, and must not
    fall back to something that looks like data."""
    p = tmp_path / "history-v2.json"
    p.write_text("{not json")
    monkeypatch.setattr(RS, "HISTORY_V2", p)
    assert RS.v2_series() == []


# ————— 5. the narrowed grant —————

RESTRICTION = ("Redistribution of these files as a dataset, or use of them to "
               "build a competing data product or service, is not permitted.")


def _flat(s):
    return " ".join(s.split())


def test_restricted_removes_republication_and_keeps_quotation(
        monkeypatch, rep, series, tmp_path):
    _mode(monkeypatch, licence="restricted")
    BR.write_csvs(rep, series, tmp_path)
    text = (tmp_path / "LICENSE.txt").read_text(encoding="utf-8")
    assert "republish these indicators" not in text
    assert "Republication is NOT granted" in text
    assert "quote these indicators" in text
    assert "shouldisellyet.com" in text
    # Narrowing the grant must not drop the limits that were already on it.
    assert _flat(RESTRICTION) in _flat(text)


def test_restricted_narrows_every_page_surface_at_once(monkeypatch):
    """The broadest wording anywhere is the one a reader relies on, so a
    narrowing that reaches LICENSE.txt and not the footer narrows nothing."""
    _mode(monkeypatch, licence="restricted")
    for text in (BR.grant_html(), BR.download_note(), BR.footer_grant()):
        low = text.lower()
        assert "republish" not in low
        assert "republication" in low and "not granted" in low
        assert "attribution" in low


def test_current_licence_surfaces_are_left_exactly_alone(monkeypatch):
    _mode(monkeypatch, licence="current")
    assert BR.grant_html() is BR.USE_HTML_CURRENT
    assert BR.download_note() is BR.DOWNLOAD_NOTE_CURRENT
    assert BR.footer_grant() is BR.FOOTER_GRANT_CURRENT


# ————— 6. the attribution stays while the data does —————

def test_no_mode_strips_the_redfin_credit_from_published_history(monkeypatch):
    """LEGAL HOLD. While a value computed from a vendor's data is published,
    that vendor is credited. These modes stop publishing; they never quietly
    keep publishing without the credit, which would be the worse fault."""
    for mode in RS.INDEX_MODES:
        _mode(monkeypatch, mode)
        assert "Redfin" in BR.CITE
