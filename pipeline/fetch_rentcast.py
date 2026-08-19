#!/usr/bin/env python3
"""ShouldISellYet — RentCast /markets runner for the tiered migration.

Acquires and stores. It does not rewrite the verdict engine and does not
touch a published page: Phase 3 does that, against data this has already
put on disk.

    python3 pipeline/fetch_rentcast.py --tier A --ceiling 1000
    python3 pipeline/fetch_rentcast.py --tier A --ceiling 1000 --dry-run
    python3 pipeline/fetch_rentcast.py --parse-only        # $0, from archive

EVERY COST CONTROL IN THE PLAN IS A CODE PATH HERE, because a cost control
that lives in a document gets skipped at 2am on the third retry:

  * --ceiling is REQUIRED for a live run. There is no default, so no run can
    quietly exceed a quota nobody set. Set it to your included quota and
    overage becomes a deliberate act.
  * Every response is written to archive/rentcast/ before anything is
    parsed. Re-parsing, re-backtesting and re-thresholding then cost $0
    forever (Lever 2). A parser bug must never be a reason to re-buy bytes.
  * Already-`done` ZIPs are skipped. The ledger is written after every
    single ZIP, so a crash resumes instead of restarting — restarting a
    5,000-ZIP run costs $150, not just time.
  * Retries cap at 3 and then mark `error`. An unbounded retry loop on a
    systematically failing ZIP burns quota silently, which is the worst way
    to spend it.
  * historyRange is requested at maximum on the FIRST call, because one call
    returns current stats plus history plus the breakdowns. Per-month or
    per-metric calls buy the same bytes repeatedly.

THE LEDGER (pipeline/rentcast_jobs.csv) is the audit trail and the
checkpoint in one file: zip,status,http,bytes,retrieved_at,attempts,note.
Status is pending / done / no_data / error, matching the plan's job states.
It is committed — "what did we actually buy, and when" is the question this
migration will be asked later, and it is the same question Phase 0 had to
answer about Redfin with no recorded retrieval timestamp anywhere.

FIELD NAMES follow RentCast's documented /markets response. The parser is
deliberately tolerant — an absent field yields None rather than an
exception, and the raw payload is on disk either way — because the Phase 2.3
validation gate exists precisely to confirm the mapping against real
responses before Tier B money is spent. Do not tighten it before then.
"""

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_data import _ssl_context

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.rentcast.io/v1/markets"
RAW = ROOT / "archive" / "rentcast"          # gitignored, permanent on disk
LEDGER = Path(__file__).parent / "rentcast_jobs.csv"
TIERS = Path(__file__).parent / "tier_interim.csv"
STATS = Path(__file__).parent / "rentcast_stats.csv"
HISTORY_RANGE = 12                            # months; the documented maximum
MAX_ATTEMPTS = 3
LEDGER_FIELDS = ["zip", "status", "http", "bytes", "retrieved_at", "attempts", "note"]
STATUSES = ("pending", "done", "no_data", "error")


# ————— targets and ledger —————

def load_targets(path=TIERS, tiers=("A",), limit=None):
    """ZIPs to call, in ranked order, from the tier CSV.

    Order matters beyond tidiness: a run cut short by the ceiling should
    have spent its requests on the highest-ranked ZIPs, not a random half.
    """
    want = {t.strip().upper() for t in tiers if t.strip()}
    out = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        if r.get("tier", "").upper() in want:
            out.append(r["zip"])
    return out[:limit] if limit else out


