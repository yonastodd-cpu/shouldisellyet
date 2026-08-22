#!/usr/bin/env python3
"""Is the degraded-mode fallback still there? FHFA + Census, against live URLs.

    python3 pipeline/check_fallback_sources.py            # dry run, NO network
    python3 pipeline/check_fallback_sources.py --check    # run it

WHY THIS FILE EXISTS. If the vendor relationship ends on short notice, the
site does not go dark: it degrades onto FHFA's annual ZIP5 house-price index
and the Census ACS housing-stock tables — free, government-published, public
domain, no licence to lose. That is the plan of record. A plan of record that
nobody has executed in eight months is a hope, and the two ways it fails are
both silent:

  * THE URL MOVES. FHFA already did this once. The old
    /document/hpi_at_bdl_zip5.xlsx still returns 200 with a valid workbook —
    it is simply FROZEN at the March 2024 release. Nothing errors; the numbers
    just stop advancing. fetch_fhfa.py documents the move at the top of the
    file, which is exactly the kind of knowledge that survives in a comment
    and dies in a rota.
  * THE VINTAGE MOVES. Census publishes 5-year estimates annually and retires
    old paths. A --year that was current when it was typed becomes a 404 on a
    schedule nobody is watching.

So this asserts FRESH and PARSEABLE, not merely reachable. A 200 is not the
test; a `thru` year that has advanced is.

WHAT IT DOES NOT DO. It does not write pipeline/fhfa_zip.csv or
pipeline/acs_zip.csv. A health check that overwrites the committed inputs it
is checking would turn a failing source into a corrupted pipeline on the same
run — and those two files are what degraded mode would actually load. It
parses into memory, compares against what is committed, and reports.

IT DOES NOT RUN WITHOUT --check. Same reason as snapshot_vendor_terms.py: the
module is imported by its test and edited by people not thinking about
network. Only the flag makes a request. Nothing here touches a metered vendor
endpoint — FHFA and Census are free public downloads and there is no API key
anywhere in this file.

ONE OF THEM IS BIG. The FHFA workbook is tens of megabytes and openpyxl walks
it row by row; budget a couple of minutes, and do not put this in the critical
path of a deploy.

CI: monthly, unattended. See the schedule note at the bottom of this file.
"""

import argparse
import csv
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import fetch_acs as ACS
import fetch_fhfa as FHFA

HERE = Path(__file__).parent

# The committed artefacts degraded mode would actually read. They are the
# baseline: a live source that suddenly reports a fraction of the ZIPs we
# already hold has broken in a way a row count catches and a 200 does not.
FHFA_CSV = HERE / "fhfa_zip.csv"
ACS_CSV = HERE / "acs_zip.csv"

# Tolerances, and why these numbers. Both sources revise: ZIPs enter and leave
# as coverage thresholds are met, so an exact match would fail every release
# for no reason. A 15% collapse in coverage is not revision, it is a broken
# parse against a changed file layout — which is the failure that looks like
# success.
MIN_COVERAGE = 0.85
# FHFA's index is annual and lags. Released each spring for the year before
# last-but-one at worst, so two years behind the wall clock is the outer edge
# of normal and three is the frozen-URL signature.
MAX_LAG_YEARS = 2
ACS_YEAR = "2023"          # matches fetch_acs.main's default


def committed_fhfa(path=FHFA_CSV):
    """(zip_count, latest_thru_year) from the committed compact CSV."""
    if not Path(path).exists():
        return 0, 0
    rows = list(csv.DictReader(Path(path).open(encoding="utf-8")))
    years = [int(r["thru"]) for r in rows if (r.get("thru") or "").isdigit()]
    return len(rows), (max(years) if years else 0)


def committed_acs(path=ACS_CSV):
    if not Path(path).exists():
        return 0
    return sum(1 for _ in csv.DictReader(Path(path).open(encoding="utf-8")))


def check_fhfa(url=None, rows=None, today=None):
    """Parse the live FHFA workbook and judge it. Returns (ok, findings).

    `rows` is injectable so the test can feed a synthetic workbook — this
    function must be testable without downloading tens of megabytes.
    """
    src = rows if rows is not None else FHFA.iter_fhfa_rows(url or FHFA.FHFA_ZIP5_URL)
    latest = {}
    n = 0
    for z, year, chg in src:
        n += 1
        if chg is None:
            continue
        if year > latest.get(z, (0, None))[0]:
            latest[z] = (year, chg)
    have, prior_thru = committed_fhfa()
    thru = max((y for y, _ in latest.values()), default=0)
    this_year = (today or date.today()).year
    out = []
    if not latest:
        out.append("FHFA: parsed 0 usable ZIP rows — the workbook layout "
                   "changed or the sheet header moved")
    if have and len(latest) < have * MIN_COVERAGE:
        out.append(f"FHFA: {len(latest):,} ZIPs, down from {have:,} committed "
                   f"(below {MIN_COVERAGE:.0%}) — likely a parse failure, not a revision")
    if thru < prior_thru:
        out.append(f"FHFA: latest reported year {thru} is BEHIND the committed "
                   f"{prior_thru} — this is the frozen-URL signature "
                   f"(see fetch_fhfa.FHFA_ZIP5_URL_LEGACY)")
    if thru and this_year - thru > MAX_LAG_YEARS:
        out.append(f"FHFA: latest reported year {thru} is {this_year - thru} "
                   f"years behind {this_year} — the file has stopped advancing")
    return (not out), out, {"rows": n, "zips": len(latest), "thru": thru,
                            "committed_zips": have, "committed_thru": prior_thru}


