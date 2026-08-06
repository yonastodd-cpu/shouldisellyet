"""
ShouldISellYet — personal-number watch alerts.

Separate from notify_changes.py (which watches the ZIP-level HOLD/WATCH/ACT
verdict for everyone on the monitor plan). This watches a subscriber's OWN
numbers — walk-away number, equity, or lock-in cost — against a threshold
they set, using the calculation inputs they explicitly opted to save via the
save-watch edge function (see supabase/functions/save-watch/index.ts).

A subscriber can watch up to three metrics at once (one toggle per number on
the report), stored as a jsonb array in `subscribers.watches` — this module
evaluates every entry in that array independently.

Runs in the GitHub Action right after fetch_data.py, using the freshly
published web/data/. If Supabase/Resend secrets aren't configured, dry-runs
and never fails the pipeline — same convention as notify_changes.py.

Usage:
  python pipeline/check_watches.py --data web/data

Required env (GitHub Actions secrets, already used by notify_changes.py):
  SUPABASE_URL, SUPABASE_SERVICE_KEY, RESEND_API_KEY
Optional:
  ALERT_FROM  default: "ShouldISellYet <support@shouldisellyet.com>"
"""

import argparse
import json
import os
import sys
import urllib.request

SITE = "https://shouldisellyet.com"
METRIC_LABEL = {
    "walkaway": "walk-away number",
    "equity": "equity",
    "lockin": "lock-in cost",
    "rate": "market 30-year rate",
    "rategap": "rate gap (market vs. yours)",
    "gain": "estimated gain",
}

# Percent-valued metrics format as "6.25%" in emails, point-valued as
# "1.5 points"; everything else is dollars.
PERCENT_METRICS = {"rate"}
POINT_METRICS = {"rategap"}


# ——— Pure calculation logic (mirrors web/my-report.html's client JS) ———

def pmt(principal, rate_pct, years=30):
    """Standard monthly mortgage payment (principal & interest only)."""
    n = years * 12
    i = rate_pct / 100 / 12
    if not (principal and principal > 0):
        return 0.0
    if not (i > 0):
        return principal / n
    return principal * i * (1 + i) ** n / ((1 + i) ** n - 1)


def latest_price(entry):
    """Most recent non-null monthly price from a ZIP entry's history, or None."""
    p = (entry or {}).get("h", {}).get("p") or []
    for v in reversed(p):
        if v is not None:
            return v
    return None


def scale_value(baseline_value, baseline_median, current_median):
    """Home value carried forward by the ZIP median's move since the watch
    was saved. Falls back to the unscaled baseline when either median is
    unavailable (e.g., the ZIP has no price history)."""
    if not baseline_median or not current_median:
        return baseline_value
    return baseline_value * (current_median / baseline_median)


def compute_metric(metric, inputs, current_median, market_rate):
    """Current value of the requested metric, or None if the saved inputs
    are insufficient to compute it (e.g., lock-in needs a rate)."""
    if metric == "rate":
        # Pure market number — needs no personal inputs at all.
        return market_rate
    if metric == "rategap":
        # Points between today's market rate and theirs — no dollar inputs.
        my_rate = inputs.get("rate")
        return None if my_rate is None else market_rate - my_rate
    value = scale_value(inputs.get("value"), inputs.get("baselineMedian"), current_median)
    if value is None:
        return None
    bal = inputs.get("bal") or 0
    if metric == "equity":
        return value - bal
    if metric == "walkaway":
        cost_pct = inputs.get("costPct", 8)
        return value * (1 - cost_pct / 100) - bal
    if metric == "gain":
        pp = inputs.get("pp")
        if pp is None:
            return None
        return value - pp
    if metric == "lockin":
        rate = inputs.get("rate")
        if rate is None or bal <= 0:
            return None
        now_pi = pmt(inputs.get("origAmt") or bal, rate)
        mkt_pi = pmt(bal, market_rate)
        return mkt_pi - now_pi
    return None


def is_crossed(value, direction, threshold):
    """True/False once evaluated; None if the metric couldn't be computed."""
    if value is None:
        return None
    return value < threshold if direction == "below" else value > threshold


def fmt(n):
    sign = "− " if n < 0 else ""
    return sign + "$" + f"{abs(round(n)):,}"


def fmt_metric(metric, n):
    """Dollars for personal numbers, percent/points for rate-style metrics."""
    if metric in PERCENT_METRICS:
        return f"{n:.2f}".rstrip("0").rstrip(".") + "%"
    if metric in POINT_METRICS:
        txt = f"{n:.1f}".rstrip("0").rstrip(".")
        return txt + (" point" if txt in ("1", "-1", "−1") else " points")
    return fmt(n)


