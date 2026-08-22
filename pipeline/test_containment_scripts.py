"""The two unattended checks, exercised without ever touching a network.

Both scripts exist to run on a schedule against somebody else's server, which
makes them the two files in this repo most likely to be "tested" by running
them once and never again. So every test here injects its transport. Nothing
in this file may make a request — and the first test is the one that proves
it, because a module that fetches on import would fetch during collection.

Run: python3 -m pytest pipeline/test_containment_scripts.py -q
"""

import csv
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import check_fallback_sources as FALLBACK
import snapshot_vendor_terms as TERMS

CLOCK = lambda: datetime(2026, 9, 1, 6, 0, 0, tzinfo=timezone.utc)


def exploding(*a, **kw):
    raise AssertionError("this code path made a network request")


# ————— neither script may fetch unasked —————

def test_neither_script_fetches_on_import_or_dry_run(monkeypatch, capsys):
    """The standing rule in this repo is that nothing calls a vendor. These
    two are the exceptions that ask first, so 'asks first' is the thing to
    pin — an --fetch flag somebody later gives a default of True would be a
    one-character change with a monthly consequence."""
    monkeypatch.setattr(TERMS, "fetch", exploding)
    monkeypatch.setattr(FALLBACK.FHFA, "iter_fhfa_rows", exploding)
    monkeypatch.setattr(FALLBACK.ACS, "fetch", exploding)
    assert TERMS.main([]) == 0
    assert FALLBACK.main([]) == 0
    out = capsys.readouterr().out
    assert out.count("DRY RUN") == 2


# ————— the terms snapshot —————

def test_it_refuses_a_destination_git_would_track(monkeypatch, tmp_path, capsys):
    """The failure this prevents: a public repository republishing a third
    party's copyrighted terms, committed by an unattended job, while we are
    arguing with that party about licence scope."""
    monkeypatch.setattr(TERMS, "fetch", exploding)
    monkeypatch.setattr(TERMS, "is_ignored", lambda p, root=None: False)
    rc = TERMS.main(["--fetch", "--dest", str(tmp_path)])
    assert rc == 2
    assert "REFUSING" in capsys.readouterr().err
    assert not list(tmp_path.iterdir()), "it wrote something before refusing"


def test_an_unanswerable_ignore_check_counts_as_not_ignored(monkeypatch, tmp_path):
    """git missing, or not a repo, exits 128. A guard that fails open is not
    a guard."""
    def boom(*a, **kw):
        raise OSError("no git here")
    monkeypatch.setattr(TERMS.subprocess, "run", boom)
    assert TERMS.is_ignored(tmp_path) is False


def test_the_body_is_stored_byte_for_byte_with_a_dated_name(tmp_path):
    body = b"<html>Terms \xe2\x80\x94 v3\x00\xff</html>"      # not valid utf-8
    rows, fails = TERMS.snapshot(
        urls=(("terms-of-service", "https://example.test/tos"),),
        dest=tmp_path, clock=CLOCK,
        fetcher=lambda url: (200, body, {"Last-Modified": "Mon, 01 Sep 2026 00:00:00 GMT"}))
    assert not fails
    f = tmp_path / "terms-of-service-2026-09-01.html"
    assert f.read_bytes() == body, "the exhibit was re-encoded"
    assert rows[0]["last_modified"].startswith("Mon, 01 Sep 2026")
    assert rows[0]["bytes"] == len(body)


def test_every_run_records_a_row_even_when_nothing_changed(tmp_path):
    """'We looked on the 1st and it was identical' is the fact worth holding.
    A directory that only records changes cannot tell 'unchanged' apart from
    'nobody ran it', which is the exact gap that lost us the version in force
    at the first call."""
    same = (lambda url: (200, b"v1", {}))
    for _ in range(3):
        TERMS.snapshot(urls=(("tos", "https://example.test/tos"),),
                       dest=tmp_path, clock=CLOCK, fetcher=same)
    rows = list(csv.DictReader((tmp_path / TERMS.MANIFEST).open()))
    assert len(rows) == 3
    assert rows[0]["changed_from_previous"] == ""          # first snapshot
    assert [r["changed_from_previous"] for r in rows[1:]] == ["false", "false"]


def test_drift_is_detected_and_both_versions_survive(tmp_path):
    urls = (("tos", "https://example.test/tos"),)
    TERMS.snapshot(urls=urls, dest=tmp_path, clock=CLOCK,
                   fetcher=lambda url: (200, b"v1", {}))
    later = lambda: datetime(2026, 10, 1, tzinfo=timezone.utc)
    rows, _ = TERMS.snapshot(urls=urls, dest=tmp_path, clock=later,
                             fetcher=lambda url: (200, b"v2 - indemnity clause moved", {}))
    assert rows[0]["changed_from_previous"] == "true"
    assert (tmp_path / "tos-2026-09-01.html").read_bytes() == b"v1", \
        "the older version was overwritten — there is nothing left to diff"
    assert (tmp_path / "tos-2026-10-01.html").exists()


