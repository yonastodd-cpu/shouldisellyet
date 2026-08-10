#!/usr/bin/env python3
"""Nightly: freeze click performance onto posted marketing tasks.

The join itself lives in SQL — public.marketing_perf_refresh (schema-v23 §7) —
so this job and the admin leaderboard can never disagree about what "measured"
means. Each run re-measures every posted task whose posted_at is inside the
last WINDOW_DAYS: perf_checks = zip_check count, perf_clicks =
purchase_click_report + purchase_click_monitor, over the events carrying that
task's utm_campaign token. Cumulative overwrite, not increment — a re-run is
always safe, and a double dispatch cannot double a number.

WHY 45 DAYS. Raw events purge at 90 (events_maintenance.py). A task last
re-measured at posted_at + 45d was measured from a COMPLETE event set — its
oldest evidence is 45 days old, half the retention window — and after that the
number is frozen and stands as the record. Re-measuring older tasks would make
their numbers shrink as their evidence expired: a chart that goes down because
the janitor came through. Numbers here may stop moving; they may never fall.

WHY ITS OWN WORKFLOW (.github/workflows/marketing-perf.yml, 08:00 UTC daily):
update.yml is Mon/Thu and every step of it is gated on the Redfin ETag, so a
Sunday 19:30 ET anchor post would sit unmeasured until Monday at best and
until Thursday if no source moved; rate-watch.yml is Friday-only. The card
promises "drove 34 checks" the morning after posting, and that needs a daily
cadence that no data source gates.

Missing config prints and exits 0 — a fork without secrets must not go red
every night. A real API failure exits 1: this workflow does nothing else, so
red IS the alert, and the columns it failed to fill stay NULL, which every
reader renders as "not measured yet" and never as zero.

MEASUREMENT ONLY. This job writes perf_checks / perf_clicks / perf_checked_at
and nothing else — never a priority, a schedule, or a status. That is not a
convention here, it is the shape of the RPC, and pipeline/test_marketing_
advisory.py fails if the UPDATE ever grows a fourth column.

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY (the pipeline's names — the edge
functions use SUPABASE_SERVICE_ROLE_KEY, a different variable).

  python3 pipeline/marketing_perf.py
"""

import json
import os
import sys
import urllib.request

WINDOW_DAYS = 45


def main() -> int:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("marketing perf: Supabase not configured — nothing to do")
        return 0

    # EXECUTE on marketing_perf_refresh is revoked from public/anon/
    # authenticated and granted to nobody else: the service key below is the
    # only caller there will ever be. No admin RPC wraps it on purpose — a
    # button that silently rewrites measured history should not exist.
    req = urllib.request.Request(
        f"{url}/rest/v1/rpc/marketing_perf_refresh",
        data=json.dumps({"p_days": WINDOW_DAYS}).encode(),
        method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.load(r)
    except Exception as exc:
        # Print the class as well as the message: a 404 here means schema-v23
        # has not been applied, a 401 means the key is wrong, and the bare
        # message does not distinguish them.
        print(f"marketing perf: refresh failed — {type(exc).__name__}: {exc}")
        return 1

    if not isinstance(out, dict):
        print(f"marketing perf: unexpected response {out!r}")
        return 1

    print(f"marketing perf: re-measured {out.get('tasks', '?')} posted task(s) "
          f"(window {out.get('days', WINDOW_DAYS)}d)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
