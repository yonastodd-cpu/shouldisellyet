#!/usr/bin/env python3
"""Refresh the 30-year mortgage rate in web/data/meta.json from Freddie Mac.

    python3 pipeline/refresh_pmms.py            # fetch, update, print
    python3 pipeline/refresh_pmms.py --check    # exit 1 if stale >10 days, touch nothing

WHY (paid-report item 7, 2026-08-28). The report's financing sections all
render meta.national.mortgage, and since the main refresh was paused that
block only moved when someone edited it — the report was quoting "today's
30-year rate" from a frozen file. PMMS is public, free, weekly (Thursdays);
this script reads the same PMMS_history.csv the archive step already fetches
and rewrites just the mortgage block: `now` from the newest week, `year_ago`
from the week closest to 365 days earlier, `asof` from the survey date.

Run weekly by .github/workflows/pmms-weekly.yml, which commits the change and
dispatches the rebuild. The scheduled refresh's stale-data alert
(alert_stale_data.py) emails if `asof` ever ages past 10 days — a weekly
series more than a week and a half old means this job is broken.
"""

import argparse
import csv
import io
import json
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
META = ROOT / "web" / "data" / "meta.json"
CSV_URL = "https://www.freddiemac.com/pmms/docs/PMMS_history.csv"
STALE_DAYS = 10   # weekly series; >10 days means the refresh job is broken


def fetch_series():
    """[(date, rate30)] ascending, from Freddie Mac's published history."""
    from fetch_data import _ssl_context   # certifi-less macOS Pythons (see audit-og.py)
    req = urllib.request.Request(CSV_URL, headers={
        "User-Agent": "shouldisellyet-ops/1.0 (+https://shouldisellyet.com)"})
    with urllib.request.urlopen(req, timeout=60, context=_ssl_context()) as r:
        text = r.read().decode("utf-8", "replace")
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            d = datetime.strptime(row["date"].strip(), "%m/%d/%Y").date()
            v = float(row["pmms30"])
        except (KeyError, ValueError):
            continue
        # Sanity fence: a parse that yields 0.66 or 66 must never ship as
        # "today's rate" on a paid report.
        if 1.0 <= v <= 25.0:
            out.append((d, v))
    return out


def refresh():
    series = fetch_series()
    if not series:
        print("::error::PMMS fetch parsed zero usable rows — meta.json untouched")
        return 1
    now_d, now_v = series[-1]
    target = now_d - timedelta(days=365)
    ago_d, ago_v = min(series, key=lambda t: abs((t[0] - target).days))
    if abs((ago_d - target).days) > 21:
        print("::error::no PMMS week within 21 days of a year ago — meta.json untouched")
        return 1
    meta = json.loads(META.read_text())
    old = meta.get("national", {}).get("mortgage")
    meta.setdefault("national", {})["mortgage"] = {
        "now": now_v, "year_ago": ago_v, "asof": now_d.isoformat(),
    }
    META.write_text(json.dumps(meta, separators=(",", ":")) + "\n")
    print(f"PMMS 30-yr: {now_v}% as of {now_d} (year ago {ago_v}% on {ago_d}); "
          f"was {old}")
    return 0


def check():
    """Freshness only — used by the stale-data alert path."""
    meta = json.loads(META.read_text())
    asof = (meta.get("national", {}).get("mortgage") or {}).get("asof")
    if not asof:
        print("meta.json carries no mortgage asof")
        return 1
    age = (date.today() - date.fromisoformat(asof)).days
    print(f"PMMS asof {asof} — {age} days old (line: {STALE_DAYS})")
    return 1 if age > STALE_DAYS else 0


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args(argv)
    return check() if args.check else refresh()


if __name__ == "__main__":
    sys.exit(main())
