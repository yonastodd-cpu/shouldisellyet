#!/usr/bin/env python3
"""Push the stored RentCast archive into market_stats / market_jobs (v35).

    python3 pipeline/load_market_stats.py --dry-run
    python3 pipeline/load_market_stats.py

Reads what fetch_rentcast.py already wrote — archive/rentcast/*.json and
pipeline/rentcast_jobs.csv — and upserts both tables. It makes NO vendor
call and costs nothing: the disk archive is the source of truth, the
database is the durable copy of it. Re-running is free and idempotent, so
after a parser fix the right move is always to re-load rather than re-fetch.

Same discipline as upsert_velocity.py: missing Supabase config prints and
exits 0, because a fork or a local run without secrets must not fail a
refresh.

TWO THINGS THIS REFUSES TO INVENT, both for the reason schema-v35 spells
out — a column that is sometimes a real measurement and sometimes a guess is
worse than one that is sometimes absent:

  * retrieved_at. It comes from the ledger row for that ZIP, which the
    runner stamped at the moment of the call. No ledger entry, no timestamp,
    no row — the ZIP is reported as skipped instead. v34 had to approximate
    this for 27,405 legacy rows and documented the regret; this is the
    file where that stops.
  * as_of_month. Taken from the payload's own lastUpdatedDate, falling back
    to the newest month present in its history block. If a payload carries
    neither, the ZIP is skipped rather than filed under "now" — a statistic
    dated by when it was loaded rather than when it was measured will
    silently corrupt any month-over-month comparison built on it. --month
    overrides deliberately, for a backfill where the date is known
    externally.

BATCHING IS BY BYTES, NOT ROWS. raw_json is the whole vendor payload —
twelve months of history plus breakdowns by property type and bedroom count
— so a 500-row batch on the velocity model would be tens of megabytes and
fail as a request-size error halfway through Tier A. Batches close at
MAX_BYTES or MAX_ROWS, whichever comes first.
"""

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_rentcast import LEDGER, RAW, TIERS, load_ledger, parse_market

MAX_ROWS = 100
MAX_BYTES = 4_000_000          # comfortably under PostgREST's default limits
SOURCE = "rentcast"


# ————— row building —————

def month_of(parsed, override=None):
    """YYYY-MM for this payload, or None if it cannot be known.

    Order: an explicit override, then the vendor's own last-updated date,
    then the newest month in its history block. Never the wall clock.
    """
    if override:
        return override
    as_of = (parsed.get("as_of") or "")[:7]
    if len(as_of) == 7 and as_of[4] == "-":
        return as_of
    hist = parsed.get("history_to") or ""
    return hist if len(hist) == 7 and hist[4] == "-" else None


def stat_rows(raw_dir=RAW, ledger=None, source=SOURCE, month=None):
    """(rows, skipped) for market_stats. `skipped` counts reasons, so a run
    that loads 940 of 1,000 says which 60 and why."""
    ledger = ledger if ledger is not None else load_ledger()
    rows, skipped = [], {}
    for f in sorted(Path(raw_dir).glob("*.json")):
        z = f.stem
        try:
            payload = json.loads(f.read_text())
        except (ValueError, OSError):
            skipped["unparseable"] = skipped.get("unparseable", 0) + 1
            continue
        job = ledger.get(z) or {}
        retrieved = job.get("retrieved_at") or ""
        if not retrieved:
            skipped["no_retrieved_at"] = skipped.get("no_retrieved_at", 0) + 1
            continue
        parsed = parse_market(payload)
        as_of = month_of(parsed, month)
        if not as_of:
            skipped["undatable"] = skipped.get("undatable", 0) + 1
            continue
        rows.append({
            "zip": parsed["zip"] or z,
            "as_of_month": as_of,
            "source": source,
            "retrieved_at": retrieved,
            "list_median_price": parsed["list_median_price"],
            "list_average_price": parsed["list_average_price"],
            "list_median_ppsf": parsed["list_median_ppsf"],
            "active_dom": parsed["active_dom"],
            "total_listings": parsed["total_listings"],
            "new_listings": parsed["new_listings"],
            "history_months": parsed["history_months"],
            "raw_json": payload,
        })
    return rows, skipped


HISTORY_KEYS = (("median_list_price", "medianPrice"),
                ("active_dom", "averageDaysOnMarket"),
                ("total_listings", "totalListings"))


def history_rows(raw_dir=RAW, source=SOURCE, months=12):
    """The monthly series, one row per zip/month, from the stored payloads.

    The vendor sends twelve months inside a single response, so this is not
    extra data — it is the same data, normalised so the reading endpoint can
    serve a sparkline without reading raw_json. That matters: the endpoint is
    the republication boundary, and it holds only while every field it returns
    is a named column.

    A month with no median price is dropped rather than stored as null: a gap
    in a sparkline is honest, a zero is not.
    """
    out = []
    for f in sorted(Path(raw_dir).glob("*.json")):
        try:
            payload = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        hist = ((payload or {}).get("saleData") or {}).get("history") or {}
        zip_code = (payload or {}).get("zipCode") or f.stem
        for month in sorted(hist)[-months:]:
            rec = hist.get(month) or {}
            price = rec.get("medianPrice")
            if not isinstance(price, (int, float)):
                continue
            row = {"zip": zip_code, "source": source, "as_of_month": month}
            for col, key in HISTORY_KEYS:
                v = rec.get(key)
                row[col] = v if isinstance(v, (int, float)) else None
            out.append(row)
    return out


