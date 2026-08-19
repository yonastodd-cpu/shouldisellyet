#!/usr/bin/env python3
"""ShouldISellYet — ACS housing stock by ZIP (ZCTA), for the interim tiering.

Phase 1 of the RentCast migration needs a housing-unit floor and, while no
organic impression data exists (see docs/migration/SEARCH-CONSOLE.md), a
defensible way to order the ZIPs worth paying for. Owner-occupied units are
the closest free proxy to "how many people here could plausibly ask whether
to sell."

Run ONCE per ACS vintage (Census releases 5-year estimates annually):

    python3 pipeline/fetch_acs.py [--year 2023] [--out pipeline/acs_zip.csv]
    python3 pipeline/fetch_acs.py --units FILE --tenure FILE   # local .dat

Output: zip,units,owner
  units  B25001_E001 — total housing units
  owner  B25003_E002 — owner-occupied units

SOURCE, AND WHY THIS PATH. api.census.gov now rejects keyless requests
("Missing Key"), and a key needs a signup. The table-based Summary File is
the same data as flat downloads with no key and no terms — a US Government
work, public domain, the cleanest licence posture available to this project
and the reason Phase 3 anchors Tier C on Census and FHFA rather than on a
vendor feed.

ZCTAs are not ZIPs. They approximate them, they are the only ZIP-shaped
geography the Census publishes, and PO-box-only ZIPs have no ZCTA at all —
which is itself the signal that such a ZIP can never carry a housing
reading. Same documented compromise fetch_cbsa.py already makes.

Margins of error are in the source and deliberately dropped: this feeds a
size ordering and a floor, not a published statistic.
"""

import argparse
import csv
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_data import _ssl_context

BASE = ("https://www2.census.gov/programs-surveys/acs/summary_file/{year}/"
        "table-based-SF/data/5YRData/acsdt5y{year}-{table}.dat")
ZCTA_PREFIX = "860Z200US"          # the GEO_ID stem for five-digit ZCTAs
OUT = Path(__file__).parent / "acs_zip.csv"


def fetch(source, timeout=600):
    if str(source).startswith("http"):
        req = urllib.request.Request(source, headers={
            "User-Agent": "shouldisellyet-pipeline"})
        return urllib.request.urlopen(
            req, timeout=timeout, context=_ssl_context()).read().decode("utf-8", "replace")
    return Path(source).read_text(encoding="utf-8", errors="replace")


def parse_dat(text, column):
    """A pipe-delimited ACS .dat → {zcta: int}. Non-ZCTA geographies (states,
    counties, tracts — the file holds every level) are skipped by prefix.

    Suppressed cells arrive as '-' or empty and are dropped rather than
    zeroed: a ZIP with no published estimate is unknown, not empty, and
    zeroing it would silently sink it below the floor.
    """
    out = {}
    for i, line in enumerate(text.splitlines()):
        if not line:
            continue
        parts = line.split("|")
        if i == 0:
            try:
                col = parts.index(column)
            except ValueError:
                raise SystemExit(f"{column} not in header: {parts}")
            continue
        geo = parts[0]
        if not geo.startswith(ZCTA_PREFIX) or len(parts) <= col:
            continue
        z = geo[len(ZCTA_PREFIX):]
        if not (len(z) == 5 and z.isdigit()):
            continue
        v = parts[col].strip()
        try:
            out[z] = int(float(v))
        except ValueError:
            continue           # '-', '', '(X)' — suppressed, not zero
    return out


def merge(units, owner):
    """One row per ZCTA that has a total-units estimate. Owner-occupied can
    legitimately be missing where total units is not, so it is left blank
    rather than assumed zero — blank means unknown downstream."""
    rows = []
    for z in sorted(units):
        u = units[z]
        if u <= 0:
            continue           # ZCTAs with no housing stock at all
        rows.append({"zip": z, "units": u, "owner": owner.get(z, "")})
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description="ACS housing stock by ZIP (ZCTA)")
    ap.add_argument("--year", default="2023")
    ap.add_argument("--units", help="local acsdt5y*-b25001.dat")
    ap.add_argument("--tenure", help="local acsdt5y*-b25003.dat")
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    u = parse_dat(fetch(args.units or BASE.format(year=args.year, table="b25001")),
                  "B25001_E001")
    o = parse_dat(fetch(args.tenure or BASE.format(year=args.year, table="b25003")),
                  "B25003_E002")
    rows = merge(u, o)

    out = Path(args.out)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["zip", "units", "owner"])
        w.writeheader()
        w.writerows(rows)
    have_owner = sum(1 for r in rows if r["owner"] != "")
    print(f"ACS {args.year}: {len(u):,} ZCTAs with units, {len(o):,} with tenure")
    print(f"wrote {out} — {len(rows):,} rows, {have_owner:,} with owner-occupied")
    return 0


if __name__ == "__main__":
    sys.exit(main())
