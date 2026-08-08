#!/usr/bin/env python3
"""Build pipeline/data/zip_cbsa.csv — ZIP → metro (CBSA) crosswalk.

    python3 pipeline/fetch_cbsa.py [--zcta-county PATH] [--delineation PATH]

Two public-domain Census Bureau inputs (both US Government works, no
licence terms to carry — cited in DATA.md as a courtesy and for
reproducibility):

  1. tab20_zcta520_county20_natl.txt — 2020 ZCTA ↔ county relationship file,
     with the land area of each overlap. A ZCTA can straddle counties; the
     county with the LARGEST overlapping land area wins. ZCTAs approximate
     ZIP codes (they are built from them) — the divergence is real but small,
     and it is the standard, documented compromise every ZIP-level analysis
     makes, because the USPS does not publish ZIP geography at all.
  2. list1_2023.xlsx — the OMB/Census CBSA *delineation file*: which counties
     make up each metro/micropolitan area, its title, and which of the two it
     is. This is the file that DEFINES "metro area" — using it means our
     metro names match what the press already calls these places.

Chain: ZIP(≈ZCTA) → county (max overlap) → CBSA (delineation).

Output columns: zip,cbsa,title,is_metro
  is_metro 1 = Metropolitan Statistical Area, 0 = Micropolitan. ZIPs whose
  county belongs to no CBSA (rural) are simply absent — the research
  aggregation buckets them as "outside metro areas" by their absence.

Run ONCE per delineation revision (OMB revises roughly every 5 years;
match the vintage noted in DATA.md). Requires openpyxl, like fetch_fhfa.py.
"""

import argparse
import csv
import io
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_data import _ssl_context

ZCTA_COUNTY_URL = ("https://www2.census.gov/geo/docs/maps-data/data/rel2020/"
                   "zcta520/tab20_zcta520_county20_natl.txt")
DELINEATION_URL = ("https://www2.census.gov/programs-surveys/metro-micro/"
                   "geographies/reference-files/2023/delineation-files/list1_2023.xlsx")
OUT = Path(__file__).parent / "data" / "zip_cbsa.csv"


def fetch(source, binary=False):
    if str(source).startswith("http"):
        req = urllib.request.Request(source, headers={"User-Agent": "shouldisellyet-pipeline"})
        data = urllib.request.urlopen(req, timeout=300, context=_ssl_context()).read()
        return data if binary else data.decode("utf-8-sig", "replace")
    p = Path(source)
    return p.read_bytes() if binary else p.read_text(encoding="utf-8-sig")


def best_county_per_zcta(text):
    """{zcta: county_fips} by largest overlapping land area."""
    rdr = csv.DictReader(io.StringIO(text), delimiter="|")
    area_field = next((f for f in rdr.fieldnames if f.startswith("AREALAND_PART")), None)
    if not area_field:
        raise SystemExit("relationship file: AREALAND_PART column not found "
                         f"(columns: {rdr.fieldnames})")
    best = {}
    for row in rdr:
        z = (row.get("GEOID_ZCTA5_20") or "").strip()
        c = (row.get("GEOID_COUNTY_20") or "").strip()
        if not (z.isdigit() and len(z) == 5 and len(c) == 5):
            continue  # county rows with no ZCTA overlap, and vice versa
        try:
            a = int(row.get(area_field) or 0)
        except ValueError:
            a = 0
        if z not in best or a > best[z][1]:
            best[z] = (c, a)
    return {z: c for z, (c, a) in best.items()}


def county_to_cbsa(xlsx_bytes):
    """{county_fips: (cbsa_code, title, is_metro)} from the delineation file."""
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(xlsx_bytes), read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    header = None
    for row in rows:
        cells = [str(c).strip() if c is not None else "" for c in row]
        if any("CBSA Code" in c for c in cells):
            header = cells
            break
    if not header:
        raise SystemExit("delineation file: header row with 'CBSA Code' not found")
    idx = {name: i for i, name in enumerate(header)}

    def col(row, *names):
        for n in names:
            if n in idx and idx[n] < len(row) and row[idx[n]] is not None:
                return str(row[idx[n]]).strip()
        return ""

    out = {}
    for row in rows:
        cbsa = col(row, "CBSA Code")
        title = col(row, "CBSA Title")
        kind = col(row, "Metropolitan/Micropolitan Statistical Area")
        st = col(row, "FIPS State Code").zfill(2)
        co = col(row, "FIPS County Code").zfill(3)
        if not (cbsa.isdigit() and len(st) == 2 and len(co) == 3 and st.isdigit()):
            continue
        out[st + co] = (cbsa, title, 1 if kind.lower().startswith("metro") else 0)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--zcta-county", default=ZCTA_COUNTY_URL)
    ap.add_argument("--delineation", default=DELINEATION_URL)
    args = ap.parse_args()

    print("ZCTA↔county relationship…")
    z2c = best_county_per_zcta(fetch(args.zcta_county))
    print(f"  {len(z2c):,} ZCTAs mapped to a county")

    print("CBSA delineation…")
    c2m = county_to_cbsa(fetch(args.delineation, binary=True))
    print(f"  {len(c2m):,} counties belong to a CBSA")

    n_metro = n_micro = 0
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["zip", "cbsa", "title", "is_metro"])
        for z in sorted(z2c):
            hit = c2m.get(z2c[z])
            if not hit:
                continue  # rural county, no CBSA — deliberately absent
            cbsa, title, is_metro = hit
            n_metro += is_metro
            n_micro += 1 - is_metro
            w.writerow([z, cbsa, title, is_metro])
    print(f"wrote {OUT} — {n_metro:,} metro + {n_micro:,} micro ZIP rows "
          f"({len(z2c) - n_metro - n_micro:,} ZCTAs outside any CBSA)")


if __name__ == "__main__":
    main()
