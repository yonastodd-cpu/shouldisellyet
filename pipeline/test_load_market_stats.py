"""Loader — what it refuses to invent, and how it batches.

schema-v35 makes retrieved_at and as_of_month NOT NULL on purpose: v34 had
to approximate a retrieval instant for 27,405 legacy rows and said so in a
column comment. This is the file where that stops, so most of these tests
are about the loader declining to fill a gap rather than filling it.

Run: python3 -m pytest pipeline/test_load_market_stats.py -q
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import load_market_stats as lm
from load_market_stats import batches, job_rows, month_of, stat_rows

PAYLOAD = {
    "zipCode": "20874",
    "saleData": {
        "lastUpdatedDate": "2026-08-01", "medianPrice": 525000,
        "averagePrice": 548200, "medianPricePerSquareFoot": 241.5,
        "averageDaysOnMarket": 38.4, "totalListings": 96, "newListings": 31,
        "history": {"2025-09": {}, "2026-07": {}},
    },
    "rentalData": {"medianRent": 2600},
}
LEDGER = {"20874": {"zip": "20874", "status": "done", "http": "200",
                    "bytes": "4210", "retrieved_at": "2026-08-19T14:00:00Z",
                    "attempts": "1", "note": ""}}


def archive(tmp_path, payloads):
    d = tmp_path / "raw"
    d.mkdir(exist_ok=True)
    for z, p in payloads.items():
        (d / f"{z}.json").write_text(json.dumps(p))
    return d


# ————— what it refuses to invent —————

def test_no_ledger_entry_means_no_row(tmp_path):
    """retrieved_at has one honest source: the ledger the runner stamped at
    the moment of the call. Without it the ZIP is skipped, not dated now."""
    rows, skipped = stat_rows(archive(tmp_path, {"20874": PAYLOAD}), ledger={})
    assert rows == [] and skipped["no_retrieved_at"] == 1


def test_blank_retrieved_at_is_also_refused(tmp_path):
    led = {"20874": dict(LEDGER["20874"], retrieved_at="")}
    rows, skipped = stat_rows(archive(tmp_path, {"20874": PAYLOAD}), ledger=led)
    assert rows == [] and skipped["no_retrieved_at"] == 1


def test_undatable_payload_is_skipped_not_filed_under_now(tmp_path):
    """A statistic dated by when it was loaded corrupts every later
    month-over-month comparison built on it."""
    p = {"zipCode": "20874", "saleData": {"medianPrice": 1}}
    rows, skipped = stat_rows(archive(tmp_path, {"20874": p}), ledger=LEDGER)
    assert rows == [] and skipped["undatable"] == 1


def test_unparseable_file_is_counted_not_fatal(tmp_path):
    d = archive(tmp_path, {"20874": PAYLOAD})
    (d / "bad.json").write_text("{nope")
    rows, skipped = stat_rows(d, ledger=LEDGER)
    assert len(rows) == 1 and skipped["unparseable"] == 1


# ————— dating —————

def test_month_prefers_the_vendors_own_last_updated_date():
    assert month_of({"as_of": "2026-08-01", "history_to": "2026-07"}) == "2026-08"


def test_month_falls_back_to_newest_history_month():
    assert month_of({"as_of": "", "history_to": "2026-07"}) == "2026-07"


def test_month_override_wins_for_known_backfills():
    assert month_of({"as_of": "2026-08-01", "history_to": "2026-07"}, "2024-01") == "2024-01"


def test_month_is_none_when_unknowable():
    assert month_of({"as_of": "", "history_to": ""}) is None
    assert month_of({"as_of": "garbage", "history_to": "nope"}) is None


# ————— the row —————

def test_stat_row_carries_the_whole_payload_verbatim(tmp_path):
    """raw_json is Lever 2 as a column: rentals and breakdowns included, so
    re-parsing after a formula change never costs another request."""
    rows, _ = stat_rows(archive(tmp_path, {"20874": PAYLOAD}), ledger=LEDGER)
    assert rows[0]["raw_json"] == PAYLOAD
    assert rows[0]["raw_json"]["rentalData"] == {"medianRent": 2600}


def test_stat_row_matches_the_v35_columns(tmp_path):
    rows, _ = stat_rows(archive(tmp_path, {"20874": PAYLOAD}), ledger=LEDGER)
    r = rows[0]
    assert r["zip"] == "20874" and r["as_of_month"] == "2026-08"
    assert r["source"] == "rentcast"
    assert r["retrieved_at"] == "2026-08-19T14:00:00Z"
    assert r["list_median_price"] == 525000 and r["active_dom"] == 38.4
    assert r["history_months"] == 2
    assert set(r) == {"zip", "as_of_month", "source", "retrieved_at",
                      "list_median_price", "list_average_price",
                      "list_median_ppsf", "active_dom", "total_listings",
                      "new_listings", "history_months", "raw_json"}


def test_jobs_carry_the_tier_the_zip_was_bought_in():
    """tier_interim.csv is regenerated; without copying it the record of
    what was actually paid for is unrecoverable."""
    rows = job_rows(LEDGER, {"20874": "A"})
    assert rows[0]["tier"] == "A" and rows[0]["status"] == "done"
    assert rows[0]["http"] == 200 and rows[0]["bytes"] == 4210


def test_jobs_tolerate_a_ledger_with_blank_numbers():
    led = {"11111": {"zip": "11111", "status": "error", "http": "",
                     "bytes": "", "attempts": "", "note": "timeout"}}
    r = job_rows(led, {})[0]
    assert r["http"] is None and r["bytes"] is None and r["attempts"] == 0
    assert r["tier"] is None and r["note"] == "timeout"


# ————— batching —————

def test_batches_close_on_bytes_before_rows():
    """A 500-row batch of raw payloads would be tens of MB and fail as a
    request-size error halfway through Tier A."""
    rows = [{"zip": f"{i:05d}", "blob": "x" * 1000} for i in range(10)]
    out = list(batches(rows, max_rows=100, max_bytes=3000))
    assert len(out) > 1
    assert all(sum(len(json.dumps(r)) for r in b) <= 3000 or len(b) == 1
               for b in out)


def test_batches_close_on_rows_when_small():
    rows = [{"zip": f"{i:05d}"} for i in range(10)]
    assert [len(b) for b in batches(rows, max_rows=4, max_bytes=10**9)] == [4, 4, 2]


def test_an_oversized_single_row_still_ships_alone():
    """Refusing it would drop the biggest markets — exactly the ones Tier A
    paid for."""
    rows = [{"zip": "20874", "blob": "x" * 5000}]
    assert [len(b) for b in batches(rows, max_rows=100, max_bytes=100)] == [1]


def test_no_rows_no_batches():
    assert list(batches([])) == []


# ————— sending —————

def test_send_continues_past_a_failed_batch():
    """The upsert is idempotent, so finishing and re-running beats stopping
    with an unknown fraction applied."""
    seen = []

    def sender(url, key, table, on_conflict, rows):
        seen.append(len(rows))
        return 500 if len(seen) == 1 else 201
    sent, failed = lm.send("u", "k", "market_stats", "zip",
                           [{"zip": f"{i:05d}"} for i in range(9)],
                           sender=sender, max_rows=4)
    assert seen == [4, 4, 1]          # the run continued past the failure
    assert failed == 1 and sent == 5  # rows 5-9 landed; the first 4 did not


def test_send_reports_transport_errors_as_failed_batches():
    def sender(*a, **k):
        raise OSError("connection reset")
    sent, failed = lm.send("u", "k", "market_stats", "zip", [{"zip": "20874"}],
                           sender=sender)
    assert sent == 0 and failed == 1


# ————— main —————

def test_dry_run_sends_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(lm, "post", lambda *a, **k: pytest.fail("dry run sent"))
    led = tmp_path / "l.csv"
    led.write_text("zip,status,http,bytes,retrieved_at,attempts,note\n"
                   "20874,done,200,4210,2026-08-19T14:00:00Z,1,\n")
    assert lm.main(["--raw", str(archive(tmp_path, {"20874": PAYLOAD})),
                    "--ledger", str(led), "--tiers-file", str(tmp_path / "none.csv"),
                    "--dry-run"]) == 0
    assert "DRY RUN" in capsys.readouterr().out


def test_missing_supabase_config_exits_zero(tmp_path, monkeypatch, capsys):
    """A fork or a local run without secrets must not fail a refresh —
    the same discipline as upsert_velocity.py."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    monkeypatch.setattr(lm, "post", lambda *a, **k: pytest.fail("sent without config"))
    led = tmp_path / "l.csv"
    led.write_text("zip,status,http,bytes,retrieved_at,attempts,note\n"
                   "20874,done,200,4210,2026-08-19T14:00:00Z,1,\n")
    assert lm.main(["--raw", str(archive(tmp_path, {"20874": PAYLOAD})),
                    "--ledger", str(led),
                    "--tiers-file", str(tmp_path / "none.csv")]) == 0
    assert "not configured" in capsys.readouterr().out


def test_loader_makes_no_vendor_call(tmp_path, monkeypatch):
    import fetch_rentcast
    monkeypatch.setattr(fetch_rentcast, "fetch_market",
                        lambda *a, **k: pytest.fail("loader called the vendor"))
    rows, _ = stat_rows(archive(tmp_path, {"20874": PAYLOAD}), ledger=LEDGER)
    assert len(rows) == 1
