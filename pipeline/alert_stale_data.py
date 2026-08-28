#!/usr/bin/env python3
"""Email the operator when the market data store goes stale past cadence.

    python3 pipeline/alert_stale_data.py            # check, alert only if stale
    python3 pipeline/alert_stale_data.py --test     # send a marked test alert now

WHY THIS EXISTS (close-out 2026-08-28, FINAL_REVIEW row 19a). Staleness was
visible in two places — the admin Data Health rows and refresh-workflow
annotations — and both share the same failure mode: they inform whoever goes
looking, and nobody goes looking. The subscription this site sells is "we
watch so you don't have to"; the operator needs the same courtesy. This runs
inside the scheduled refresh job (update.yml, Mon/Thu) and emails when the
newest stored market reading is older than the alert line.

THE THRESHOLD. market_stats holds monthly-vintage vendor data, refreshed by
metered manual acquisition (market-refresh.yml) and purchase-time pulls. For a
monthly source, 45 days is the stall alarm — the same line the admin health
row draws for a monthly release. Override with STALE_ALERT_DAYS.

DELIVERY. Resend, same recipients as the Growth Ops digest
(OPS_DIGEST_RECIPIENTS, falling back to hello@shouldisellyet.com — a real
Titan mailbox; see match-request/index.ts for why alerts@ is not one).

FAILURE POSTURE. The CI step carries continue-on-error — an alerting problem
must never cost a deploy — but this script still exits nonzero when it cannot
check or cannot send, so the failure is a red annotation rather than silence.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

DEFAULT_STALE_DAYS = 45
FALLBACK_TO = "hello@shouldisellyet.com"


def newest_retrieved_at():
    """ISO timestamp of the newest market_stats row, or None if unreachable."""
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_KEY not set — cannot check freshness")
        return None
    req = urllib.request.Request(
        f"{url}/rest/v1/market_stats?select=retrieved_at&order=retrieved_at.desc&limit=1",
        headers={"apikey": key, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            rows = json.load(r)
    except Exception as e:  # noqa: BLE001 — any failure here is "cannot check"
        print(f"freshness query failed: {e}")
        return None
    return rows[0]["retrieved_at"] if rows else None


def days_old(iso, now=None):
    """Whole days between an ISO timestamp and now (UTC)."""
    now = now or datetime.now(timezone.utc)
    ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int((now - ts).total_seconds() // 86400)


def recipients():
    env = os.environ.get("OPS_DIGEST_RECIPIENTS", "").strip()
    return [x.strip() for x in env.split(",") if x.strip()] or [FALLBACK_TO]


def send(subject, html):
    key = os.environ.get("RESEND_API_KEY", "")
    if not key:
        print("RESEND_API_KEY not set — no alert sent")
        return False
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({
            "from": os.environ.get("ALERT_FROM",
                                   "ShouldISellYet <support@shouldisellyet.com>"),
            "to": recipients(), "subject": subject, "html": html,
        }).encode(),
        method="POST",
        # The UA matters: Cloudflare fronts api.resend.com and bot-blocks
        # urllib's default signature (error 1010) — found when the first test
        # send from a GitHub runner came back 403 with no Resend error at all.
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                 "User-Agent": "shouldisellyet-ops/1.0 (+https://shouldisellyet.com)"})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        return True
    except urllib.error.HTTPError as e:
        # Resend's body names the actual refusal (unverified domain, restricted
        # key) — a bare status code sends whoever reads the log guessing.
        print(f"resend send failed: {e} — {e.read().decode('utf-8', 'replace')[:300]}")
        return False
    except Exception as e:  # noqa: BLE001
        print(f"resend send failed: {e}")
        return False


def alert_html(age_days, newest, threshold):
    return (
        "<p><b>The market data store is stale past cadence.</b></p>"
        f"<p>Newest <code>market_stats</code> row was retrieved <b>{age_days} days ago</b> "
        f"({newest}); the alert line is {threshold} days for a monthly-vintage source.</p>"
        "<p>Likely causes: no acquisition run since the last vintage "
        "(market-refresh.yml is manual and metered), or the vendor stopped "
        "publishing. Served pages keep rendering their stored readings either "
        "way — this alert is about the freshness the terms promise (§7), not "
        "an outage.</p>")


def main(argv=None):
    argv = argv or sys.argv[1:]
    threshold = int(os.environ.get("STALE_ALERT_DAYS", DEFAULT_STALE_DAYS))

    if "--test" in argv:
        ok = send("[TEST] Stale-data alert — delivery check",
                  "<p><b>Test only — the data is not being reported stale.</b></p>"
                  + alert_html(999, "1970-01-01T00:00:00Z (synthetic)", threshold)
                  + "<p>This message verifies the stale-data alert path "
                    "(pipeline/alert_stale_data.py) can reach your inbox. "
                    "FINAL_REVIEW row 19a.</p>")
        print("test alert sent" if ok else "test alert FAILED")
        return 0 if ok else 1

    newest = newest_retrieved_at()
    if newest is None:
        # Cannot check is its own failure — silence is what this file replaces.
        # Nonzero either way; the email (when it sends) names the run to read.
        send("Stale-data check could not run",
             "<p><b>The scheduled freshness check could not query "
             "market_stats.</b> See the update.yml run log.</p>")
        return 1

    age = days_old(newest)
    if age <= threshold:
        print(f"fresh: newest market_stats row is {age} days old (line: {threshold})")
        return 0
    ok = send(f"Market data is stale — newest reading is {age} days old",
              alert_html(age, newest, threshold))
    print(f"stale ({age}d > {threshold}d) — alert {'sent' if ok else 'FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
