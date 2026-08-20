#!/usr/bin/env python3
"""Stage and release Phase 4 tranches.

    python3 pipeline/promote_tranche.py --name tranche-1 --tier A --count 1000
    python3 pipeline/promote_tranche.py --name tranche-1 --release
    python3 pipeline/promote_tranche.py --status

Two steps on purpose. STAGING picks the ZIPs and writes them to
pipeline/tranches.json with no release timestamp — nothing changes on the
site, and the list can be reviewed as a diff before it is anything. RELEASING
stamps released_utc, and that stamp is the only thing data_pause reads.

WHAT THIS REFUSES TO DO. It will not stage a ZIP that has no v2 reading
behind it. Phase 0 took the old vendor's numbers off ~23,000 pages; an
allowlist that only asked "is this ZIP in tranche 1?" would put them straight
back, because the entries in web/data/zips are still Redfin-derived and a
released ZIP renders whatever its entry holds. The check is belt and braces
with data_pause.shows_data(zip, basis), which independently refuses to
publish a reading whose basis is not RELEASED_BASIS — a staged mistake stays
dark rather than going live.

ORDER COMES FROM THE RANKING, not from this file. --tier reads
tier_interim.csv (supply-based, the interim ordering) and --ranking reads
gsc_zip.csv (impressions, once Search Console has data). The plan wants the
second; correction 1 explains why the first exists.
"""

import argparse
import csv
import glob
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import data_pause as PAUSE

ROOT = Path(__file__).resolve().parents[1]
# (the per-state layout is gone; the basis now comes from the store —
#  see readings(). Kept out of the module so nothing re-defaults to it.)
# The rebuilt ranking (rank_v2.py). Already-staged ZIPs are excluded by
# partition(), so re-pointing does not restage tranches 1 and 2.
TIERS = Path(__file__).parent / "tier_v2.csv"
GSC = Path(__file__).parent / "gsc_zip.csv"


def load_file(path=None):
    p = Path(path or PAUSE.TRANCHES)
    if not p.exists():
        return {"basis": PAUSE.RELEASED_BASIS, "tranches": []}
    return json.loads(p.read_text())


def save_file(data, path=None):
    p = Path(path or PAUSE.TRANCHES)
    p.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def readings(zips_dir=None, source="rentcast"):
    """{zip: basis} — which ZIPs have a v2 reading behind them.

    THE PUBLIC ARTIFACT CANNOT ANSWER THIS, and used to be asked anyway. An
    unreleased ZIP's record is {"st": "XX"} by construction — no level, no
    basis — because withholding it is the whole point of the pause. So reading
    web/data to decide what may be released asks the output whether the input
    exists. It happened to work while records were the Redfin-era shape and
    every ZIP carried metrics; it stopped the moment those were blanked, and
    stopped visibly on 2026-08-20 when the per-state files were removed
    entirely: every candidate came back "no reading at all" and Tranche 1
    could not be staged.

    The private store is the real answer. A ZIP is stageable when market_stats
    has scored data for it — the same source provision_readings scores from.

    zips_dir is kept for fixtures and tests, and now accepts either layout:
    one file per state ({zip: entry}) or one file per ZIP (the entry, named
    {zip}.json).
    """
    if zips_dir:
        return _readings_from_files(zips_dir)
    from rescore_v2 import db_rows
    out = {}
    for row, _hist in db_rows(source):
        z = (row.get("zip") or "").strip()
        if z:
            out[z] = PAUSE.RELEASED_BASIS
    return out


def _readings_from_files(zips_dir):
    """Fixture reader. Accepts both the per-state and per-ZIP layouts."""
    out = {}
    for f in sorted(Path(zips_dir).glob("*.json")):
        try:
            doc = json.loads(f.read_text())
        except (ValueError, OSError):
            continue
        if isinstance(doc, dict) and f.stem.isdigit() and "st" in doc:
            out[f.stem] = doc.get("b", PAUSE.LEGACY_BASIS)   # one file per ZIP
        elif isinstance(doc, dict):
            for z, e in doc.items():                          # one file per state
                if isinstance(e, dict):
                    out[z] = e.get("b", PAUSE.LEGACY_BASIS)
    return out


