#!/usr/bin/env python3
"""Freeze which ZIPs have a standing page — pipeline/data/page_manifest.csv.

    python3 pipeline/build_manifest.py [--check]

WHY THIS FILE EXISTS. Until now the set of published URLs was a side effect of
a vendor's monthly coverage: build_pages globbed web/data/zips/*.json and
whatever passed an eligibility test built from vendor metrics got a directory.
That was workable while the metrics lived in the repo. They are leaving, and
the eligibility test cannot be recomputed without them — so the URL set has to
become a committed, reviewable contract instead of an emergent property.

That is also the safer arrangement. A build that loses its data now emits the
same pages carrying the "being rebuilt" notice, where before it would have
emitted nothing and the deploy would have DELETED ~23,000 live URLs.

WHAT IS IN IT: zip,state. Nothing else. No price, no days-on-market, no
rating. A ZIP code and its state are postal geography.

RUN IT ONCE, from data that still has the metrics. --check re-derives and
compares without writing, which is how CI can prove the file still matches the
rule that produced it while that data is still around.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
# NOT imported at module level: build_pages imports read_manifest from here,
# so a top-level import either way round is a cycle. This module is the one
# that can defer, because only its main() needs place names — read_manifest,
# the half build_pages wants, needs nothing.

ROOT = Path(__file__).resolve().parents[1]
ZIPS = ROOT / "web" / "data" / "zips"
OUT = Path(__file__).parent / "data" / "page_manifest.csv"


def eligible(entries, places):
    """The rule build_pages.main() has always used, in one place.

    Kept verbatim rather than simplified: this is the last time it can run
    against the data it was written for, so it must reproduce exactly the set
    of pages the site publishes today.
    """
    out, skipped = [], {}
    for z, e in sorted(entries.items()):
        m = e.get("m") or {}
        if any(r and r[0] == "insufficient_data" for r in e.get("r") or []):
            skipped["insufficient_verdict"] = skipped.get("insufficient_verdict", 0) + 1
            continue
        need = (("spy", "dom", "domy", "invy") if e.get("b")
                else ("mos", "spy", "dom", "domy"))
        if any(m.get(k) is None for k in need):
            skipped["incomplete_dials"] = skipped.get("incomplete_dials", 0) + 1
            continue
        if z not in places:
            skipped["no_city_name"] = skipped.get("no_city_name", 0) + 1
            continue
        out.append((z, e.get("st") or places[z][1]))
    return out, skipped


def load_entries(zips=ZIPS):
    out = {}
    for f in sorted(Path(zips).glob("*.json")):
        out.update(json.loads(f.read_text()))
    return out


def read_manifest(path=OUT):
    if not Path(path).exists():
        return []
    return [(r["zip"], r["state"]) for r in csv.DictReader(open(path, encoding="utf-8"))]


def write_manifest(rows, path=OUT):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["zip", "state"])
        w.writerows(rows)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Freeze the standing-page URL set")
    ap.add_argument("--zips", default=str(ZIPS))
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true",
                    help="re-derive and compare; write nothing")
    args = ap.parse_args(argv)

    from build_pages import load_places      # deferred; see the note above
    entries = load_entries(args.zips)
    rows, skipped = eligible(entries, load_places())
    print(f"scored ZIPs: {len(entries):,}")
    for k, v in sorted(skipped.items()):
        print(f"  skipped {k}: {v:,}")
    print(f"standing pages: {len(rows):,}")

    if args.check:
        have = read_manifest(args.out)
        if have == rows:
            print("manifest matches the derived set")
            return 0
        only_file = set(have) - set(rows)
        only_derived = set(rows) - set(have)
        print(f"MISMATCH: {len(only_file):,} in file only, {len(only_derived):,} derived only")
        for z, st in list(only_file)[:5]:
            print(f"  file only: {z} {st}")
        for z, st in list(only_derived)[:5]:
            print(f"  derived only: {z} {st}")
        return 1

    write_manifest(rows, args.out)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