def load_ledger(path=LEDGER):
    if not Path(path).exists():
        return {}
    return {r["zip"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def save_ledger(path, ledger):
    """Rewritten after every ZIP. Small enough that the cost is nothing and
    the guarantee — a crash never loses more than the ZIP in flight — is
    worth more than the writes."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=LEDGER_FIELDS, extrasaction="ignore")
        w.writeheader()
        for z in sorted(ledger):
            w.writerow(ledger[z])
    tmp.replace(path)                     # atomic: never a half-written ledger


def pending(targets, ledger, refresh=False):
    """Targets still owing a call. `done` and `no_data` are both settled —
    re-calling a ZIP RentCast has already said it has no data for buys the
    same non-answer again."""
    if refresh:
        return list(targets)
    return [z for z in targets
            if ledger.get(z, {}).get("status") not in ("done", "no_data")]


# ————— network —————

def api_key():
    k = os.environ.get("RENTCAST_API_KEY", "")
    if not k:
        raise SystemExit(
            "RENTCAST_API_KEY is not set. It belongs in the secrets manager, "
            "never in the repo — see docs/migration/PHASE1-PLUS.md §1.4.")
    return k


def fetch_market(zip_code, key, history_range=HISTORY_RANGE, timeout=60):
    """One /markets call. Returns (http_status, body_bytes, parsed_or_None).

    404 is a real answer — RentCast has no market data for this ZIP — and is
    reported as 404 with no body so the caller can mark it `no_data` rather
    than retrying a settled question.
    """
    q = urllib.parse.urlencode({
        "zipCode": zip_code, "dataType": "All", "historyRange": history_range})
    req = urllib.request.Request(f"{API}?{q}", headers={
        "X-Api-Key": key, "Accept": "application/json"})
    try:
        resp = urllib.request.urlopen(req, timeout=timeout, context=_ssl_context())
        body = resp.read()
        return resp.status, len(body), json.loads(body.decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        body = e.read()
        if e.code == 404:
            return 404, len(body), None
        raise RentcastHTTPError(e.code, body.decode("utf-8", "replace")[:300])


class RentcastHTTPError(Exception):
    def __init__(self, code, detail):
        super().__init__(f"HTTP {code}: {detail}")
        self.code, self.detail = code, detail


def retryable(code):
    """429 and 5xx are worth another attempt; 4xx are not — a 401 retried
    three times is three ways of being told the same thing."""
    return code == 429 or 500 <= code < 600


# ————— parsing —————

def _num(d, *keys):
    for k in keys:
        v = (d or {}).get(k)
        if isinstance(v, (int, float)):
            return v
    return None


def parse_market(obj):
    """A /markets payload → the fields Phase 3's formula can actually use.

    Only sale-side statistics are taken. Rental data arrives in the same
    response (dataType=All costs no more than dataType=Sale) and is stored
    raw, but nothing on this site reads it and pretending otherwise would
    invite a rental number onto a for-sale page.

    NOTE the metric shift, in the names: `medianPrice` here is a LIST price
    median from active listings, where Redfin's was a closed-sale median.
    Trend is comparable, level is not. The column names keep `list_` on them
    so no one downstream mistakes one for the other.
    """
    sale = (obj or {}).get("saleData") or {}
    hist = sale.get("history") or {}
    return {
        "zip": (obj or {}).get("zipCode") or "",
        "as_of": sale.get("lastUpdatedDate") or "",
        "list_median_price": _num(sale, "medianPrice"),
        "list_average_price": _num(sale, "averagePrice"),
        "list_median_ppsf": _num(sale, "medianPricePerSquareFoot"),
        "active_dom": _num(sale, "averageDaysOnMarket"),
        "total_listings": _num(sale, "totalListings"),
        "new_listings": _num(sale, "newListings"),
        "history_months": len(hist),
        "history_from": min(hist) if hist else "",
        "history_to": max(hist) if hist else "",
    }


STAT_FIELDS = list(parse_market({}).keys())


def parse_archive(raw_dir=RAW, out=STATS):
    """Rebuild the parsed table from stored responses. Costs nothing, which
    is the entire point of storing them — every formula revision and
    threshold recalibration runs through here, not through the API."""
    rows = []
    for f in sorted(Path(raw_dir).glob("*.json")):
        try:
            rows.append(parse_market(json.loads(f.read_text())))
        except (ValueError, OSError) as e:
            print(f"  unparseable {f.name}: {e}")
    rows.sort(key=lambda r: r["zip"])
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=STAT_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    return rows


# ————— the run —————

def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run(targets, key, ceiling, raw_dir=RAW, ledger_path=LEDGER,
        history_range=HISTORY_RANGE, rps=5.0, fetch=fetch_market,
        sleep=time.sleep, clock=now_utc):
    """Call each target once, storing as it goes. Returns (ledger, spent).

    `fetch`, `sleep` and `clock` are injected so the tests can exercise the
    ceiling, the retry cap and the checkpointing without a network or a
    wall-clock delay.
    """
    ledger = load_ledger(ledger_path)
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    interval = 1.0 / rps if rps > 0 else 0
    spent = 0

    for i, z in enumerate(targets):
        if spent >= ceiling:
            print(f"CEILING REACHED: {spent:,} requests spent, "
                  f"{len(targets) - i:,} target(s) left unfetched — re-run "
                  f"with a higher --ceiling to continue, deliberately.")
            break
        attempts, status, http, size, note = 0, "error", "", "", ""
        while attempts < MAX_ATTEMPTS:
            attempts += 1
            spent += 1
            try:
                http, size, obj = fetch(z, key, history_range)
                if obj is None:
                    status, note = "no_data", "404 from RentCast"
                else:
                    (raw_dir / f"{z}.json").write_text(
                        json.dumps(obj, indent=1), encoding="utf-8")
                    status = "done"
                break
            except RentcastHTTPError as e:
                http, note = e.code, e.detail
                if not retryable(e.code) or attempts >= MAX_ATTEMPTS:
                    status = "error"
                    break
                sleep(min(2 ** attempts, 30))       # 2s, 4s — then give up
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                http, note = "", str(e)[:200]
                if attempts >= MAX_ATTEMPTS:
                    status = "error"
                    break
                sleep(min(2 ** attempts, 30))
            if spent >= ceiling:
                status, note = "pending", "ceiling reached mid-retry"
                break

        ledger[z] = {"zip": z, "status": status, "http": http, "bytes": size,
                     "retrieved_at": clock(), "attempts": attempts, "note": note}
        save_ledger(ledger_path, ledger)            # checkpoint every ZIP
        if interval:
            sleep(interval)

    return ledger, spent


def summarise(ledger, spent, ceiling):
    counts = {s: 0 for s in STATUSES}
    for r in ledger.values():
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    total_bytes = sum(int(r["bytes"] or 0) for r in ledger.values())
    print(f"requests spent this run: {spent:,} of a {ceiling:,} ceiling")
    print("ledger: " + " · ".join(f"{k} {v:,}" for k, v in counts.items() if v))
    print(f"stored: {total_bytes/1e6:.1f} MB across {counts.get('done', 0):,} ZIPs")
    if counts.get("error"):
        print(f"{counts['error']:,} ZIP(s) in error — inspect the note column "
              f"before re-running; a systematic failure re-run is quota burnt twice.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="RentCast /markets tiered runner")
    ap.add_argument("--tier", default="A", help="comma-separated tiers from tier_interim.csv")
    ap.add_argument("--tiers-file", default=str(TIERS))
    ap.add_argument("--limit", type=int, help="first N targets (smoke tests)")
    ap.add_argument("--ceiling", type=int,
                    help="hard stop after this many requests — REQUIRED for a live run")
    ap.add_argument("--rps", type=float, default=5.0,
                    help="request rate, deliberately under the published limit")
    ap.add_argument("--history-range", type=int, default=HISTORY_RANGE)
    ap.add_argument("--raw", default=str(RAW))
    ap.add_argument("--ledger", default=str(LEDGER))
    ap.add_argument("--stats", default=str(STATS))
    ap.add_argument("--refresh", action="store_true",
                    help="re-call ZIPs already marked done (spends money again)")
    ap.add_argument("--dry-run", action="store_true",
                    help="print what would be called and stop; costs nothing")
    ap.add_argument("--parse-only", action="store_true",
                    help="rebuild the parsed table from stored responses; costs nothing")
    args = ap.parse_args(argv)

    if args.parse_only:
        rows = parse_archive(args.raw, args.stats)
        print(f"parsed {len(rows):,} stored responses → {args.stats}")
        return 0

    targets = load_targets(args.tiers_file, args.tier.split(","), args.limit)
    todo = pending(targets, load_ledger(args.ledger), args.refresh)
    print(f"tier {args.tier}: {len(targets):,} target(s), {len(todo):,} still owing a call")

    if args.dry_run:
        print("DRY RUN — no requests made. First 10:", ", ".join(todo[:10]) or "none")
        print(f"A live run would spend up to {len(todo):,} requests.")
        return 0

    if args.ceiling is None:
        raise SystemExit(
            "--ceiling is required for a live run. Set it to your plan's "
            "included quota so overage is a deliberate decision, not an "
            "accident at request 5,001. Use --dry-run to size the job first.")
    if not todo:
        print("nothing to do")
        return 0

    ledger, spent = run(todo, api_key(), args.ceiling, args.raw, args.ledger,
                        args.history_range, args.rps)
    summarise(ledger, spent, args.ceiling)
    rows = parse_archive(args.raw, args.stats)
    print(f"parsed {len(rows):,} stored responses → {args.stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
