"""RentCast runner — the cost controls, exercised.

Every test here is about money. The runner's job is to acquire bytes once
and never buy them twice, so what gets pinned is the ceiling, the retry cap,
the resume-from-checkpoint behaviour, and the refusal to re-call a ZIP that
is already settled. A parser bug is cheap; any of these is not.

Run: python3 -m pytest pipeline/test_fetch_rentcast.py -q
"""

import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import fetch_rentcast as rc
from fetch_rentcast import (RentcastHTTPError, load_targets, parse_archive,
                            parse_market, pending, retryable, run, save_ledger)

PAYLOAD = {
    "zipCode": "20874",
    "saleData": {
        "lastUpdatedDate": "2026-08-01",
        "medianPrice": 525000, "averagePrice": 548200,
        "medianPricePerSquareFoot": 241.5,
        "averageDaysOnMarket": 38.4, "totalListings": 96, "newListings": 31,
        "history": {"2025-09": {}, "2025-10": {}, "2026-08": {}},
    },
    "rentalData": {"medianRent": 2600},
}


def fake_fetch(responses):
    """responses: {zip: [outcome, ...]} consumed per attempt. An outcome is
    a (status, bytes, obj) tuple or an exception to raise."""
    calls = []

    def _f(z, key, history_range=12, timeout=60):
        calls.append(z)
        out = responses[z].pop(0)
        if isinstance(out, Exception):
            raise out
        return out
    return _f, calls


def ledger_rows(path):
    return {r["zip"]: r for r in csv.DictReader(open(path))}


# ————— the ceiling —————

def test_ceiling_stops_the_run_and_leaves_the_rest_unfetched(tmp_path, capsys):
    zips = ["11111", "22222", "33333"]
    f, calls = fake_fetch({z: [(200, 10, PAYLOAD)] for z in zips})
    ledger, spent = run(zips, "k", ceiling=2, raw_dir=tmp_path / "raw",
                        ledger_path=tmp_path / "l.csv", fetch=f,
                        sleep=lambda *_: None, clock=lambda: "T")
    assert calls == ["11111", "22222"] and spent == 2
    assert "33333" not in ledger
    assert "CEILING REACHED" in capsys.readouterr().out


def test_ceiling_counts_retries_not_just_zips(tmp_path):
    """A retry is a billed request. A ceiling that only counted ZIPs would
    let a flaky tier spend three times its budget."""
    f, calls = fake_fetch({"11111": [RentcastHTTPError(503, "x"),
                                     RentcastHTTPError(503, "x"),
                                     (200, 10, PAYLOAD)],
                           "22222": [(200, 10, PAYLOAD)]})
    _, spent = run(["11111", "22222"], "k", ceiling=2, raw_dir=tmp_path / "raw",
                   ledger_path=tmp_path / "l.csv", fetch=f,
                   sleep=lambda *_: None, clock=lambda: "T")
    assert spent == 2 and calls == ["11111", "11111"]


def test_live_run_refuses_without_a_ceiling(tmp_path, monkeypatch):
    tiers = tmp_path / "t.csv"
    tiers.write_text("rank,tier,zip\n1,A,11111\n")
    monkeypatch.setenv("RENTCAST_API_KEY", "k")
    with pytest.raises(SystemExit) as e:
        rc.main(["--tiers-file", str(tiers), "--ledger", str(tmp_path / "l.csv")])
    assert "--ceiling is required" in str(e.value)


def test_dry_run_costs_nothing(tmp_path, monkeypatch, capsys):
    tiers = tmp_path / "t.csv"
    tiers.write_text("rank,tier,zip\n1,A,11111\n2,B,22222\n")
    monkeypatch.setattr(rc, "fetch_market", lambda *a, **k:
                        pytest.fail("dry run made a request"))
    assert rc.main(["--tiers-file", str(tiers), "--tier", "A", "--dry-run",
                    "--ledger", str(tmp_path / "l.csv")]) == 0
    assert "DRY RUN" in capsys.readouterr().out


# ————— retries —————

def test_retries_cap_at_three_then_mark_error(tmp_path):
    f, calls = fake_fetch({"11111": [RentcastHTTPError(503, "boom")] * 3})
    ledger, spent = run(["11111"], "k", ceiling=99, raw_dir=tmp_path / "raw",
                        ledger_path=tmp_path / "l.csv", fetch=f,
                        sleep=lambda *_: None, clock=lambda: "T")
    assert len(calls) == 3 and spent == 3
    assert ledger["11111"]["status"] == "error"
    assert ledger["11111"]["attempts"] == 3


def test_non_retryable_status_is_not_retried(tmp_path):
    """A 401 retried three times is three ways of hearing the same thing."""
    f, calls = fake_fetch({"11111": [RentcastHTTPError(401, "bad key")] * 3})
    ledger, spent = run(["11111"], "k", ceiling=99, raw_dir=tmp_path / "raw",
                        ledger_path=tmp_path / "l.csv", fetch=f,
                        sleep=lambda *_: None, clock=lambda: "T")
    assert len(calls) == 1 and spent == 1
    assert ledger["11111"]["status"] == "error"


@pytest.mark.parametrize("code,expected", [
    (429, True), (500, True), (502, True), (503, True),
    (400, False), (401, False), (403, False), (404, False), (200, False)])
def test_retryable_classification(code, expected):
    assert retryable(code) is expected


def test_transient_failure_then_success_is_done(tmp_path):
    f, _ = fake_fetch({"11111": [RentcastHTTPError(429, "slow down"),
                                 (200, 10, PAYLOAD)]})
    ledger, spent = run(["11111"], "k", ceiling=99, raw_dir=tmp_path / "raw",
                        ledger_path=tmp_path / "l.csv", fetch=f,
                        sleep=lambda *_: None, clock=lambda: "T")
    assert ledger["11111"]["status"] == "done" and spent == 2


