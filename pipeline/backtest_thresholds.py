"""
ShouldISellYet — danger-line backtest against FHFA's official ZIP indexes.

The report's disclosures used to justify each danger line with the general
sentence "the level that preceded price declines in past national
downturns," because no backtest existed. This script builds one:

  signals  — end-of-year snapshots per (ZIP, year) computed from the Redfin
             market tracker with the SAME rules the live verdict uses
             (verdict.evaluate), for every year the tracker covers.
  outcome  — FHFA's official annual house-price change for that ZIP the
             FOLLOWING year (government repeat-sales index; nominal).

For each danger line we then report: of markets past the line at year-end,
what share saw prices fall the next year — against the same share for
markets inside the line. Honest caveats baked into the output: nominal
changes, annual granularity, GSE-mortgage sample (FHFA), and the tracker's
own coverage window.

Run after each FHFA release (annual):

  python pipeline/backtest_thresholds.py \
      --redfin /path/to/zip_code_market_tracker.tsv000.gz \
      --fhfa-full /path/to/fhfa_full.csv \
      [--out pipeline/backtest_results.json]

fetch_data.py embeds the topline into meta.json (national.backtest) on its
next run, which the report's disclosures read.
"""

import argparse
import csv
import json
import statistics
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_data import load_rows, row_to_metrics
from verdict import evaluate

HERE = Path(__file__).parent

# disclosure key -> the verdict reason codes that mean "past this line"
SIGNAL_CODES = {
    "mos":   ("supply_high", "supply_severe"),
    "price": ("price_falling", "price_falling_fast"),
    "cuts":  ("price_cuts_widespread",),
    "dom":   ("dom_stretching",),
    "inv":   ("inventory_surge",),
}
# metric presence per signal, so "clear" never counts absent data as healthy
SIGNAL_PRESENT = {
    "mos":   lambda m: m.months_of_supply is not None,
    "price": lambda m: m.median_sale_price_yoy is not None,
    "cuts":  lambda m: m.price_drop_share is not None,
    "dom":   lambda m: m.median_dom is not None and m.median_dom_yoy is not None,
    "inv":   lambda m: m.inventory_yoy is not None,
}


def year_end_snapshots(source):
    """Latest row per (zip, year) from the Redfin tracker."""
    best = {}
    for row in load_rows(source):
        if (row.get("is_seasonally_adjusted") or "").strip().lower() == "true":
            continue
        pt = (row.get("property_type") or "").strip().lower()
        if pt and "all residential" not in pt:
            continue
        region = row.get("region", "")
        z = region.split(":")[-1].strip() if ":" in region else region.strip()
        if not (z.isdigit() and len(z) == 5):
            continue
        period = row.get("period_end", "")
        if len(period) < 7:
            continue
        year = period[:4]
        key = (z, year)
        if key not in best or period > best[key][0]:
            state = (row.get("state_code") or "").strip().upper()[:2]
            best[key] = (period, state, row)
    return best


def load_fhfa_full(path):
    chg = {}
    for r in csv.DictReader(open(path)):
        try:
            chg[(r["zip"], int(r["year"]))] = float(r["chg"])
        except (KeyError, ValueError):
            continue
    return chg


def bucket():
    return {"n": 0, "declines": 0, "chgs": []}


def add(b, outcome):
    b["n"] += 1
    if outcome < 0:
        b["declines"] += 1
    b["chgs"].append(outcome)


def finish(b):
    if not b["n"]:
        return None
    return {
        "n": b["n"],
        "decline_pct": round(100 * b["declines"] / b["n"], 1),
        "median_chg": round(statistics.median(b["chgs"]), 2),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--redfin", required=True, help="Redfin ZIP tracker tsv(.gz) path or URL")
    ap.add_argument("--fhfa-full", required=True, help="zip,year,chg csv from fetch_fhfa.py --full-out")
    ap.add_argument("--out", default=str(HERE / "backtest_results.json"))
    args = ap.parse_args()

    print("loading FHFA outcomes…")
    outcomes = load_fhfa_full(args.fhfa_full)
    fhfa_thru = max(y for _, y in outcomes)
    print(f"{len(outcomes)} zip-year outcomes, through {fhfa_thru}")

    print("building year-end signal snapshots from the Redfin tracker…")
    snaps = year_end_snapshots(args.redfin)
    years = sorted({y for _, y in snaps})
    print(f"{len(snaps)} zip-year snapshots, {years[0]}–{years[-1]}")

    levels = {k: bucket() for k in ("green", "yellow", "red", "strong")}
    signals = {k: {"crossed": bucket(), "clear": bucket()} for k in SIGNAL_CODES}
    pairs = 0

    for (z, year), (period, state, row) in snaps.items():
        outcome = outcomes.get((z, int(year) + 1))
        if outcome is None:
            continue
        m = row_to_metrics(z, period, state, row)
        v = evaluate(m)
        if v.reasons and v.reasons[0][0] == "insufficient_data":
            continue
        pairs += 1
        add(levels[v.level], outcome)
        codes = {c for c, _, _ in v.reasons}
        for sig, sig_codes in SIGNAL_CODES.items():
            if not SIGNAL_PRESENT[sig](m):
                continue
            side = "crossed" if any(c in codes for c in sig_codes) else "clear"
            add(signals[sig][side], outcome)

    results = {
        "generated": date.today().isoformat(),
        "redfin_years": [int(years[0]), int(years[-1])],
        "fhfa_thru": fhfa_thru,
        "n_pairs": pairs,
        "notes": "Outcomes are FHFA nominal annual ZIP-index changes the year after "
                 "each year-end signal snapshot; FHFA indexes sample GSE-backed "
                 "mortgages and are annual, so this measures direction over a "
                 "12-month horizon, not exact magnitudes.",
        "levels": {k: finish(b) for k, b in levels.items()},
        "signals": {k: {"crossed": finish(v["crossed"]), "clear": finish(v["clear"])}
                    for k, v in signals.items()},
    }
    Path(args.out).write_text(json.dumps(results, indent=2))
    print(json.dumps(results["levels"], indent=2))
    for k, v in results["signals"].items():
        print(k, "crossed:", v["crossed"], "clear:", v["clear"])
    print(f"wrote {args.out}")


def write_web_extract(results, web=ROOT / "web" / "data"):
    """Small committed extract the public pages render from.

    press.html used to carry these numbers as hand-typed prose and they drifted:
    it published 155,612 ZIP-years and a 10.2/18.3/27.8 ladder while the
    computed truth was 182,644 and 11.3/18.9/28.1 — the published HOLD rate
    flattering us by a point. Numbers about our own performance render from a
    file or they do not appear.
    """
    web.mkdir(parents=True, exist_ok=True)
    (web / "backtest.json").write_text(json.dumps({
        "n_pairs": results["n_pairs"],
        "years": results["redfin_years"],
        "fhfa_thru": results.get("fhfa_thru"),
        "ladder": {k: {"n": v["n"], "decline_pct": v["decline_pct"]}
                   for k, v in results["levels"].items()},
    }, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
