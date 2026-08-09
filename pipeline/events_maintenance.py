#!/usr/bin/env python3
"""Delete raw analytics events older than 90 days, and spent rate-limit rows.

The privacy posture is "anonymous usage counts", and part of keeping counts
anonymous is not hoarding the raw rows: the dashboard reads daily rollups, so
per-event rows older than a quarter serve nobody. The events_daily view
recomputes from what remains — history beyond 90 days fades by design.

Runs in the weekly jobs workflow (same scheduler and secrets as
renewal_reminders.py). Weekly deletion of a 90-day boundary is exactly as
compliant as nightly — nothing reads the boundary between runs.

Env: SUPABASE_URL, SUPABASE_SERVICE_KEY. Missing config prints and exits 0 —
a fork without secrets must not fail the workflow that also sends rate alerts.
"""

import datetime as dt
import os
import sys
import urllib.request

RETAIN_DAYS = 90


def main() -> int:
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("events maintenance: Supabase not configured — nothing to do")
        return 0

    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=RETAIN_DAYS)).isoformat()
    req = urllib.request.Request(
        f"{url}/rest/v1/events?ts=lt.{cutoff}",
        method="DELETE",
        headers={
            "apikey": key,
            "Authorization": f"Bearer {key}",
            # Count without echoing rows back — the response tells us how many
            # went, which is the only thing worth logging.
            "Prefer": "count=exact",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        # Content-Range: */N or 0-24/25 — the total after the slash.
        rng = r.headers.get("Content-Range", "")
        n = rng.split("/")[-1] if "/" in rng else "?"
        print(f"events maintenance: deleted {n} rows older than {RETAIN_DAYS} days")

    # Rate-limit rows (schema-v18) are spent the moment their window lapses —
    # the longest window is 24h, so anything older than 48h is inert. The keys
    # are salted daily-rotating hashes that join to nothing, but dead rows are
    # still dead rows. Weekly is fine: the limiter resets lapsed windows
    # in-place, so stale rows can't extend or revive a limit between runs.
    cutoff_rl = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)).isoformat()
    req = urllib.request.Request(
        f"{url}/rest/v1/rate_limits?window_start=lt.{cutoff_rl}",
        method="DELETE",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            rng = r.headers.get("Content-Range", "")
            n = rng.split("/")[-1] if "/" in rng else "?"
            print(f"events maintenance: purged {n} spent rate-limit rows (>48h)")
    except Exception as e:  # table may predate schema-v18 on a fork — not fatal
        print(f"events maintenance: rate-limit purge skipped ({e})")

    # Unconfirmed waitlist signups purge at 7 days (double opt-in, schema-v19):
    # the address got its one confirm email and never clicked, so we stop
    # holding it — an unconfirmed row is a stranger's address we have no
    # consent to keep. ONLY rows created after the confirm flow went live
    # (2026-08-08): pre-migration waitlist signups predate confirmation and
    # are deliberately kept-but-never-emailed until the future waitlist
    # sender opens with a confirm pass for them — see schema-v19's footer.
    cutoff_wl = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=7)).isoformat()
    req = urllib.request.Request(
        f"{url}/rest/v1/subscribers?plan=eq.waitlist&confirmed_at=is.null"
        f"&created_at=lt.{cutoff_wl}&created_at=gt.2026-08-08",
        method="DELETE",
        headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "count=exact"},
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            rng = r.headers.get("Content-Range", "")
            n = rng.split("/")[-1] if "/" in rng else "?"
            print(f"events maintenance: purged {n} unconfirmed waitlist rows (>7d)")
    except Exception as e:  # column may predate schema-v19 on a fork — not fatal
        print(f"events maintenance: waitlist purge skipped ({e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