# ————— storage and resume —————

def test_response_is_written_before_anything_is_parsed(tmp_path):
    raw = tmp_path / "raw"
    f, _ = fake_fetch({"20874": [(200, 10, PAYLOAD)]})
    run(["20874"], "k", ceiling=9, raw_dir=raw, ledger_path=tmp_path / "l.csv",
        fetch=f, sleep=lambda *_: None, clock=lambda: "T")
    stored = json.loads((raw / "20874.json").read_text())
    assert stored == PAYLOAD                      # byte-for-byte, rentals included


def test_ledger_is_checkpointed_after_every_zip(tmp_path):
    """A crash mid-run must lose one ZIP, not the run."""
    path = tmp_path / "l.csv"
    seen = []

    def f(z, key, history_range=12, timeout=60):
        seen.append(sorted(ledger_rows(path)) if path.exists() else [])
        return 200, 10, dict(PAYLOAD, zipCode=z)
    run(["11111", "22222", "33333"], "k", ceiling=9, raw_dir=tmp_path / "raw",
        ledger_path=path, fetch=f, sleep=lambda *_: None, clock=lambda: "T")
    assert seen == [[], ["11111"], ["11111", "22222"]]


def test_done_and_no_data_are_not_recalled(tmp_path):
    ledger = {"11111": {"zip": "11111", "status": "done"},
              "22222": {"zip": "22222", "status": "no_data"},
              "33333": {"zip": "33333", "status": "error"}}
    assert pending(["11111", "22222", "33333", "44444"], ledger) == ["33333", "44444"]


def test_refresh_overrides_the_skip(tmp_path):
    ledger = {"11111": {"zip": "11111", "status": "done"}}
    assert pending(["11111"], ledger, refresh=True) == ["11111"]


def test_404_is_no_data_not_error(tmp_path):
    f, _ = fake_fetch({"11111": [(404, 0, None)]})
    ledger, _ = run(["11111"], "k", ceiling=9, raw_dir=tmp_path / "raw",
                    ledger_path=tmp_path / "l.csv", fetch=f,
                    sleep=lambda *_: None, clock=lambda: "T")
    assert ledger["11111"]["status"] == "no_data"
    assert not (tmp_path / "raw" / "11111.json").exists()


def test_ledger_round_trips(tmp_path):
    path = tmp_path / "l.csv"
    save_ledger(path, {"11111": {"zip": "11111", "status": "done", "http": 200,
                                 "bytes": 10, "retrieved_at": "T", "attempts": 1,
                                 "note": ""}})
    assert rc.load_ledger(path)["11111"]["status"] == "done"


# ————— targets —————

def test_targets_keep_rank_order_so_a_cut_run_spent_well(tmp_path):
    t = tmp_path / "t.csv"
    t.write_text("rank,tier,zip\n1,A,77494\n2,A,78660\n3,B,11111\n4,C,22222\n")
    assert load_targets(t, ("A",)) == ["77494", "78660"]
    assert load_targets(t, ("A", "B")) == ["77494", "78660", "11111"]
    assert load_targets(t, ("A",), limit=1) == ["77494"]


# ————— parsing —————

def test_parse_market_reads_the_documented_sale_fields():
    p = parse_market(PAYLOAD)
    assert p["zip"] == "20874"
    assert p["list_median_price"] == 525000
    assert p["active_dom"] == 38.4
    assert p["total_listings"] == 96 and p["new_listings"] == 31
    assert p["history_months"] == 3
    assert p["history_from"] == "2025-09" and p["history_to"] == "2026-08"


def test_parse_market_tolerates_missing_fields():
    """Phase 2.3 validates the mapping against real responses. Until then a
    thin or differently-shaped payload must not crash a 1,000-ZIP run."""
    assert parse_market({})["list_median_price"] is None
    assert parse_market({"saleData": {}})["history_months"] == 0
    assert parse_market({"saleData": {"medianPrice": None}})["list_median_price"] is None


def test_parse_market_ignores_rental_data():
    """Rentals ride along free in dataType=All and must never reach a
    for-sale page."""
    assert "rent" not in " ".join(parse_market(PAYLOAD).keys()).lower()


def test_parse_archive_rebuilds_without_network(tmp_path, monkeypatch):
    monkeypatch.setattr(rc, "fetch_market", lambda *a, **k:
                        pytest.fail("parse-only made a request"))
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "20874.json").write_text(json.dumps(PAYLOAD))
    (raw / "11111.json").write_text(json.dumps(dict(PAYLOAD, zipCode="11111")))
    rows = parse_archive(raw, tmp_path / "s.csv")
    assert [r["zip"] for r in rows] == ["11111", "20874"]
    assert rc.main(["--parse-only", "--raw", str(raw),
                    "--stats", str(tmp_path / "s.csv")]) == 0


def test_unparseable_stored_file_does_not_sink_the_batch(tmp_path, capsys):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "bad.json").write_text("{not json")
    (raw / "20874.json").write_text(json.dumps(PAYLOAD))
    rows = parse_archive(raw, tmp_path / "s.csv")
    assert [r["zip"] for r in rows] == ["20874"]
    assert "unparseable" in capsys.readouterr().out


def test_missing_api_key_says_where_it_belongs(monkeypatch):
    monkeypatch.delenv("RENTCAST_API_KEY", raising=False)
    with pytest.raises(SystemExit) as e:
        rc.api_key()
    assert "secrets manager" in str(e.value)