# WHAT WAS PAID FOR, NOT WHAT IS CURRENT. job_rows() rebuilds every row from
# the ledger on each run, so whatever this points at relabels the whole
# acquisition history. The first 5,000 ZIPs were bought against
# tier_interim.csv; rank_v2 reorders 18,953 of them, and letting that reach
# market_jobs.tier would rewrite what the column exists to remember. A future
# acquisition round should record its own file here alongside this one.
ACQUIRED_TIERS = Path(__file__).parent / "tier_interim.csv"


def load_tiers(path=ACQUIRED_TIERS):
    """{zip: tier} — which tier a ZIP was in WHEN IT WAS BOUGHT."""
    p = Path(path)
    if not p.exists():
        return {}
    return {r["zip"]: r.get("tier") for r in csv.DictReader(open(p, encoding="utf-8"))}


def job_rows(ledger=None, tiers=None, source=SOURCE):
    ledger = ledger if ledger is not None else load_ledger()
    tiers = tiers if tiers is not None else load_tiers()
    out = []
    for z, r in sorted(ledger.items()):
        out.append({
            "zip": z,
            "source": source,
            "status": r.get("status") or "pending",
            "tier": tiers.get(z) or None,
            "http": int(r["http"]) if str(r.get("http", "")).isdigit() else None,
            "bytes": int(r["bytes"]) if str(r.get("bytes", "")).isdigit() else None,
            "attempts": int(r["attempts"]) if str(r.get("attempts", "")).isdigit() else 0,
            "note": r.get("note") or None,
            "retrieved_at": r.get("retrieved_at") or None,
        })
    return out


# ————— sending —————

def batches(rows, max_rows=MAX_ROWS, max_bytes=MAX_BYTES):
    """Close a batch on whichever limit is hit first. A single row larger
    than max_bytes still ships alone — refusing it would drop the biggest
    markets, which are exactly the ones Tier A bought."""
    cur, size = [], 0
    for r in rows:
        n = len(json.dumps(r))
        if cur and (len(cur) >= max_rows or size + n > max_bytes):
            yield cur
            cur, size = [], 0
        cur.append(r)
        size += n
    if cur:
        yield cur


def post(url, key, table, on_conflict, rows, timeout=180):
    req = urllib.request.Request(
        f"{url}/rest/v1/{table}?on_conflict={on_conflict}",
        data=json.dumps(rows).encode(), method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Prefer": "resolution=merge-duplicates,return=minimal"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status


def send(url, key, table, on_conflict, rows, sender=post,
         max_rows=MAX_ROWS, max_bytes=MAX_BYTES):
    """Returns (sent, failed_batches). One bad batch does not abandon the
    rest: the upsert is idempotent, so finishing and re-running is strictly
    better than stopping with an unknown fraction applied."""
    sent, failed = 0, 0
    for i, b in enumerate(batches(rows, max_rows, max_bytes)):
        try:
            status = sender(url, key, table, on_conflict, b)
            if status not in (200, 201, 204):
                print(f"  {table} batch {i}: HTTP {status}", file=sys.stderr)
                failed += 1
                continue
            sent += len(b)
        except (urllib.error.HTTPError, urllib.error.URLError, OSError) as e:
            detail = e.read().decode("utf-8", "replace")[:200] if hasattr(e, "read") else str(e)[:200]
            print(f"  {table} batch {i}: {detail}", file=sys.stderr)
            failed += 1
    return sent, failed


def main(argv=None):
    ap = argparse.ArgumentParser(description="Load the RentCast archive into Supabase")
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--tiers-file", default=str(TIERS))
    ap.add_argument("--source", default=SOURCE)
    ap.add_argument("--month", help="override as_of_month (backfills where the date is known externally)")
    ap.add_argument("--stats-only", action="store_true")
    ap.add_argument("--jobs-only", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="build the rows, send nothing")
    args = ap.parse_args(argv)

    ledger = load_ledger(args.ledger)
    stats, skipped = stat_rows(args.raw, ledger, args.source, args.month)
    jobs = job_rows(ledger, load_tiers(args.tiers_file), args.source)

    print(f"market_stats: {len(stats):,} row(s) from {args.raw}")
    for why, n in sorted(skipped.items()):
        print(f"  skipped {why}: {n:,}")
    print(f"market_jobs: {len(jobs):,} row(s) from {args.ledger}")
    hist_preview = history_rows(args.raw, args.source) if not args.jobs_only else []
    print(f"market_history: {len(hist_preview):,} monthly point(s) "
          f"across {len({h['zip'] for h in hist_preview}):,} ZIP(s)")
    if stats:
        nbatch = sum(1 for _ in batches(stats))
        mb = sum(len(json.dumps(r)) for r in stats) / 1e6
        print(f"  {mb:.1f} MB in {nbatch} batch(es)")

    if args.dry_run:
        print("DRY RUN — nothing sent.")
        return 0

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("market load: Supabase not configured — nothing to do")
        return 0

    failed = 0
    if not args.jobs_only and stats:
        n, f = send(url, key, "market_stats", "zip,as_of_month,source", stats)
        print(f"market_stats: upserted {n:,}")
        failed += f
    if not args.jobs_only:
        hist = history_rows(args.raw, args.source)
        if hist:
            n, f = send(url, key, "market_history", "zip,source,as_of_month", hist)
            print(f"market_history: upserted {n:,} monthly point(s)")
            failed += f
    if not args.stats_only and jobs:
        n, f = send(url, key, "market_jobs", "zip,source", jobs)
        print(f"market_jobs: upserted {n:,}")
        failed += f
    if failed:
        print(f"{failed} batch(es) failed — re-run to finish; the upsert is "
              f"idempotent so nothing is duplicated.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
