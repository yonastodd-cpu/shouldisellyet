#!/usr/bin/env python3
"""Which ZIPs are worth a paid call — rebuilt on data that still exists.

    python3 pipeline/rank_v2.py            # writes pipeline/tier_v2.csv
    python3 pipeline/rank_v2.py --check    # re-derive and compare, write nothing

WHY A REWRITE. rank_interim.py ranked from the Redfin-era per-state records and
gated on six things. Two of them were Realtor.com:

    no_rdc        No Realtor.com row — no independent read on the market.
    rdc_flagged   Realtor.com set quality_flag.

Those two excluded 20874 Germantown MD — 14,842 owner-occupied homes, a
standing page, an FHFA index, a place name, everything else passing — from ever
being bought. Its neighbour 20878 ranks 170th. 20906 Silver Spring, the ZIP the
site's own sample report is written about, was excluded the same way. Across the
country the old ranking covered 10,633 ZIPs; this one covers 18,953, and the
difference is very largely markets a third party did not happen to carry.

A cross-check is a reason to trust a reading. It is not a reason to decide a
market does not exist.

WHAT THIS RANKS FROM. Only committed, public-domain inputs: the page manifest
(ours), the Census ACS housing table, the FHFA ZIP index, and the GeoNames
place list. No vendor data is read, which is also why this one still runs —
rank_interim's inputs were withdrawn and it now refuses to start.

THE GATES THAT REMAIN, all of them about whether a page could exist at all:

    no_page       No standing page. Paying for a ZIP with nowhere to put the
                  reading is the purest form of wasted spend.
    no_place      No city name, so the page cannot be titled or linked.
    no_acs        No ZCTA in the Census file. PO-box and point ZIPs have no
                  housing geography, which is itself the answer.
    below_floor   Fewer than --floor owner-occupied homes (default 500).
                  Thin stock produces thin statistics.

FHFA IS RECORDED, NOT REQUIRED. The old ranking dropped 1,856 ZIPs for having
no FHFA index, on the reasoning that without a public-domain price anchor there
is no way to backtest the formula there — a fair argument about where to spend
the FIRST dollars, and a poor one for excluding a market permanently. The
column is kept so a backtest can filter on it; the gate is gone.

ORDERING. Owner-occupied homes, descending — the closest free proxy for "how
many people here could plausibly ask whether to sell". Ties break on total
housing units, then on ZIP, so the output is stable across runs and depends on
nothing that changes. The old tiebreak was Realtor.com's active-listing count,
which is the same coupling in a quieter place.

ALREADY-BOUGHT ZIPS ARE NOT RE-BOUGHT. fetch_rentcast skips any ZIP its ledger
marks done or no_data, so re-pointing at this file spends nothing on the 5,000
already held. What was paid for at what tier is recorded on market_jobs.tier,
not inferred from whichever ranking is current.

Run: python3 -m pytest pipeline/test_rank_v2.py -q
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
HERE = Path(__file__).parent
MANIFEST = HERE / "data" / "page_manifest.csv"
ACS = HERE / "acs_zip.csv"
FHFA = HERE / "fhfa_zip.csv"
PLACES = HERE / "data" / "zip_places.csv"
OUT = HERE / "tier_v2.csv"

GATES = ["no_page", "no_place", "no_acs", "below_floor"]
FIELDS = ["rank", "tier", "zip", "state", "owner", "units", "has_fhfa"]


def _int(v):
    v = str(v or "").strip()
    return int(v) if v.isdigit() else 0


def load_manifest(path=MANIFEST):
    """{zip: state} for ZIPs with a standing page."""
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    if not rows:
        raise SystemExit(f"rank_v2: {path} is empty — refusing to rank nothing.")
    return {r["zip"]: r.get("state", "") for r in rows if r.get("page") == "1"}


def load_acs(path=ACS):
    return {r["zip"]: r for r in csv.DictReader(open(path, encoding="utf-8"))}


def load_places(path=PLACES):
    return {r["zip"] for r in csv.DictReader(open(path, encoding="utf-8"))}


def load_fhfa(path=FHFA):
    """ZIPs with an FHFA index. Recorded, never gated on."""
    p = Path(path)
    if not p.exists():
        return set()
    return {r["zip"] for r in csv.DictReader(open(p, encoding="utf-8")) if r.get("zip")}


def build(manifest, acs, places, fhfa, floor=500):
    """(rows, dropped) — ranked best first, with a reason count per gate."""
    rows, dropped = [], {g: 0 for g in GATES}
    for zip_code, state in manifest.items():
        if zip_code not in places:
            dropped["no_place"] += 1
            continue
        a = acs.get(zip_code)
        if not a:
            dropped["no_acs"] += 1
            continue
        owner, units = _int(a.get("owner")), _int(a.get("units"))
        if owner < floor:
            dropped["below_floor"] += 1
            continue
        rows.append({"zip": zip_code, "state": state, "owner": owner,
                     "units": units, "has_fhfa": 1 if zip_code in fhfa else 0})
    rows.sort(key=lambda r: (-r["owner"], -r["units"], r["zip"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows, dropped


def assign_tiers(rows, tier_a=1000, tier_b=4000):
    for r in rows:
        r["tier"] = ("A" if r["rank"] <= tier_a
                     else "B" if r["rank"] <= tier_a + tier_b else "C")


def write(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in FIELDS})


def main(argv=None):
    ap = argparse.ArgumentParser(description="Paid-call ranking, no vendor inputs")
    ap.add_argument("--tier-a", type=int, default=1000)
    ap.add_argument("--tier-b", type=int, default=4000)
    ap.add_argument("--floor", type=int, default=500,
                    help="minimum owner-occupied homes")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--check", action="store_true",
                    help="re-derive and compare against the file; write nothing")
    args = ap.parse_args(argv)

    rows, dropped = build(load_manifest(), load_acs(), load_places(),
                          load_fhfa(), args.floor)
    assign_tiers(rows, args.tier_a, args.tier_b)

    print(f"ranked: {len(rows):,} ZIPs")
    for g in GATES:
        if dropped[g]:
            print(f"  dropped {g}: {dropped[g]:,}")
    no_fhfa = sum(1 for r in rows if not r["has_fhfa"])
    print(f"  ranked without an FHFA index: {no_fhfa:,} (recorded, not excluded)")

    if args.check:
        have = [(r["zip"], r["tier"]) for r in
                csv.DictReader(open(args.out, encoding="utf-8"))]
        want = [(r["zip"], r["tier"]) for r in rows]
        if have == want:
            print("tier file matches the derived ranking")
            return 0
        print(f"MISMATCH: file has {len(have):,} rows, derived {len(want):,}")
        return 1

    if not rows:
        raise SystemExit(
            f"rank_v2: ranked 0 ZIPs — refusing to write {args.out}. An empty "
            "ranking would erase the ordering that targets paid API calls.")
    write(args.out, rows)
    print(f"wrote {args.out} ({len(rows):,} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
