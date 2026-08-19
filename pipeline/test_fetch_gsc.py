"""Search Console puller — parsing, aggregation and the empty-ranking guard.

The dangerous failure here is not a crash. It is a plausible-looking CSV:
state hubs counted as ZIPs, trailing-slash duplicates halving a ZIP's
impressions, or an empty pull quietly replacing a good ranking the day
before somebody spends $199 against it. These pin all three.

Run: python3 -m pytest pipeline/test_fetch_gsc.py -q
"""

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import fetch_gsc
from fetch_gsc import (data_span, non_zip_summary, page_to_zip,
                       rows_to_zip_ranking, window, write_ranking)

S = "https://shouldisellyet.com"


def row(url, clicks=0, imps=0, pos=0.0):
    return {"keys": [url], "clicks": clicks, "impressions": imps, "position": pos}


# ————— page_to_zip —————

@pytest.mark.parametrize("url,expected", [
    (f"{S}/zip/20874/", "20874"),
    (f"{S}/zip/20874", "20874"),
    (f"{S}/zip/06106/", "06106"),                       # leading zero survives
    (f"{S}/zip/20874/?utm_source=x", "20874"),          # shared links keep tags
    (f"{S}/zip/MD/", None),                             # state hub, not a ZIP
    (f"{S}/zip/", None),
    (f"{S}/", None),
    (f"{S}/report.html", None),
    (f"{S}/s/20874/", None),                            # share stub, noindexed
    (f"{S}/zip/2087/", None),                           # too short
    (f"{S}/zip/2087a/", None),
    (f"{S}/research/2026-07/", None),
    ("", None),
    (None, None),
])
def test_page_to_zip(url, expected):
    assert page_to_zip(url) == expected


# ————— aggregation —————

def test_ranking_orders_by_impressions_then_clicks():
    rows = [row(f"{S}/zip/11111/", 1, 10, 8.0),
            row(f"{S}/zip/22222/", 5, 90, 3.0),
            row(f"{S}/zip/33333/", 0, 50, 20.0)]
    r = rows_to_zip_ranking(rows)
    assert [d["zip"] for d in r] == ["22222", "33333", "11111"]
    assert r[0]["clicks"] == 5 and r[0]["impressions"] == 90


def test_trailing_slash_variants_are_one_zip():
    """Search Console treats /zip/20874 and /zip/20874/ as different URLs.
    Counting them separately would halve the ZIP that Tier A is chosen on."""
    r = rows_to_zip_ranking([row(f"{S}/zip/20874/", 2, 100, 4.0),
                             row(f"{S}/zip/20874", 1, 100, 6.0)])
    assert len(r) == 1
    assert r[0]["impressions"] == 200 and r[0]["clicks"] == 3


def test_position_is_impression_weighted_not_averaged():
    """Two pages at position 4 (900 imps) and 40 (100 imps) average to 22 —
    which is nowhere near where this ZIP actually shows up."""
    r = rows_to_zip_ranking([row(f"{S}/zip/20874/", 0, 900, 4.0),
                             row(f"{S}/zip/20874", 0, 100, 40.0)])
    assert r[0]["position"] == 7.6          # (4*900 + 40*100) / 1000
    assert r[0]["position"] != 22.0


def test_ctr_recomputed_from_totals():
    r = rows_to_zip_ranking([row(f"{S}/zip/20874/", 5, 100), row(f"{S}/zip/20874", 5, 900)])
    assert r[0]["ctr"] == 0.01              # 10/1000, not the mean of 5% and 0.6%


def test_state_hubs_and_homepage_never_enter_the_ranking():
    rows = [row(f"{S}/zip/MD/", 9, 999), row(f"{S}/", 9, 999),
            row(f"{S}/zip/20874/", 1, 5)]
    r = rows_to_zip_ranking(rows)
    assert [d["zip"] for d in r] == ["20874"]


def test_zero_impression_rows_do_not_divide_by_zero():
    r = rows_to_zip_ranking([row(f"{S}/zip/20874/", 0, 0, 0.0)])
    assert r[0]["ctr"] == 0.0 and r[0]["position"] == 0.0


def test_non_zip_summary_is_the_pause_era_signal():
    """While every ZIP page is noindexed this is the only populated part of
    the report, and it is what distinguishes a dead property from a live
    one with correctly deindexed pages."""
    rows = [row(f"{S}/", 3, 120), row(f"{S}/report.html", 1, 40),
            row(f"{S}/zip/20874/", 0, 7)]
    assert non_zip_summary(rows) == [("/", 120), ("/report.html", 40)]


