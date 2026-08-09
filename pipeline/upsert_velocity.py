#!/usr/bin/env python3
"""Upsert per-ZIP velocity payloads to Supabase — the paid serving layer.

    python3 pipeline/upsert_velocity.py [--src pipeline/velocity/zip-velocity-latest.json]

Reads the (gitignored) per-ZIP output of velocity.py and upserts it into
zip_velocity (schema-v20), which verify-access joins per purchase token.
Runs in the refresh workflow right after velocity.py, with the same
missing-config-exits-0 discipline as every other Supabase job here: a fork
without secrets must not fail the refresh.

Batched: ~26k rows at 500/request ≈ 54 requests. `resolution=merge-duplicates`
makes each batch an upsert on the zip primary key.
"""

import argparse
import json
import os
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BATCH = 500


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(Path(__file__).parent / "velocity" / "zip-velocity-latest.json"))
    args = ap.parse_args()

    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("velocity upsert: Supabase not configured — nothing to do")
        return 0

    src = Path(args.src)
    if not src.exists():
        print(f"velocity upsert: {src} missing (velocity.py not run?) — nothing to do")
        return 0

    data = json.loads(src.read_text())
    period, zips = data["period"], data["zips"]
    rows = [{"zip": z,
             "period": period,
             # Everything the report section needs; nothing it doesn't.
             "payload": {"sig": r["sig"], "score": r["score"],
                         "state": r["state"], "low_volume": r["low_volume"]}}
            for z, r in zips.items()]

    sent = 0
    items = list(rows)
    for i in range(0, len(items), BATCH):
        body = json.dumps(items[i:i + BATCH]).encode()
        req = urllib.request.Request(
            f"{url}/rest/v1/zip_velocity?on_conflict=zip",
            data=body, method="POST",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json",
                     "Prefer": "resolution=merge-duplicates,return=minimal"})
        with urllib.request.urlopen(req, timeout=120) as r:
            if r.status not in (200, 201, 204):
                print(f"velocity upsert: batch {i//BATCH} HTTP {r.status}", file=sys.stderr)
                return 1
        sent += len(items[i:i + BATCH])
    print(f"velocity upsert: {sent:,} ZIPs for {period}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
