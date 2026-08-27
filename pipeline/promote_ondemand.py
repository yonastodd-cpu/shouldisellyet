#!/usr/bin/env python3
"""Promotion sweep: fold on-demand-pulled ZIPs into the build's release ledger.

Run by .github/workflows/ondemand-promote.yml on MANUAL DISPATCH only
(operator decision 2026-08-26 — no cron; the operator picks when static
pages publish).

THE TWO-WRITER PROBLEM, IN THE OTHER DIRECTION. promote_tranche.py writes
tranches.json first and mirrors it into public.zip_release. The on-demand
path writes in the opposite order: the `ondemand-pull` edge function inserts
the zip_release row at pull time (tranche='ondemand'), because a function
cannot commit to the repo — so the API serves the pulled ZIP immediately,
while its STATIC page still shows the notice and stays out of the sitemap.

This script closes the loop: it reads the tranche='ondemand' rows back and
appends any missing ZIPs to an `ondemand` tranche in pipeline/tranches.json.
On the next deploy those ZIPs get provisioned readings, render live pages,
drop noindex and join the sitemap — through exactly the gates every tranche
page passes, because after this sweep they ARE tranche pages.

WHY BATCHED, NOT PER SALE. Each promotion is a commit, a rebuild and a
sitemap change. Batching keeps sitemap churn low and keeps the promotion on
the same gated deploy path as everything else. In the gap, the ZIP is fully
served: the homepage and the buyer's report read the word from the API
(zip_readings), only the static page lags.

SAFETY: a ZIP is appended only if public.zip_readings actually holds its
reading — the same "no staged ZIP without a v2 reading behind it" rule
promote_tranche enforces. A zip_release row with no reading behind it (which
the pull path cannot produce, but rules exist for the states code cannot
produce) is reported and skipped.

Usage:
  python3 pipeline/promote_ondemand.py [--dry-run] [--file pipeline/tranches.json]

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY. Missing credentials exit 0 with a
message (same contract as load_market_stats), so a fork's CI never fails on
absent secrets.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import data_pause as PAUSE

TRANCHE_NAME = "ondemand"


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _get(url, key, path):
    req = urllib.request.Request(f"{url}/rest/v1/{path}", headers={
        "apikey": key, "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def fetch_ondemand_zips(url, key):
    """Every zip_release row the pull path wrote, paginated."""
    out, offset, page = [], 0, 1000
    while True:
        rows = _get(url, key,
                    f"zip_release?tranche=eq.{TRANCHE_NAME}&select=zip"
                    f"&order=zip.asc&limit={page}&offset={offset}")
        out += [r["zip"] for r in rows]
        if len(rows) < page:
            return out
        offset += page


def fetch_scored(url, key, zips):
    """The subset of `zips` that zip_readings actually holds."""
    scored = set()
    for i in range(0, len(zips), 200):
        batch = ",".join(zips[i:i + 200])
        quoted = urllib.parse.quote(f"({batch})", safe="(),")
        rows = _get(url, key,
                    f"zip_readings?zip=in.{quoted}&select=zip&limit=200")
        scored.update(r["zip"] for r in rows)
    return scored


def merge(data, zips, when=None):
    """Append missing ZIPs to the ondemand tranche. Returns the new ones.

    Append-only: nothing is ever removed here, and an existing tranche keeps
    its original released_utc — released_zips() only needs the stamp to
    exist, and rewriting it would misstate when the first pulled ZIP went
    live.
    """
    when = when or now_utc()
    tranche = next((t for t in data.get("tranches", [])
                    if t.get("name") == TRANCHE_NAME), None)
    if tranche is None:
        tranche = {"name": TRANCHE_NAME,
                   "released_utc": when,
                   "basis": PAUSE.RELEASED_BASIS,
                   "staged_utc": when,
                   "zips": []}
        data.setdefault("tranches", []).append(tranche)
    have = set(tranche["zips"])
    new = sorted(z for z in set(zips) if z not in have)
    tranche["zips"] += new
    return new


def main(argv=None):
    ap = argparse.ArgumentParser(description="Fold on-demand ZIPs into tranches.json")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--file", default=str(PAUSE.TRANCHES))
    args = ap.parse_args(argv)

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set — nothing to sweep")
        return 0

    pulled = fetch_ondemand_zips(url, key)
    if not pulled:
        print("no on-demand ZIPs in zip_release — nothing to promote")
        return 0

    scored = fetch_scored(url, key, pulled)
    unscored = sorted(set(pulled) - scored)
    if unscored:
        # Loud, not fatal: the scored ones still promote.
        print(f"::warning::{len(unscored)} on-demand ZIP(s) have a release row "
              f"but no reading in zip_readings — skipped: {', '.join(unscored[:10])}"
              + ("…" if len(unscored) > 10 else ""))

    path = Path(args.file)
    data = json.loads(path.read_text())
    new = merge(data, sorted(scored))
    if not new:
        print(f"ondemand tranche already carries all {len(scored)} pulled ZIP(s) — no change")
        return 0
    if args.dry_run:
        print(f"--dry-run: would append {len(new)} ZIP(s): {', '.join(new[:20])}"
              + ("…" if len(new) > 20 else ""))
        return 0
    path.write_text(json.dumps(data, indent=2) + "\n")
    print(f"appended {len(new)} on-demand ZIP(s) to the {TRANCHE_NAME} tranche: "
          + ", ".join(new[:20]) + ("…" if len(new) > 20 else ""))
    print("Commit tranches.json and deploy to take effect — the pages drop "
          "noindex and join the sitemap on the next build.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