def render_watch_email(metric, direction, threshold, current_value, zip_code, token):
    label = METRIC_LABEL.get(metric, metric)
    verb = "dropped below" if direction == "below" else "rose above"
    whose = "The" if metric in PERCENT_METRICS else "Your"
    subject = f"{whose} {label} just {verb} {fmt_metric(metric, threshold)} — EquityWatch"
    report_url = f"{SITE}/my-report.html?token={token}&zip={zip_code}" if token else f"{SITE}/?zip={zip_code}"
    html = f"""
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">\U0001F514 EquityWatch — your number alert</p>
  <h1 style="font-size:24px;margin:6px 0 4px">{whose} {label} just {verb} {fmt_metric(metric, threshold)}</h1>
  <p style="font-size:14px;color:#667085">You asked to hear about this. Current reading: <b>{fmt_metric(metric, current_value)}</b>.</p>
  <p style="margin:24px 0"><a href="{report_url}" style="background:#1f3a5f;color:#fff;padding:13px 24px;border-radius:10px;text-decoration:none;font-family:Arial,sans-serif;font-size:15px;font-weight:bold">Open your report →</a></p>
  <p style="font-size:12px;color:#98a2b3;line-height:1.5">This is your own number, computed from the inputs you saved and the latest public market data — not an appraisal. Not financial advice. Turn this alert off anytime from your report page.</p>
</div>"""
    return subject, html


def process_subscriber(sub, data_dir, market_rate):
    """Evaluate every watch entry for one subscriber against fresh ZIP data.

    Returns (updated_watches, emails) where emails is a list of
    (subject, html) tuples to send to sub["email"]. `updated_watches` should
    be written back only if it differs from sub["watches"] (crossed-flag
    changes or a fresh evaluation of a previously-unevaluable metric).
    """
    watches = sub.get("watches") or []
    if not watches:
        return watches, []
    inputs = sub.get("calc_inputs") or {}
    entry = load_zip_data(data_dir, sub.get("zip", ""))
    current_median = latest_price(entry) if entry else None

    updated, emails = [], []
    for w in watches:
        value = compute_metric(w["metric"], inputs, current_median, market_rate)
        crossed = is_crossed(value, w["direction"], w["threshold"])
        if crossed is None:
            updated.append(w)  # can't evaluate yet (e.g., lock-in needs a rate) — leave as-is
            continue
        was_crossed = bool(w.get("crossed"))
        if crossed and not was_crossed:
            emails.append(render_watch_email(
                w["metric"], w["direction"], w["threshold"], value,
                sub.get("zip", ""), sub.get("access_token", ""),
            ))
            updated.append({**w, "crossed": True})
        elif not crossed and was_crossed:
            updated.append({**w, "crossed": False})  # rearm for a future crossing
        else:
            updated.append(w)
    return updated, emails


# ——— I/O ———

def _req(url, headers=None, data=None, method=None):
    req = urllib.request.Request(
        url, headers=headers or {},
        data=json.dumps(data).encode() if data is not None else None,
        method=method or ("POST" if data is not None else "GET"),
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
        return json.loads(body) if body else None


def fetch_watchers(supabase_url, service_key):
    """Active/report subscribers who have at least one watch — filtered
    client-side (not via a jsonb-array PostgREST filter) to stay robust to
    exact-text-match quirks on jsonb equality."""
    url = (f"{supabase_url}/rest/v1/subscribers"
           f"?select=id,email,zip,access_token,calc_inputs,watches"
           f"&status=in.(active,report)")
    rows = _req(url, headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"}) or []
    return [r for r in rows if r.get("watches")]


def set_watches(supabase_url, service_key, sub_id, watches):
    _req(
        f"{supabase_url}/rest/v1/subscribers?id=eq.{sub_id}",
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"},
        data={"watches": watches},
        method="PATCH",
    )


def send_email(api_key, sender, to, subject, html):
    return _req("https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                data={"from": sender, "to": [to], "subject": subject, "html": html})


def load_zip_data(data_dir, zip_code):
    """{state,...entry} for a ZIP from the pipeline's published data, or None."""
    try:
        index = json.load(open(os.path.join(data_dir, "index.json")))
    except (OSError, json.JSONDecodeError):
        return None
    state = index.get(zip_code[:3])
    if not state:
        return None
    try:
        zips = json.load(open(os.path.join(data_dir, "zips", f"{state}.json")))
    except (OSError, json.JSONDecodeError):
        return None
    return zips.get(zip_code)


def load_market_rate(data_dir, fallback=6.58):
    try:
        meta = json.load(open(os.path.join(data_dir, "meta.json")))
        return meta.get("national", {}).get("mortgage", {}).get("now", fallback)
    except (OSError, json.JSONDecodeError):
        return fallback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="web/data", help="Path to the pipeline's published data dir")
    args = ap.parse_args()

    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    rs_key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("ALERT_FROM", "ShouldISellYet <support@shouldisellyet.com>")

    if not (sb_url and sb_key):
        print("Supabase secrets not configured — DRY RUN, nothing to check.")
        return

    watchers = fetch_watchers(sb_url, sb_key)
    total_watches = sum(len(w.get("watches") or []) for w in watchers)
    print(f"{len(watchers)} subscriber(s) with {total_watches} active watch(es) total.")
    market_rate = load_market_rate(args.data)
    sent = 0

    for sub in watchers:
        updated, emails = process_subscriber(sub, args.data, market_rate)
        for subject, html in emails:
            if rs_key:
                try:
                    send_email(rs_key, sender, sub["email"], subject, html)
                    sent += 1
                except Exception as e:  # one bad address must not kill the batch
                    print(f"send failed for {sub.get('email')}: {e}", file=sys.stderr)
            else:
                print(f"DRY RUN would email {sub.get('email')}: {subject}")
        if updated != sub.get("watches"):
            set_watches(sb_url, sb_key, sub["id"], updated)

    print(f"Sent {sent} personal-number alert(s).")


if __name__ == "__main__":
    main()
