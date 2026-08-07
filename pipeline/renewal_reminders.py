"""
ShouldISellYet — pre-renewal reminders.

Emails annual subscribers about a month before their subscription renews:
what plan, what date, what amount, and how to cancel. Several state
auto-renewal statutes require advance notice on long-term terms; more
practically, a $29 charge nobody remembered agreeing to is a chargeback and a
refund request, and this is cheaper than both.

    python3 pipeline/renewal_reminders.py [--dry-run] [--window-days 30]

MONTHLY SUBSCRIBERS ARE NOT REMINDED, deliberately. A $3.99 charge every 30
days is visible and self-evident; a monthly reminder email would be noise that
trains people to ignore us — and an ignored sender is worse than a silent one
when the alert that matters finally fires.

IDEMPOTENCY IS PER PERIOD, not per subscriber. `renewal_reminder_sent_for`
stores the period_end a reminder covered, so next year's renewal sends again
while this year's cannot double-send. A boolean would have silenced every
future renewal after the first — the classic version of this bug.

Env (missing anything = dry run, never a crash):
  SUPABASE_URL, SUPABASE_SERVICE_KEY
  RESEND_API_KEY, ALERT_FROM
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

SITE = "https://shouldisellyet.com"

# Mirrors web/prices.js. pipeline/test_prices.py fails the build if they
# disagree, so this cannot quietly quote a price we no longer charge.
PRICE_ANNUAL = 29
PRICE_MONTHLY = 3.99


def usd(n):
    return "$" + (str(int(n)) if float(n).is_integer() else f"{n:.2f}")


def sb_get(path):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = os.environ["SUPABASE_SERVICE_KEY"]
    req = urllib.request.Request(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def sb_patch(path, payload):
    url = os.environ["SUPABASE_URL"].rstrip("/") + "/rest/v1/" + path
    key = os.environ["SUPABASE_SERVICE_KEY"]
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="PATCH",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"})
    urllib.request.urlopen(req, timeout=30).read()


def due(window_days=30):
    """Active annual subscribers whose period ends inside the window and who
    have not already been reminded FOR THAT period end."""
    now = datetime.now(timezone.utc)
    hi = (now + timedelta(days=window_days)).isoformat()
    q = ("subscribers?select=id,email,zip,current_period_end,renewal_reminder_sent_for,access_token"
         "&status=eq.active&billing_interval=eq.annual"
         f"&current_period_end=gte.{urllib.parse.quote(now.isoformat())}"
         f"&current_period_end=lte.{urllib.parse.quote(hi)}")
    out = []
    for r in sb_get(q):
        pe, sent = r.get("current_period_end"), r.get("renewal_reminder_sent_for")
        if not pe or not r.get("email"):
            continue
        # Compare the STAMP to the period, not a boolean. Same period → skip.
        if sent and sent[:10] == pe[:10]:
            continue
        out.append(r)
    return out


def render(row):
    when = row["current_period_end"][:10]
    try:
        pretty = datetime.fromisoformat(row["current_period_end"].replace("Z", "+00:00")) \
            .strftime("%B %-d, %Y")
    except (ValueError, TypeError):
        pretty = when
    token = row.get("access_token") or ""
    manage = f"{SITE}/my-report.html?token={token}" if token else f"{SITE}/refunds.html"
    zip_code = row.get("zip") or "your ZIP"
    subject = f"Your EquityWatch subscription renews on {pretty}"
    html = f"""
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">EquityWatch</p>
  <h1 style="font-size:24px;margin:6px 0 14px">A heads-up before your renewal.</h1>
  <p style="font-size:16px;line-height:1.65">Your EquityWatch monitoring for <b>{zip_code}</b> renews on <b>{pretty}</b> at <b>{usd(PRICE_ANNUAL)} for the year</b>. Nothing is needed from you — this is just so the charge isn't a surprise.</p>
  <p style="font-size:16px;line-height:1.65">If you'd rather not continue, you can cancel yourself in a couple of clicks. Canceling stops the renewal; your monitoring runs to {pretty} either way.</p>
  <p style="margin:22px 0"><a href="{manage}" style="background:#1f3a5f;color:#fff;padding:13px 24px;border-radius:10px;text-decoration:none;font-family:Arial,sans-serif;font-size:15px;font-weight:bold;display:inline-block">Manage or cancel my subscription →</a></p>
  <p style="font-size:12px;color:#98a2b3;line-height:1.5;margin-top:18px">You're getting this because you have an active EquityWatch subscription — it's a billing notice, not marketing, so it's sent regardless of your email preferences. Questions? Just reply.</p>
</div>"""
    return subject, html


def send(to, subject, html):
    key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("ALERT_FROM", "ShouldISellYet <support@shouldisellyet.com>")
    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps({"from": sender, "to": [to], "subject": subject, "html": html}).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=30).read()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--window-days", type=int, default=30)
    args = ap.parse_args()

    need = ("SUPABASE_URL", "SUPABASE_SERVICE_KEY")
    if not all(os.environ.get(k) for k in need):
        print("renewal reminders: Supabase not configured — nothing to do")
        return 0
    try:
        rows = due(args.window_days)
    except Exception as e:
        print(f"renewal reminders: lookup failed ({e}) — skipping")
        return 0

    print(f"renewal reminders: {len(rows)} annual subscription(s) renewing "
          f"within {args.window_days} days and not yet reminded")
    if args.dry_run or not os.environ.get("RESEND_API_KEY"):
        for r in rows:
            subject, _ = render(r)
            print(f"  [dry-run] {r['email']} — {subject}")
        return 0

    for r in rows:
        subject, html = render(r)
        try:
            send(r["email"], subject, html)
        except Exception as e:
            # Leave the stamp unset so the next run retries. A reminder that
            # never arrives is the failure this job exists to prevent.
            print(f"  send failed for {r['email']}: {e}")
            continue
        try:
            sb_patch(f"subscribers?id=eq.{r['id']}",
                     {"renewal_reminder_sent_for": r["current_period_end"]})
            print(f"  reminded {r['email']} for period ending {r['current_period_end'][:10]}")
        except Exception as e:
            # Sent but not stamped: the next run would send again. Loud, because
            # a duplicate billing notice is confusing and worth fixing by hand.
            print(f"  ::warning:: sent to {r['email']} but could not stamp the row ({e}) "
                  f"— it may send again next run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