def candidates(tiers_file=None, gsc_file=None, tier=None, ranking=False, count=None):
    """Ranked ZIPs to consider, best first.

    Paths resolve at call time, not as default arguments: a default captured
    at import binds the module constant permanently, which makes the ranking
    source impossible to point anywhere else — including at a fixture.
    """
    tiers_file = tiers_file or TIERS
    gsc_file = gsc_file or GSC
    if ranking:
        rows = list(csv.DictReader(open(gsc_file, encoding="utf-8")))
        out = [r["zip"] for r in rows]
    else:
        want = {t.strip().upper() for t in (tier or "A").split(",")}
        out = [r["zip"] for r in csv.DictReader(open(tiers_file, encoding="utf-8"))
               if r.get("tier", "").upper() in want]
    return out[:count] if count else out


def partition(zips, basis_by_zip, already):
    """(eligible, blocked) — blocked carries a reason per ZIP."""
    eligible, blocked = [], {}
    for z in zips:
        if z in already:
            blocked[z] = "already in a tranche"
        elif z not in basis_by_zip:
            blocked[z] = "no reading at all"
        elif basis_by_zip[z] != PAUSE.RELEASED_BASIS:
            blocked[z] = "reading is still legacy — no v2 data for this ZIP"
        else:
            eligible.append(z)
    return eligible, blocked


def staged_zips(data):
    out = set()
    for t in data.get("tranches", []):
        out.update(str(z) for z in t.get("zips", []))
    return out


