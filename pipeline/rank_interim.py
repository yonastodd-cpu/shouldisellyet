#!/usr/bin/env python3
"""ShouldISellYet — interim Tier A/B/C ranking, built without demand data.

WHY THIS EXISTS, AND WHAT IT IS NOT. Phase 1 of the RentCast migration wants
the paid ZIPs ordered by 90-day organic impressions. That ordering cannot
exist yet: every /zip/ page serves noindex, so no ZIP page can appear in
search results, so none can accrue impressions — the ranking that decides
which pages to un-noindex could only be produced after they are un-noindexed
(docs/migration/PHASE1-PLUS.md, correction 1).

So this ranks on **supply**, not demand: how much housing a ZIP has, and
whether its market is currently measurable at all. It answers "is this ZIP
worth a paid call" — never "do people search for this ZIP." Any page or
methodology note explaining why 1,000 ZIPs were chosen must say which of the
two it used.

    python3 pipeline/rank_interim.py [--tier-a 1000] [--tier-b 4000]

Everything it reads is committed; it makes no network call and spends no
quota. Replace it the day Search Console has real impressions
(pipeline/fetch_gsc.py) — that is an upgrade, not a rewrite: same output
columns, better ordering.

GATES, in the order applied. A ZIP is attributed to the FIRST gate it
fails, so the counts are "why this ZIP dropped out," not independent totals.

  no_page       No standing page — build_pages.py would skip it anyway
                (insufficient verdict, incomplete dials, or no city name).
                Paying for a ZIP with no page to put it on is the purest
                form of wasted spend.
  no_acs        No ZCTA in the Census file. PO-box-only and point ZIPs have
                no housing geography at all, which is itself the answer.
  below_floor   Fewer than --floor housing units (default 500, the plan's
                figure). Thin stock produces thin statistics.
  no_fhfa       No FHFA index. Without it there is no public-domain price
                anchor and no way to backtest the rebuilt formula on this
                ZIP, which makes it a poor place to spend the first dollars.
  no_rdc        No Realtor.com row — no independent read on whether the
                market is live right now.
  rdc_flagged   Realtor.com set quality_flag. The flag marks unreliable
                comparability, which is exactly what a reading needs.

ORDERING. Owner-occupied units, descending — the closest free proxy to "how
many people here could plausibly ask whether to sell." Ties break on active
listings, then ZIP, so the output is stable across runs.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from build_pages import load_places

ROOT = Path(__file__).resolve().parents[1]
ZIPS = ROOT / "web" / "data" / "zips"
ACS = Path(__file__).parent / "acs_zip.csv"
OUT = Path(__file__).parent / "tier_interim.csv"

GATES = ["no_page", "no_acs", "below_floor", "no_fhfa", "no_rdc", "rdc_flagged"]


def load_acs(path=ACS):
    """{zip: (units, owner_or_None)} from pipeline/acs_zip.csv."""
    out = {}
    for r in csv.DictReader(open(path, encoding="utf-8")):
        try:
            units = int(r["units"])
        except (KeyError, TypeError, ValueError):
            continue
        owner = r.get("owner") or ""
        out[r["zip"]] = (units, int(owner) if owner.strip().isdigit() else None)
    return out


def load_entries(zips=ZIPS):
    """{zip: entry} across the committed per-state files.

    THESE INPUTS NO LONGER EXIST. This script ranks on the Redfin-era record
    shape — it needs `mos` and the Realtor.com `x` block, and it read them from
    web/data/zips/{STATE}.json. That directory was removed on 2026-08-20 when
    provisioning moved to one file per ZIP, and the records themselves were
    blanked long before that: a per-ZIP file today is {"st": "MD"} with no
    metrics and no cross-check. So there is nothing here to rank.

    A missing directory used to be silent. Path.glob on a path that does not
    exist yields nothing rather than raising, so load_entries returned {},
    build returned zero rows, and main() then wrote that empty result over
    tier_interim.csv — the frozen 10,633-row ordering that decides which ZIPs
    are worth paying RentCast for. One accidental run would have destroyed it
    with no error at all.
    """
    d = Path(zips)
    if not d.is_dir():
        raise SystemExit(
            f"rank_interim: input directory {d} does not exist.\n"
            "This script ranks on the withdrawn Redfin record shape (months of "
            "supply + the Realtor.com cross-check block); those records were "
            "blanked and the per-state files removed. Re-ranking on the "
            "active-listing basis is Phase 5 work.\n"
            "REFUSING TO RUN: continuing would overwrite pipeline/"
            "tier_interim.csv, the frozen ordering that decides paid API spend.")
    out = {}
    for f in sorted(d.glob("*.json")):
        out.update(json.loads(f.read_text()))
    return out


def has_standing_page(entry, zip_code, places):
    """Mirror of build_pages.py's eligibility test (see its main(), the
    `eligible` loop). Kept in step by test_rank_interim, which runs both
    over the real committed data and asserts the same count — a ZIP we pay
    for and then cannot render is the failure this guards."""
    m = entry.get("m") or {}
    if any(r and r[0] == "insufficient_data" for r in entry.get("r") or []):
        return False
    need = (("spy", "dom", "domy", "invy") if entry.get("b")
            else ("mos", "spy", "dom", "domy"))
    if any(m.get(k) is None for k in need):
        return False
    return zip_code in places


def gate(zip_code, entry, acs, places, floor=500):
    """The first gate this ZIP fails, or None if it survives."""
    if not has_standing_page(entry, zip_code, places):
        return "no_page"
    a = acs.get(zip_code)
    if not a:
        return "no_acs"
    units, _ = a
    if units < floor:
        return "below_floor"
    if not entry.get("f"):
        return "no_fhfa"
    x = entry.get("x")
    if not x:
        return "no_rdc"
    if x.get("q") == 1:
        return "rdc_flagged"
    return None


def build(entries, acs, places, floor=500):
    """(ranked rows, gate counts). Ranked by owner-occupied units desc, then
    active listings desc, then ZIP asc for a stable order."""
    rows, dropped = [], {g: 0 for g in GATES}
    for z, e in entries.items():
        why = gate(z, e, acs, places, floor)
        if why:
            dropped[why] += 1
            continue
        units, owner = acs[z]
        x = e.get("x") or {}
        rows.append({
            "zip": z,
            "state": e.get("st", ""),
            "owner": owner if owner is not None else 0,
            "units": units,
            "listings": int(x.get("inv") or 0),
            "fhfa_a1": (e.get("f") or {}).get("a1", ""),
        })
    rows.sort(key=lambda r: (-r["owner"], -r["listings"], r["zip"]))
    return rows, dropped


def assign_tiers(rows, tier_a=1000, tier_b=4000):
    """A = the paid head, B = the rest of the paid tier, C = free sources."""
    for i, r in enumerate(rows):
        r["rank"] = i + 1
        r["tier"] = "A" if i < tier_a else ("B" if i < tier_a + tier_b else "C")
    return rows


FIELDS = ["rank", "tier", "zip", "state", "owner", "units", "listings", "fhfa_a1"]


def write(path, rows):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def report(rows, dropped, tier_a, tier_b):
    total_owner = sum(r["owner"] for r in rows) or 1
    print(f"eligible: {len(rows):,} ZIPs")
    for g in GATES:
        if dropped[g]:
            print(f"  dropped {g}: {dropped[g]:,}")
    for label, n in (("A", tier_a), ("A+B", tier_a + tier_b)):
        share = sum(r["owner"] for r in rows[:n]) / total_owner
        print(f"tier {label} ({min(n, len(rows)):,} ZIPs): {share:.1%} of "
              f"eligible owner-occupied stock")
    if len(rows) < tier_a + tier_b:
        print(f"WARNING: only {len(rows):,} ZIPs clear the gates — the paid "
              f"tier of {tier_a + tier_b:,} cannot be filled with quality ZIPs.")
    print()
    print("This is a SUPPLY ranking, not a demand ranking. Housing stock is "
          "far more evenly spread than search demand, so the curve here is "
          "flat where an impressions curve would be steep — do not quote its "
          "concentration as if it were traffic. Replace with fetch_gsc.py "
          "output once impressions exist.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Interim Tier A/B/C ranking (supply-based)")
    ap.add_argument("--tier-a", type=int, default=1000)
    ap.add_argument("--tier-b", type=int, default=4000)
    ap.add_argument("--floor", type=int, default=500, help="minimum housing units")
    ap.add_argument("--acs", default=str(ACS))
    ap.add_argument("--zips", default=str(ZIPS))
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args(argv)

    rows, dropped = build(load_entries(args.zips), load_acs(args.acs),
                          load_places(), args.floor)
    assign_tiers(rows, args.tier_a, args.tier_b)
    report(rows, dropped, args.tier_a, args.tier_b)
    # Belt and braces. The guard in load_entries covers the way this actually
    # broke, but any future path that yields nothing must not be able to write
    # an empty ranking over the real one.
    if not rows:
        raise SystemExit(
            f"rank_interim: ranked 0 ZIPs — refusing to write {args.out}. "
            "An empty ranking would erase the ordering that targets paid API "
            "calls. Check the input directory before re-running.")
    write(args.out, rows)
    print(f"wrote {args.out} ({len(rows):,} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
