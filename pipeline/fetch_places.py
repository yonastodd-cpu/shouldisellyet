#!/usr/bin/env python3
"""Regenerate pipeline/data/zip_places.csv from the GeoNames US postal export.

    Source   https://download.geonames.org/export/zip/US.zip
    Licence  CC BY 4.0 — credit GeoNames; their readme accepts a link to
             www.geonames.org. See docs/ATTRIBUTION.md.

WHY THIS IS NOT PART OF THE SCHEDULED REFRESH
---------------------------------------------
build_pages.py reads this file from disk and makes no network call, by design
(see its module docstring). That hermetic property is worth keeping: the page
build runs on EVERY deploy, and a build that reaches the network on every
deploy can fail on a deploy that changed nothing but CSS.

So place names are refreshed deliberately, not automatically. US ZIP→city
assignments change on the order of a few hundred rows a year — this is not a
monthly feed like Redfin, and treating it as one would add a failure mode to
every deploy in exchange for nothing.

    python3 pipeline/fetch_places.py --check    # drift report, writes nothing
    python3 pipeline/fetch_places.py            # rewrite, refusing on removals
    python3 pipeline/fetch_places.py --force    # rewrite even if ZIPs vanish

THE MILITARY-CODE FILTER
------------------------
GeoNames carries ~509 APO/FPO postal codes with an empty state AND county.
They are dropped: overseas military addresses have no housing market, and the
output schema requires a state. The rule is exactly "keep rows with a state" —
not a hand-maintained exclusion list, so it stays correct as GeoNames changes.

COLUMN MAPPING
--------------
US.txt is tab-delimited, no header, 12 fields. We keep four:
    2 → zip    3 → city    5 → state (2-letter)    6 → county
Where a ZIP appears more than once, the FIRST row wins — the output is one
primary place per ZIP, which is what the consumers expect.
"""

import argparse
import csv
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

SOURCE_URL = "https://download.geonames.org/export/zip/US.zip"
MEMBER = "US.txt"
OUT = Path(__file__).parent / "data" / "zip_places.csv"
HEADER = ["zip", "city", "state", "county"]


def _ssl_context():
    """Mirrors fetch_data.py: verifying context that still works on stock
    macOS pythons with no default CA bundle. Verification is never disabled."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    system = Path("/etc/ssl/cert.pem")
    if system.exists():
        return ssl.create_default_context(cafile=str(system))
    return ssl.create_default_context()


def download(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "shouldisellyet-pipeline"})
    with urllib.request.urlopen(req, timeout=120, context=_ssl_context()) as r:
        return r.read()


def parse(blob: bytes) -> dict:
    """→ {zip: (city, state, county)}, military codes dropped."""
    # A truncated download or an error page served with a 200 both arrive here
    # as bytes. Say which, rather than surfacing a zipfile traceback.
    try:
        zf = zipfile.ZipFile(io.BytesIO(blob))
    except zipfile.BadZipFile:
        head = blob[:120].decode("utf-8", "replace").strip()
        raise SystemExit(f"  ! not a zip archive ({len(blob):,} bytes). Starts: {head!r}")
    with zf as z:
        if MEMBER not in z.namelist():
            raise SystemExit(f"  ! {MEMBER} not in the archive: {z.namelist()}")
        raw = z.read(MEMBER).decode("utf-8", "replace")
    places, dropped, dupes = {}, 0, 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        f = line.split("\t")
        if len(f) < 6:
            continue
        zc, city, state, county = f[1], f[2], f[4], f[5]
        if not state:                      # APO/FPO — no state, no market
            dropped += 1
            continue
        if zc in places:                   # one primary place per ZIP
            dupes += 1
            continue
        places[zc] = (city, state, county)
    print(f"  parsed {len(places):,} ZIPs  "
          f"({dropped:,} military codes dropped, {dupes:,} duplicate rows collapsed)")
    return places


def read_existing(path: Path) -> dict:
    if not path.exists():
        return {}
    out = {}
    with path.open(newline="", encoding="utf-8") as f:
        r = csv.reader(f)
        head = next(r, None)
        if head != HEADER:
            print(f"  ! existing header is {head}, expected {HEADER}")
        for row in r:
            if len(row) == 4:
                out[row[0]] = tuple(row[1:])
    return out


def write(path: Path, places: dict) -> None:
    tmp = path.with_suffix(".csv.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(HEADER)
        for zc in sorted(places):
            w.writerow([zc, *places[zc]])
    tmp.replace(path)


def diff(old: dict, new: dict) -> tuple:
    added = sorted(new.keys() - old.keys())
    removed = sorted(old.keys() - new.keys())
    changed = sorted(z for z in old.keys() & new.keys() if old[z] != new[z])
    return added, removed, changed


def report(old, new, added, removed, changed) -> None:
    print(f"\n  committed : {len(old):,} ZIPs")
    print(f"  upstream  : {len(new):,} ZIPs")
    print(f"  added     : {len(added):,}")
    print(f"  REMOVED   : {len(removed):,}")
    print(f"  changed   : {len(changed):,}")
    for label, rows in (("added", added), ("REMOVED", removed)):
        for z in rows[:10]:
            src = new.get(z) or old.get(z)
            print(f"     {label:8} {z}  {src}")
        if len(rows) > 10:
            print(f"     … and {len(rows) - 10:,} more")
    for z in changed[:10]:
        print(f"     changed  {z}  {old[z]} → {new[z]}")
    if len(changed) > 10:
        print(f"     … and {len(changed) - 10:,} more")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true",
                    help="report drift and exit; never writes. Exit 1 if drift.")
    ap.add_argument("--force", action="store_true",
                    help="write even when ZIPs would be removed")
    ap.add_argument("--input", help="a local US.zip instead of downloading")
    args = ap.parse_args()

    print(f"GeoNames US postal codes — {SOURCE_URL}")
    blob = Path(args.input).read_bytes() if args.input else download(SOURCE_URL)
    print(f"  {len(blob):,} bytes")
    new = parse(blob)
    if not new:
        print("  ! parsed zero rows — refusing to touch the committed file")
        return 2

    old = read_existing(OUT)
    added, removed, changed = diff(old, new)
    report(old, new, added, removed, changed)

    if not (added or removed or changed):
        print("\n  identical to the committed file — nothing to do")
        return 0

    if args.check:
        print("\n  --check: drift found, nothing written")
        return 1

    # A ZIP disappearing upstream means every generated page for it loses its
    # city name. That is a real regression and should be a decision, not a
    # side effect of running a refresh script.
    if removed and not args.force:
        print(f"\n  ! {len(removed):,} ZIPs would be REMOVED. Nothing written.")
        print("    Review the list above, then re-run with --force to accept.")
        return 1

    write(OUT, new)
    print(f"\n  wrote {OUT} — {len(new):,} ZIPs")
    print("    Update the 'Verified' date in docs/ATTRIBUTION.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