def test_one_dead_url_does_not_cost_us_the_other_snapshot(tmp_path):
    def half(url):
        if url.endswith("gone"):
            raise OSError("404")
        return (200, b"ok", {})
    rows, fails = TERMS.snapshot(
        urls=(("gone-page", "https://example.test/gone"),
              ("live-page", "https://example.test/live")),
        dest=tmp_path, clock=CLOCK, fetcher=half)
    assert [r["slug"] for r in rows] == ["live-page"]
    assert [f[0] for f in fails] == ["gone-page"]


# ————— the fallback health check —————

def fhfa_rows(zips, years, chg=1.5):
    for z in zips:
        for y in years:
            yield z, y, chg


def test_a_healthy_fhfa_release_passes():
    have, thru = FALLBACK.committed_fhfa()
    assert have > 10000 and thru >= 2025, \
        "the committed baseline is empty — these tests would pass on nothing"
    ok, findings, stats = FALLBACK.check_fhfa(
        rows=fhfa_rows([f"{i:05d}" for i in range(have)], [thru, thru + 1]),
        today=date(2026, 9, 1))
    assert ok, findings
    assert stats["thru"] == thru + 1


def test_the_frozen_url_signature_is_caught():
    """The failure mode fetch_fhfa.py documents at the top of the file: the
    retired URL still returns 200 and a valid workbook, permanently stuck at
    an old release. Nothing errors; the numbers just stop advancing."""
    have, thru = FALLBACK.committed_fhfa()
    ok, findings, _ = FALLBACK.check_fhfa(
        rows=fhfa_rows([f"{i:05d}" for i in range(have)], [2023]),
        today=date(2026, 9, 1))
    assert not ok
    assert any("BEHIND the committed" in f or "stopped advancing" in f
               for f in findings), findings


def test_a_silent_parse_failure_is_caught_even_though_it_returns_rows():
    """A layout change that still yields SOME rows is worse than one that
    yields none, because a reachability check passes it."""
    have, thru = FALLBACK.committed_fhfa()
    ok, findings, _ = FALLBACK.check_fhfa(
        rows=fhfa_rows([f"{i:05d}" for i in range(max(1, have // 10))], [thru]),
        today=date(2026, 9, 1))
    assert not ok
    assert any("below" in f for f in findings), findings


def acs_dat(prefix, column, pairs):
    head = "|".join(["GEO_ID", column])
    body = "\n".join(f"{prefix}{z}|{v}" for z, v in pairs)
    return head + "\n" + body


def test_a_healthy_acs_vintage_passes():
    have = FALLBACK.committed_acs()
    zips = [f"{i:05d}" for i in range(have)]
    ok, findings, stats = FALLBACK.check_acs(
        units_text=acs_dat(FALLBACK.ACS.ZCTA_PREFIX, "B25001_E001",
                           [(z, 1000) for z in zips]),
        tenure_text=acs_dat(FALLBACK.ACS.ZCTA_PREFIX, "B25003_E002",
                            [(z, 600) for z in zips]))
    assert ok, findings
    assert stats["merged"] == have


def test_tenure_parsing_to_nothing_is_caught_by_itself():
    """Total units is the easy table and tenure is the one the tiering
    actually orders on. Units parsing while tenure empties passes a row count
    and produces a ranking with no signal in it."""
    have = FALLBACK.committed_acs()
    zips = [f"{i:05d}" for i in range(have)]
    ok, findings, _ = FALLBACK.check_acs(
        units_text=acs_dat(FALLBACK.ACS.ZCTA_PREFIX, "B25001_E001",
                           [(z, 1000) for z in zips]),
        tenure_text=acs_dat(FALLBACK.ACS.ZCTA_PREFIX, "B25003_E002", []))
    assert not ok
    assert any("owner-occupied" in f for f in findings), findings


def test_a_changed_geography_prefix_is_caught():
    """Census retires paths and layouts between vintages. A file that parses
    to zero ZCTAs is the shape that failure takes."""
    ok, findings, _ = FALLBACK.check_acs(
        units_text=acs_dat("999NOTAZCTA", "B25001_E001", [("00601", 10)]),
        tenure_text=acs_dat("999NOTAZCTA", "B25003_E002", [("00601", 5)]))
    assert not ok
    assert any("0 ZCTAs" in f for f in findings), findings


# ————— both are documented for the orchestrator —————

@pytest.mark.parametrize("mod", [TERMS, FALLBACK])
def test_each_script_states_the_ci_schedule_it_needs(mod):
    """These are useless unrun, and the workflow files belong to somebody
    else. The schedule therefore lives next to the code it schedules, where
    it cannot be lost in a handoff."""
    src = Path(mod.__file__).read_text()
    assert "THE CI JOB THIS NEEDS" in src
    assert "cron" in src and "workflow_dispatch" in src
