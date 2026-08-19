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


# ————— Preheader —————
# The inbox gives three slots: sender, subject, then whatever text it scrapes
# first from the body. That third slot was landing on the visible brand
# header, so a row repeated the product name and said the news once. This
# block is invisible when rendered but is the first text a client finds, so
# it becomes the preview line. The trailing zero-width joiners stop clients
# padding the preview with markup that follows.
def preheader(text):
    return ('<div style="display:none;font-size:1px;color:#faf8f4;line-height:1px;'
            'max-height:0;max-width:0;opacity:0;overflow:hidden">' + text
            + "&#8204;&nbsp;" * 60 + "</div>")


def render_watch_email(metric, direction, threshold, current_value, zip_code, token):
    label = METRIC_LABEL.get(metric, metric)
    verb = "dropped below" if direction == "below" else "rose above"
    whose = "The" if metric in PERCENT_METRICS else "Your"
    # The number they chose to watch, and what it just did. No brand — the
    # sender already says it.
    subject = f"{whose} {label} just {verb} {fmt_metric(metric, threshold)}"
    report_url = f"{SITE}/my-report.html?token={token}&zip={zip_code}" if token else f"{SITE}/?zip={zip_code}"
    html = f"""{preheader(f"You asked to hear when this crossed {fmt_metric(metric, threshold)}. It now reads {fmt_metric(metric, current_value)} in {zip_code}.")}
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">\U0001F514 MyMarketCheckup — your number alert</p>
  <h1 style="font-size:24px;margin:6px 0 4px">{whose} {label} just {verb} {fmt_metric(metric, threshold)}</h1>
  <p style="font-size:14px;color:#667085">You asked to hear about this. Current reading: <b>{fmt_metric(metric, current_value)}</b>.</p>
  <p style="margin:24px 0"><a href="{report_url}" style="background:#1f3a5f;color:#fff;padding:13px 24px;border-radius:10px;text-decoration:none;font-family:Arial,sans-serif;font-size:15px;font-weight:bold">Open your report →</a></p>
  <p style="font-size:12px;color:#98a2b3;line-height:1.5">This is your own number, computed from the inputs you saved and the latest public market data — not an appraisal. Not financial advice. Turn this alert off anytime from your report page.</p>
</div>"""
    return subject, html


# ——— The velocity alert (metric "velocity") ———
# Stateful, not threshold-based: fires when the market's gathering STATE
# escalates past the baseline recorded at save time, then re-baselines so one
# worsening produces one email. De-escalation quietly lowers the baseline —
# nobody wants "good news" spam, and re-arming means a future worsening from
# the better level fires again. States come from zip_velocity (schema-v20),
# fetched in one query for every watched ZIP by main().
VEL_RANK = {"improving": 0, "stable": 1, "drifting": 2, "deteriorating fast": 3}
VEL_PHRASE = {
    "drifting": "has started drifting toward its warning lines",
    "deteriorating fast": "is now moving toward its warning lines fast",
}


def render_velocity_email(old_state, new_state, zip_code, token):
    phrase = VEL_PHRASE.get(new_state, f"changed from {old_state} to {new_state}")
    subject = f"{zip_code}: your market {phrase}"
    html = f"""{preheader(f"Direction change in {zip_code}: {old_state} \u2192 {new_state}. Your full report has the month-by-month pace.")}
<div style="font-family:system-ui,-apple-system,sans-serif;max-width:520px;margin:0 auto;color:#1c2430;line-height:1.65">
<p>You asked to hear if the market in <b>{zip_code}</b> started moving toward a warning line.</p>
<p>It has: our approach-velocity read just moved from <b>{old_state}</b> to <b>{new_state}</b>.
A state change is about direction and pace \u2014 not a verdict flip \u2014 but this is
how turns usually start, months before prices move.</p>
<p style="margin:22px 0"><a href="https://shouldisellyet.com/my-report.html?token={token}"
   style="background:#1f3a5f;color:#faf8f4;text-decoration:none;padding:13px 22px;border-radius:8px;font-weight:600;display:inline-block">
   See which dials are moving \u2192</a></p>
<p style="font-size:13px;color:#8a8578">ShouldISellYet \u00b7 you set this alert on your report page \u2014
manage or turn it off there. <a href="https://kfbjooteazwvdsonthba.supabase.co/functions/v1/unsubscribe?token={token}">Unsubscribe</a></p>
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

    # The reading's basis. Legacy entries carry no `b` at all, so an existing
    # watch (no `basis` key) matches a legacy entry and nothing changes today.
    entry_basis = (entry or {}).get("b", "")

    updated, emails = [], []
    vel_state = sub.get("_vel_state")   # attached by main() from zip_velocity
    for w in watches:
        # ——— the migration guard ———
        # A watch scales the subscriber's own baseline by the current median.
        # When that median stops being a closed-sale figure and becomes a
        # list-price figure it steps UP for reasons that have nothing to do
        # with this market, and every threshold above it would cross at once.
        # So the first run on a new basis re-baselines silently and sends
        # nothing — exactly what the velocity branch below already does for a
        # first real read. Per-watch and automatic: once a watch has been
        # re-baselined its alerts resume by themselves, with no global switch
        # left switched off.
        if w.get("basis", "") != entry_basis:
            if w.get("metric") == "velocity":
                fresh = vel_state if vel_state in VEL_RANK else w.get("baseline", "unknown")
                updated.append({**w, "basis": entry_basis, "baseline": fresh})
            else:
                v = compute_metric(w["metric"], inputs, current_median, market_rate)
                c = is_crossed(v, w["direction"], w["threshold"])
                updated.append({**w, "basis": entry_basis,
                                "crossed": bool(c) if c is not None else bool(w.get("crossed"))})
            continue
        if w.get("metric") == "velocity":
            base = w.get("baseline", "unknown")
            cur = vel_state
            if cur is None or cur == "unknown" or cur not in VEL_RANK:
                updated.append(w)          # no fresh read — leave untouched
            elif base not in VEL_RANK:
                updated.append({**w, "baseline": cur})   # first real read becomes baseline
            elif VEL_RANK[cur] > VEL_RANK[base]:
                emails.append(render_velocity_email(base, cur, sub.get("zip", ""),
                                                    sub.get("access_token", "")))
                updated.append({**w, "baseline": cur})
            elif VEL_RANK[cur] < VEL_RANK[base]:
                updated.append({**w, "baseline": cur})   # quiet re-arm downward
            else:
                updated.append(w)
            continue
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
           # active/report exist only via the payment webhook, which stamps
           # confirmed_at (schema-v19) — payment-verified addresses, the
           # double-opt-in invariant. Never widen this filter.
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

    # One query hydrates every velocity watch: current gathering state per
    # watched ZIP from zip_velocity (schema-v20). Missing rows leave
    # _vel_state None and the watch is left untouched this run.
    vel_zips = sorted({s.get("zip") for s in watchers
                       if any((w or {}).get("metric") == "velocity"
                              for w in (s.get("watches") or []))
                       and s.get("zip")})
    vel_states = {}
    if vel_zips:
        try:
            rows = _req(f"{sb_url}/rest/v1/zip_velocity?select=zip,payload"
                        f"&zip=in.({','.join(vel_zips)})",
                        headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}"})
            vel_states = {r["zip"]: (r.get("payload") or {}).get("state")
                          for r in (rows or [])}
        except Exception as e:
            print(f"zip_velocity read failed — velocity watches skipped: {e}", file=sys.stderr)
    for s in watchers:
        s["_vel_state"] = vel_states.get(s.get("zip"))
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
