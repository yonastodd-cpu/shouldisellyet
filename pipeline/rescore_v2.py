#!/usr/bin/env python3
"""Re-score acquired ZIPs on v2 and merge the readings into web/data/zips.

    python3 pipeline/rescore_v2.py --dry-run
    python3 pipeline/rescore_v2.py

This is the step between "the data is bought" and "a tranche can be
released". promote_tranche.py refuses to stage a ZIP whose reading is still
legacy, and data_pause refuses to publish one, so nothing reaches a reader
until this has run for that ZIP.

A MERGE, NOT A REBUILD. Only acquired ZIPs are touched. The ~28,000 that
have no RentCast data keep their existing entries exactly as they are —
paused, legacy, invisible. Re-running is idempotent.

WHAT A RE-SCORED ENTRY LOOKS LIKE, and why each choice:

  l, s, r   from verdict_v2. Same keys as v1 so no reader forks.
  b         "active listings" — the marker the tranche guard reads, and the
            thing that lets a page say what kind of number it shows.
  m.domy    WRITTEN IN DAYS, not the fraction the engine scores on. Three
            separate renderers (build_pages.metric_rows, index.html's
            buildMetricRows, market-render.js) already compute
            `domy / (dom - domy)` to recover a rate, and they are the wire
            format. Emitting a fraction here would not error — it would
            quietly print "+0 days y/y" on every released page. The engine
            keeps its fraction internally; this is the boundary where units
            are the readers'.
  m.mos     ABSENT. RentCast cannot produce months of supply, and every
            renderer already guards `if mos != null`, so the dial simply
            does not appear. Same for m.pd and m.sold.
  h         REBUILT from RentCast's 12-month history. This is the one that
            would have leaked: v1's `h` holds 36 months of REDFIN prices and
            the page plots it as a sparkline, so a released page carrying an
            untouched `h` would publish the withdrawn vendor's data in a
            chart while the headline number was correctly the new vendor's.
  x, f      LEFT ALONE. Realtor.com cross-check and FHFA are neither Redfin
            nor RentCast — different vendors, unaffected by this migration.
            (Realtor.com's commercial terms remain attorney question 3.)
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from shard_layout import require_shards
import verdict_v2 as v2
from calibrate_v2 import DB_SQL, _num

ROOT = Path(__file__).resolve().parents[1]
ZIPS = ROOT / "web" / "data" / "zips"
STATS = Path(__file__).parent / "rentcast_stats.csv"
HIST_KEYS = ("medianPrice", "averageDaysOnMarket")


def _rpc_rows(source, zips=None):
    """The same query over PostgREST, using SUPABASE_URL + the service key.

    The CLI path needs a LINKED project, which an operator's machine has and CI
    does not. That is how the tranche-1 release failed to land: "Cannot find
    project ref", readings_for() returned {}, and 1,000 released ZIPs published
    the notice instead of their readings.

    public.readings_for_scoring (schema-v38) does the raw_json transform inside
    the database, so the republication boundary stays server-side — the caller
    gets the five fields a reading needs and cannot ask for the payload.
    Returns None when no credentials are configured, so the caller can fall
    back rather than crash.
    """
    import os
    import urllib.request
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        return None
    body = {"p_source": source}
    if zips:
        # Ask for exactly what is needed. Requesting all 5,000 and keeping the
        # ~1,000 we want cost 23 of them on the first CI run: the function
        # returns all 5,000 (verified in psql) and the REST layer delivered
        # fewer. Asking by ZIP makes the response small and, more importantly,
        # makes short delivery detectable — the caller knows what it asked for.
        body["p_zips"] = sorted(zips)
    req = urllib.request.Request(
        f"{url}/rest/v1/rpc/readings_for_scoring",
        data=json.dumps(body).encode(), method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Accept-Profile": "public", "Range-Unit": "items"})
    with urllib.request.urlopen(req, timeout=600) as r:
        rows = json.loads(r.read().decode())
    if zips is not None and len(rows) < len(set(zips)):
        got = {x.get("zip") for x in rows}
        short = sorted(set(zips) - got)
        print(f"::warning::rescore: asked the store for {len(set(zips)):,} ZIP(s) "
              f"and received {len(rows):,}. Missing {len(short):,}, e.g. "
              f"{', '.join(short[:5])}")
    return rows


def db_rows(source="rentcast", zips=None):
    """market_stats → [(row, history)]. Rows are data to score, never
    instructions.

    Tries the RPC first (works anywhere with a URL and the service key), then
    the linked CLI. Order matters: CI has the credentials and no link, and the
    silent fallback to "no readings" is exactly what shipped a release that did
    not publish.
    """
    import subprocess
    rows = None
    try:
        rows = _rpc_rows(source, zips)
    except Exception as e:
        print(f"rescore: RPC unavailable ({type(e).__name__}: {str(e)[:120]}) "
              f"— falling back to the linked CLI")
    if rows is None:
        sql = DB_SQL.format(source="'" + source.replace("'", "''") + "'")
        proc = subprocess.run(["npx", "--yes", "supabase", "db", "query", "--linked", sql],
                              capture_output=True, text=True, cwd=ROOT, timeout=600)
        if "{" not in proc.stdout:
            raise SystemExit(f"db query returned no JSON. stderr: {proc.stderr[:300]}")
        rows = json.loads(proc.stdout[proc.stdout.index("{"):]).get("rows", [])
    out = []
    for r in rows:
        hist = r.get("history")
        if isinstance(hist, str):
            hist = json.loads(hist)
        out.append(({"zip": r.get("zip") or "",
                     "as_of_month": r.get("as_of_month") or "",
                     "list_median_price": _num(r.get("list_median_price")),
                     "active_dom": _num(r.get("active_dom")),
                     "total_listings": _num(r.get("total_listings")),
                     "list_median_ppsf": _num(r.get("list_median_ppsf")),
                     "new_listings": _num(r.get("new_listings"))}, hist or {}))
    return out


def csv_rows(path=STATS):
    """Offline fallback: the parsed table the runner writes. Carries no
    history, so YoY cannot be computed — usable for a smoke test, never for
    a real re-score, and this says so rather than silently scoring every ZIP
    as insufficient_data."""
    rows = []
    for r in csv.DictReader(open(path, encoding="utf-8")):
        rows.append(({k: (_num(v) if k not in ("zip", "as_of") else v)
                      for k, v in r.items()} | {"zip": r["zip"]}, {}))
    return rows


def history_block(hist, months=12):
    """RentCast's month-keyed history → the compact {s, p, d} the sparkline
    reads. Months with no price are dropped from both series together so the
    two arrays stay index-aligned, which is what the renderer assumes."""
    keep = []
    for month in sorted(hist)[-months:]:
        rec = hist.get(month) or {}
        price = _num(rec.get("medianPrice"))
        if price is None:
            continue
        keep.append((month, price, _num(rec.get("averageDaysOnMarket"))))
    if not keep:
        return None
    return {"s": keep[0][0],
            "p": [round(p) for _, p, _ in keep],
            "d": [round(d) if d is not None else None for _, _, d in keep]}


def dom_days_yoy(market, row, hist):
    """The year-over-year DOM change IN DAYS — the wire format every renderer
    already parses. The engine scores the fraction; this is the same fact in
    the readers' units."""
    months = sorted(hist)
    if len(months) < 12 or market.active_dom is None:
        return None
    prior = (hist.get(months[-13]) if len(months) >= 13 else hist.get(months[0])) or {}
    then = _num(prior.get("averageDaysOnMarket"))
    return None if then is None else round(market.active_dom - then, 1)


