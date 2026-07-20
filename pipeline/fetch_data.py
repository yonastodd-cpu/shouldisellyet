"""
ShouldISellYet — data pipeline.

Downloads the Redfin Data Center ZIP-code market tracker, computes a
verdict for every ZIP with sufficient data, and writes:

  web/data/index.json          — 3-digit ZIP prefix → state (for routing)
  web/data/zips/{STATE}.json   — per-state verdict maps
  web/data/meta.json           — generation date, data period, attribution

Run monthly (locally or via GitHub Actions):
  python pipeline/fetch_data.py [--states MD,VA,DC] [--input path.tsv.gz]

NOTE ON LICENSING: Redfin makes this data available for use with proper
citation ("Data from Redfin, a national real estate brokerage"). Before
charging customers, get written confirmation from press@redfin.com.
Zillow research data is NOT used here — its terms restrict commercial use.
"""

import argparse
import csv
import gzip
import io
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from verdict import ZipMetrics, evaluate, to_compact

REDFIN_ZIP_TRACKER = (
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/"
    "redfin_market_tracker/zip_code_market_tracker.tsv000.gz"
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "data"


def _f(row, key):
    """Parse a float field; Redfin uses empty strings for missing."""
    v = row.get(key, "")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_rows(source: str):
    """Stream rows from a local file or the Redfin URL (gzipped TSV)."""
    if source.startswith("http"):
        req = urllib.request.Request(source, headers={"User-Agent": "shouldisellyet-pipeline"})
        raw = urllib.request.urlopen(req, timeout=600)
        stream = gzip.GzipFile(fileobj=raw)
    elif source.endswith(".gz"):
        stream = gzip.open(source, "rb")
    else:
        stream = open(source, "rb")
    text = io.TextIOWrapper(stream, encoding="utf-8", errors="replace")
    return csv.DictReader(text, delimiter="\t")


def latest_by_zip(rows, states=None):
    """Keep the newest 'All Residential' row per ZIP. Prints diagnostics."""
    best = {}
    skipped = {"property_type": 0, "bad_zip": 0, "state_filter": 0}
    first_row_shown = False
    seen_ptypes = {}
    for row in rows:
        if not first_row_shown:
            print("COLUMNS:", list(row.keys()))
            print("SAMPLE ROW:", {k: row[k] for k in list(row)[:14]})
            first_row_shown = True
        pt = (row.get("property_type") or "").strip().lower()
        seen_ptypes[pt] = seen_ptypes.get(pt, 0) + 1
        if pt and "all residential" not in pt:
            skipped["property_type"] += 1
            continue
        region = row.get("region", "")           # "Zip Code: 20874"
        zip_code = region.split(":")[-1].strip() if ":" in region else region.strip()
        if not (zip_code.isdigit() and len(zip_code) == 5):
            skipped["bad_zip"] += 1
            continue
        state = (row.get("state_code") or row.get("state") or "").strip().upper()
        if len(state) > 2:  # full state name → keep last resort mapping simple
            state = state[:2].upper()
        if states and state not in states:
            skipped["state_filter"] += 1
            continue
        period = row.get("period_end", "")
        if zip_code not in best or period > best[zip_code][0]:
            best[zip_code] = (period, state, row)
    print("skipped:", skipped)
    print("property_type values seen:",
          dict(sorted(seen_ptypes.items(), key=lambda x: -x[1])[:8]))
    return best


def row_to_metrics(zip_code, period, state, row) -> ZipMetrics:
    inv = _f(row, "inventory")
    sold = _f(row, "homes_sold")
    mos = _f(row, "months_of_supply")
    if mos is None and inv and sold:
        mos = inv / sold  # proxy: inventory ÷ monthly sales
    return ZipMetrics(
        zip_code=zip_code,
        state=state,
        period=period[:7],
        months_of_supply=mos,
        median_sale_price_yoy=_f(row, "median_sale_price_yoy"),
        price_drop_share=_f(row, "price_drops"),
        median_dom=_f(row, "median_dom"),
        median_dom_yoy=_f(row, "median_dom_yoy"),
        inventory_yoy=_f(row, "inventory_yoy"),
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=REDFIN_ZIP_TRACKER,
                    help="Local TSV(.gz) path or URL (default: Redfin ZIP tracker)")
    ap.add_argument("--states", default="",
                    help="Comma-separated state codes to limit output (e.g. MD,VA,DC)")
    args = ap.parse_args()
    states = set(s.strip().upper() for s in args.states.split(",") if s.strip()) or None

    print(f"Loading {args.input} …")
    best = latest_by_zip(load_rows(args.input), states)
    print(f"{len(best)} ZIPs with data")
    if len(best) < 100 and args.input.startswith("http"):
        sys.exit(
            f"FATAL: only {len(best)} ZIPs parsed — refusing to publish. "
            "Check the COLUMNS/SAMPLE ROW diagnostics above for a schema mismatch."
        )

    by_state = defaultdict(dict)
    prefix_state = {}
    period_seen = ""
    for zip_code, (period, state, row) in best.items():
        m = row_to_metrics(zip_code, period, state, row)
        v = evaluate(m)
        by_state[state or "XX"][zip_code] = to_compact(v, m)
        prefix_state[zip_code[:3]] = state or "XX"
        period_seen = max(period_seen, period)

    OUT.joinpath("zips").mkdir(parents=True, exist_ok=True)
    for state, zips in by_state.items():
        (OUT / "zips" / f"{state}.json").write_text(json.dumps(zips, separators=(",", ":")))
    (OUT / "index.json").write_text(json.dumps(prefix_state, separators=(",", ":")))
    (OUT / "meta.json").write_text(json.dumps({
        "generated": date.today().isoformat(),
        "period": period_seen[:7],
        "attribution": "Data from Redfin, a national real estate brokerage (redfin.com)",
    }))

    counts = defaultdict(int)
    for zips in by_state.values():
        for z in zips.values():
            counts[z["l"]] += 1
    print(f"Done. green={counts['green']} yellow={counts['yellow']} red={counts['red']}")
    print(f"Wrote {len(by_state)} state files to {OUT}")


if __name__ == "__main__":
    main()