def check_acs(year=ACS_YEAR, units_text=None, tenure_text=None):
    """Parse both live ACS tables and judge them. Returns (ok, findings, stats)."""
    u = ACS.parse_dat(units_text if units_text is not None else
                      ACS.fetch(ACS.BASE.format(year=year, table="b25001")),
                      "B25001_E001")
    o = ACS.parse_dat(tenure_text if tenure_text is not None else
                      ACS.fetch(ACS.BASE.format(year=year, table="b25003")),
                      "B25003_E002")
    merged = ACS.merge(u, o)
    have = committed_acs()
    out = []
    if not merged:
        out.append(f"Census ACS {year}: parsed 0 ZCTAs — the .dat layout or "
                   f"the GEO_ID prefix changed")
    if have and len(merged) < have * MIN_COVERAGE:
        out.append(f"Census ACS {year}: {len(merged):,} ZCTAs, down from "
                   f"{have:,} committed (below {MIN_COVERAGE:.0%})")
    with_owner = sum(1 for r in merged if r["owner"] != "")
    if merged and with_owner < len(merged) * 0.5:
        # Tenure is the half the tiering actually orders on. Total units
        # parsing while tenure silently empties would pass a row count and
        # produce a ranking with no signal in it.
        out.append(f"Census ACS {year}: only {with_owner:,} of {len(merged):,} "
                   f"ZCTAs carry owner-occupied counts — the tenure table "
                   f"parsed but yielded nothing usable")
    return (not out), out, {"units": len(u), "tenure": len(o),
                            "merged": len(merged), "with_owner": with_owner,
                            "committed": have}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="actually fetch and parse (without this: dry run)")
    ap.add_argument("--acs-year", default=ACS_YEAR)
    args = ap.parse_args(argv)

    if not args.check:
        print("DRY RUN — no request made. Would check:")
        print(f"  FHFA   {FHFA.FHFA_ZIP5_URL}")
        for t in ("b25001", "b25003"):
            print(f"  Census {ACS.BASE.format(year=args.acs_year, table=t)}")
        print("Re-run with --check to fetch and parse them.")
        return 0

    findings = []
    print("FHFA ZIP5 house-price index…")
    ok_f, f_out, f_stats = check_fhfa()
    print(f"  {f_stats['zips']:,} ZIPs through {f_stats['thru']} "
          f"(committed: {f_stats['committed_zips']:,} through {f_stats['committed_thru']})")
    findings += f_out

    print(f"Census ACS {args.acs_year} housing stock…")
    ok_a, a_out, a_stats = check_acs(args.acs_year)
    print(f"  {a_stats['merged']:,} ZCTAs, {a_stats['with_owner']:,} with tenure "
          f"(committed: {a_stats['committed']:,})")
    findings += a_out

    if findings:
        print("\nFALLBACK DEGRADED — the plan of record does not currently run:")
        for f in findings:
            print("  * " + f, file=sys.stderr)
        return 1
    print("\nBoth fallback sources fetched, parsed, and fresh.")
    return 0


# ————— THE CI JOB THIS NEEDS —————
#
# Monthly, unattended, separate workflow from the data refresh — this has to
# keep running through a month when nothing is deployed, which is exactly the
# month the fallback would be needed.
#
#   schedule:  cron "0 7 1 * *"  (07:00 UTC on the 1st) + workflow_dispatch
#   runtime:   allow 15 minutes. The FHFA workbook is tens of megabytes and
#              openpyxl streams it; the default 6h job timeout is fine but a
#              tight step timeout is not.
#   deps:      pip install openpyxl. It is NOT a monthly-pipeline dependency —
#              fetch_fhfa is an annual hand run — so this job installs it or
#              the check fails on an ImportError that says nothing about the
#              sources.
#   steps:     checkout → pip install openpyxl →
#              python3 pipeline/check_fallback_sources.py --check
#   exit 1:    a source moved, froze, or stopped parsing. Fail the job. This
#              is a "you have months to fix it" alarm, not a page — which is
#              the entire value of finding out on a quiet month.
#   NOT gated on the deploy. It must never be able to block a site build: the
#   fallback being broken is a future problem, and a check that can take the
#   site down is a bigger present one.

if __name__ == "__main__":
    sys.exit(main())
