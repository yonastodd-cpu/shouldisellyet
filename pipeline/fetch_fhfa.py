"""
ShouldISellYet — FHFA ZIP5 house-price-index extraction (annual).

FHFA publishes experimental annual repeat-sales indexes for five-digit ZIP
codes (Bogin, Doerner & Larson; see citation below). This is the official,
government-published measure of *value* — annual and lagged, so it is a
benchmark and backtest source, never an early-warning signal.

Run ONCE per FHFA release (they update annually):

  python pipeline/fetch_fhfa.py \
      [--input hpi_at_bdl_zip5.xlsx | URL] \
      [--out pipeline/fhfa_zip.csv] \
      [--full-out /tmp/fhfa_full.csv]

Outputs:
  pipeline/fhfa_zip.csv   (committed, small) — one row per ZIP:
                          zip,thru,a1,a3
                            thru = latest year with a reported change
                            a1   = that year's annual change, %
                            a3   = mean of the last 3 reported changes, %
                          fetch_data.py merges this into each ZIP entry as
                          `f` on every monthly run — no xlsx dependency.
  --full-out              (not committed, ~12MB) — zip,year,chg history for
                          backtest_thresholds.py.

Requires openpyxl (only for this annual run, not for the monthly pipeline).

Citation (per FHFA's tracking request): Bogin, A., Doerner, W., Larson, W.
(2019). Local House Price Dynamics: New Indices and Stylized Facts. Real
Estate Economics 47(2), 365-398. FHFA working paper 16-01.
"""

import argparse
import csv
import io
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_data import _ssl_context  # same CA handling as the main pipeline

FHFA_ZIP5_URL = "https://www.fhfa.gov/document/hpi_at_bdl_zip5.xlsx"
HERE = Path(__file__).parent


def iter_fhfa_rows(source):
    """Yield (zip, year, annual_change_pct_or_None) from the FHFA workbook."""
    import openpyxl
    if str(source).startswith("http"):
        req = urllib.request.Request(source, headers={"User-Agent": "shouldisellyet-pipeline"})
        data = urllib.request.urlopen(req, timeout=300, context=_ssl_context()).read()
        fh = io.BytesIO(data)
    else:
        fh = open(source, "rb")
    wb = openpyxl.load_workbook(fh, read_only=True)
    ws = wb.active
    started = False
    for row in ws.iter_rows(values_only=True):
        if not started:
            if row and str(row[0] or "").strip().lower().startswith("five-digit zip"):
                started = True
            continue
        if not row or row[0] is None:
            continue
        z = str(row[0]).strip()
        if not (z.isdigit() and len(z) == 5):
            continue
        try:
            year = int(str(row[1]).strip())
        except (TypeError, ValueError):
            continue
        raw = str(row[2]).strip() if row[2] is not None else "."
        chg = None
        if raw not in (".", "", "None"):
            try:
                chg = float(raw)
            except ValueError:
                chg = None
        yield z, year, chg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=FHFA_ZIP5_URL, help="FHFA ZIP5 xlsx path or URL")
    ap.add_argument("--out", default=str(HERE / "fhfa_zip.csv"),
                    help="Compact per-ZIP csv (committed)")
    ap.add_argument("--full-out", default="",
                    help="Optional full zip,year,chg history csv (for the backtest)")
    args = ap.parse_args()

    hist = {}  # zip -> list[(year, chg)]
    n = 0
    for z, year, chg in iter_fhfa_rows(args.input):
        hist.setdefault(z, []).append((year, chg))
        n += 1
    print(f"{n} rows, {len(hist)} ZIPs")

    full = None
    if args.full_out:
        full = open(args.full_out, "w", newline="")
        fw = csv.writer(full)
        fw.writerow(["zip", "year", "chg"])

    with open(args.out, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["zip", "thru", "a1", "a3"])
        kept = 0
        for z, rows in sorted(hist.items()):
            rows.sort()
            if full:
                for year, chg in rows:
                    if chg is not None:
                        fw.writerow([z, year, chg])
            reported = [(y, c) for y, c in rows if c is not None]
            if not reported:
                continue
            thru, a1 = reported[-1]
            last3 = [c for _, c in reported[-3:]]
            a3 = sum(last3) / len(last3)
            w.writerow([z, thru, round(a1, 2), round(a3, 2)])
            kept += 1
    if full:
        full.close()
    print(f"wrote {kept} ZIPs -> {args.out}" + (f" (+full history -> {args.full_out})" if args.full_out else ""))


if __name__ == "__main__":
    main()