def sync_release(tranche, dry=False):
    """Mirror a released tranche into public.zip_release (schema-v36).

    The build reads tranches.json; the market-reading Edge Function reads this
    table, because a function cannot read the repo. They are written together
    on purpose — a ZIP released in one and not the other is a page rendering a
    reading the API will not serve, or the reverse.

    Returns the row count written, or None if it could not be done. Never
    raises: the JSON stamp has already landed by the time this runs, and
    crashing here would leave the operator unsure which of the two is true.
    """
    if dry:
        print(f"  --no-db: skipped writing {len(tranche.get('zips', [])):,} "
              f"rows to public.zip_release")
        return 0
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("  Supabase not configured — zip_release not updated")
        return None
    rows = [{"zip": z, "tranche": tranche["name"],
             "basis": tranche.get("basis") or PAUSE.RELEASED_BASIS,
             "released_at": tranche["released_utc"]}
            for z in tranche.get("zips", [])]
    sent = 0
    for i in range(0, len(rows), 500):
        batch = rows[i:i + 500]
        req = urllib.request.Request(
            f"{url}/rest/v1/zip_release?on_conflict=zip",
            data=json.dumps(batch).encode(), method="POST",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "Prefer": "resolution=merge-duplicates,return=minimal"})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                if r.status not in (200, 201, 204):
                    print(f"  zip_release batch {i // 500}: HTTP {r.status}")
                    return None
        except Exception as e:
            print(f"  zip_release batch {i // 500} failed: {str(e)[:120]}")
            return None
        sent += len(batch)
    print(f"  zip_release: {sent:,} row(s) written — the API will now serve them")
    return sent


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def status(data):
    if not data.get("tranches"):
        print("no tranches staged")
        return
    for t in data["tranches"]:
        state = f"RELEASED {t['released_utc']}" if t.get("released_utc") else "staged (not live)"
        print(f"  {t['name']:<14} {len(t.get('zips', [])):>6,} ZIPs  {state}")
    live = PAUSE.released_zips(PAUSE.TRANCHES)
    print(f"live now: {len(live):,} ZIPs of {len(staged_zips(data)):,} staged")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Stage and release Phase 4 tranches")
    ap.add_argument("--name")
    ap.add_argument("--tier", help="tiers from tier_interim.csv (default A)")
    ap.add_argument("--ranking", action="store_true",
                    help="order by gsc_zip.csv impressions instead of tier")
    ap.add_argument("--count", type=int)
    ap.add_argument("--release", action="store_true", help="stamp released_utc")
    ap.add_argument("--no-db", action="store_true",
                    help="stamp the file only; do not write public.zip_release")
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--file", default=str(PAUSE.TRANCHES))
    ap.add_argument("--zips", default=None,
                    help="read the basis from files instead of the store "
                         "(fixtures and tests; accepts either layout)")
    ap.add_argument("--tiers-file", default=str(TIERS))
    ap.add_argument("--gsc-file", default=str(GSC))
    args = ap.parse_args(argv)

    data = load_file(args.file)

    if args.status:
        status(data)
        return 0

    if not args.name:
        raise SystemExit("--name is required (or use --status)")

    if args.release:
        for t in data["tranches"]:
            if t["name"] == args.name:
                if t.get("released_utc"):
                    print(f"{args.name} was already released at {t['released_utc']}")
                    return 0
                if not t.get("zips"):
                    raise SystemExit(f"{args.name} is empty — nothing to release")
                t["released_utc"] = now_utc()
                save_file(data, args.file)
                print(f"RELEASED {args.name}: {len(t['zips']):,} ZIPs now live "
                      f"at {t['released_utc']}")
                pushed = sync_release(t, dry=args.no_db)
                if pushed is None:
                    print("::warning::tranches.json is stamped but public."
                          "zip_release was NOT updated. The pages will publish "
                          "readings the API refuses to serve. Re-run with the "
                          "database reachable before deploying.")
                print("Deploy to take effect. The pages drop noindex and "
                      "re-enter the sitemap on the next build.")
                return 0
        raise SystemExit(f"no tranche named {args.name} — stage it first")

    if any(t["name"] == args.name for t in data["tranches"]):
        raise SystemExit(f"{args.name} already exists — use --release, or "
                         f"pick another name")

    try:
        basis_by_zip = readings(args.zips)
    except SystemExit as e:
        raise SystemExit(
            f"promote_tranche: could not read the private store ({e}).\n"
            "Staging needs to know which ZIPs have a v2 reading, and only the "
            "store knows — the public records are blanked by design. Check "
            "the Supabase link, or pass --zips with a fixture directory.")
    if not basis_by_zip and not args.zips:
        raise SystemExit(
            "promote_tranche: the store returned no scored ZIPs.\n"
            "Every candidate would be blocked as 'no reading at all', which "
            "reads like a clean no-op and is not one. Refusing to continue.")
    picks = candidates(args.tiers_file, args.gsc_file, tier=args.tier,
                       ranking=args.ranking, count=args.count)
    eligible, blocked = partition(picks, basis_by_zip, staged_zips(data))

    reasons = {}
    for why in blocked.values():
        reasons[why] = reasons.get(why, 0) + 1
    print(f"considered {len(picks):,} ranked ZIPs")
    for why, n in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  blocked — {why}: {n:,}")
    print(f"eligible: {len(eligible):,}")

    if not eligible:
        print("\nNothing to stage. If every ZIP is blocked as 'still legacy', "
              "that is the expected state until the acquisition has run and "
              "the pipeline has re-scored these ZIPs on v2 — staging them now "
              "would republish the numbers Phase 0 withdrew.")
        return 1

    data["tranches"].append({"name": args.name, "released_utc": None,
                             "basis": PAUSE.RELEASED_BASIS,
                             "staged_utc": now_utc(), "zips": eligible})
    save_file(data, args.file)
    print(f"\nstaged {args.name}: {len(eligible):,} ZIPs, NOT live.")
    print("Review the diff, then: --name "
          f"{args.name} --release")
    return 0


if __name__ == "__main__":
    sys.exit(main())