def compact(market, row, hist):
    """The entry fields this step owns. Everything else is preserved."""
    verdict = v2.evaluate(market)
    m = {"spy": market.list_price_yoy,
         "dom": market.active_dom,
         "domy": dom_days_yoy(market, row, hist),
         "invy": market.listings_yoy,
         "inv": market.total_listings,
         "ppsfy": market.ppsf_yoy,
         "nly": market.new_listings_yoy}
    m = {k: (round(v, 4) if isinstance(v, float) else v)
         for k, v in m.items() if v is not None}
    # The record carries its own month. The global meta.json is frozen at the
    # last Redfin run, so a page that took its date from there published August
    # readings as "Data through June 2026".
    out = {"p": (row.get("as_of_month") or "") or None,
           "l": verdict.level, "s": verdict.score,
           "r": [[c, p, round(v, 4) if isinstance(v, float) else v]
                 for c, p, v in verdict.reasons],
           "b": verdict.basis, "m": m}
    if not out["p"]:
        out.pop("p")
    h = history_block(hist)
    if h:
        out["h"] = h
    return out, verdict


def merge(entry, scored):
    """v2 fields replace their v1 counterparts; st/x/f survive.

    The legacy m, h and any v1-only keys are REPLACED rather than merged —
    a half-migrated entry carrying months-of-supply from one vendor beside a
    list price from another is exactly the mismatch this migration exists to
    end.
    """
    keep = {k: v for k, v in entry.items() if k in ("st", "x", "f")}
    return keep | scored


def run(rows, zips_dir=ZIPS, dry=False):
    require_shards(zips_dir, "rescore_v2.run",
                   "the per-state shard layout it rewrites in place")
    files = sorted(Path(zips_dir).glob("*.json"))
    data = {f: json.loads(f.read_text()) for f in files}
    index = {z: f for f, d in data.items() for z in d}

    scored_by_file, stats = {}, {"scored": 0, "missing_entry": 0,
                                 "insufficient": 0, "no_history": 0}
    levels = {}
    for row, hist in rows:
        z = row["zip"]
        f = index.get(z)
        if not f:
            stats["missing_entry"] += 1
            continue
        market = v2.from_market_stats(row, hist)
        scored, verdict = compact(market, row, hist)
        if verdict.reasons and verdict.reasons[0][0] == "insufficient_data":
            stats["insufficient"] += 1
        if "h" not in scored:
            stats["no_history"] += 1
        levels[verdict.level] = levels.get(verdict.level, 0) + 1
        scored_by_file.setdefault(f, {})[z] = scored
        stats["scored"] += 1

    if not dry:
        for f, scores in scored_by_file.items():
            d = data[f]
            for z, scored in scores.items():
                d[z] = merge(d[z], scored)
            f.write_text(json.dumps(d, separators=(",", ":")), encoding="utf-8")
    return stats, levels, len(scored_by_file)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Re-score acquired ZIPs on verdict v2")
    ap.add_argument("--source", default="rentcast")
    ap.add_argument("--stats-csv", help="offline fallback; no history, smoke tests only")
    ap.add_argument("--zips", default=str(ZIPS))
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    rows = csv_rows(args.stats_csv) if args.stats_csv else db_rows(args.source)
    print(f"loaded {len(rows):,} acquired ZIP(s)")
    stats, levels, files = run(rows, args.zips, args.dry_run)

    print(f"re-scored: {stats['scored']:,} across {files} state file(s)")
    for k in ("missing_entry", "insufficient", "no_history"):
        if stats[k]:
            print(f"  {k}: {stats[k]:,}")
    print("  " + " · ".join(f"{k} {v:,}" for k, v in sorted(levels.items())))
    if args.dry_run:
        print("DRY RUN — nothing written.")
    else:
        print("written. These ZIPs are now eligible for promote_tranche.py.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