# ————— probe —————

def test_data_span_ignores_zero_impression_days():
    rows = [{"keys": ["2026-08-01"], "impressions": 0},
            {"keys": ["2026-08-05"], "impressions": 12},
            {"keys": ["2026-08-09"], "impressions": 3},
            {"keys": ["2026-08-20"], "impressions": 0}]
    assert data_span(rows) == ("2026-08-05", "2026-08-09")


def test_data_span_empty():
    assert data_span([]) == (None, None)


# ————— window —————

def test_window_is_inclusive_and_respects_lag():
    start, end = window(90, 3, today=date(2026, 8, 19))
    assert end == "2026-08-16"                    # 3 days back
    assert start == "2026-05-19"                  # 90 days inclusive of end


# ————— the guard that matters —————

def test_empty_ranking_refuses_to_clobber_a_populated_file(tmp_path, monkeypatch, capsys):
    out = tmp_path / "gsc_zip.csv"
    write_ranking(out, [{"zip": "20874", "clicks": 5, "impressions": 900,
                         "ctr": 0.005, "position": 4.0}])
    before = out.read_text()

    saved = tmp_path / "saved"
    saved.mkdir()
    (saved / "page-000.json").write_text(json.dumps(
        {"rows": [row(f"{S}/", 1, 10)]}))          # a real pull, no ZIP rows

    code = fetch_gsc.main(["--input", str(saved), "--out", str(out)])
    assert code == 1
    assert out.read_text() == before               # untouched
    assert "REFUSING" in capsys.readouterr().out


def test_allow_empty_overrides_the_guard(tmp_path):
    out = tmp_path / "gsc_zip.csv"
    write_ranking(out, [{"zip": "20874", "clicks": 5, "impressions": 900,
                         "ctr": 0.005, "position": 4.0}])
    saved = tmp_path / "saved"
    saved.mkdir()
    (saved / "page-000.json").write_text(json.dumps({"rows": []}))

    assert fetch_gsc.main(["--input", str(saved), "--out", str(out),
                           "--allow-empty"]) == 0
    assert out.read_text().strip() == "zip,clicks,impressions,ctr,position"


def test_empty_pull_reports_why_rather_than_looking_like_a_ranking(tmp_path, capsys):
    saved = tmp_path / "saved"
    saved.mkdir()
    (saved / "page-000.json").write_text(json.dumps({"rows": [row(f"{S}/", 1, 10)]}))
    fetch_gsc.main(["--input", str(saved), "--out", str(tmp_path / "new.csv")])
    out = capsys.readouterr().out
    assert "NO ZIP-PAGE IMPRESSIONS" in out and "noindex" in out


def test_input_mode_reads_a_directory_of_pages(tmp_path):
    saved = tmp_path / "saved"
    saved.mkdir()
    (saved / "page-000.json").write_text(json.dumps({"rows": [row(f"{S}/zip/11111/", 0, 30)]}))
    (saved / "page-001.json").write_text(json.dumps({"rows": [row(f"{S}/zip/22222/", 0, 70)]}))
    out = tmp_path / "r.csv"
    assert fetch_gsc.main(["--input", str(saved), "--out", str(out)]) == 0
    lines = out.read_text().strip().splitlines()
    assert lines[1].startswith("22222") and lines[2].startswith("11111")


def test_input_mode_makes_no_network_call(tmp_path, monkeypatch):
    """Re-parsing stored responses must never touch the API — that is the
    whole point of keeping them."""
    def boom(*a, **k):
        raise AssertionError("network call in --input mode")
    monkeypatch.setattr(fetch_gsc, "access_token", boom)
    monkeypatch.setattr(fetch_gsc, "query", boom)
    saved = tmp_path / "saved"
    saved.mkdir()
    (saved / "p.json").write_text(json.dumps({"rows": [row(f"{S}/zip/11111/", 0, 30)]}))
    assert fetch_gsc.main(["--input", str(saved), "--out", str(tmp_path / "r.csv")]) == 0


def test_missing_credentials_name_themselves(monkeypatch):
    for k in ("GSC_CLIENT_ID", "GSC_CLIENT_SECRET", "GSC_REFRESH_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    with pytest.raises(SystemExit) as e:
        fetch_gsc.access_token()
    msg = str(e.value)
    assert "GSC_CLIENT_ID" in msg and "GSC_REFRESH_TOKEN" in msg
