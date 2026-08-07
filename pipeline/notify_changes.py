"""
ShouldISellYet — verdict-change alert engine.

Runs in the GitHub Action after each data refresh:
  1. Diffs the previous verdicts (snapshot taken before the pipeline ran)
     against the freshly generated ones.
  2. Looks up 'monitor' subscribers in Supabase for the changed ZIPs.
  3. Emails each subscriber via Resend.

Usage:
  python pipeline/notify_changes.py --old /tmp/old_zips --new web/data/zips

Required env (GitHub Actions secrets) — if any are missing, the script
prints what it WOULD send and exits 0, so the pipeline never breaks:
  SUPABASE_URL          e.g. https://abcd1234.supabase.co
  SUPABASE_SERVICE_KEY  service-role key (server-side only, never in the site)
  RESEND_API_KEY        from resend.com
Optional:
  ALERT_FROM            default: "ShouldISellYet <support@shouldisellyet.com>"
"""

import argparse
import glob
import json
import os
import sys
import urllib.request

WORDS = {"green": "HOLD", "yellow": "WATCH", "red": "ACT", "strong": "ACT"}
EMOJI = {"green": "🟢", "yellow": "🟡", "red": "🔴", "strong": "🔵"}
# "strong" = seller's market, the good direction — below green on this scale
SEVERITY = {"strong": -1, "green": 0, "yellow": 1, "red": 2}
SITE = "https://shouldisellyet.com"


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


def load_dir(path):
    """{zip: level} from a directory of {STATE}.json files."""
    out = {}
    for f in glob.glob(os.path.join(path, "*.json")):
        try:
            for z, d in json.load(open(f)).items():
                out[z] = d["l"]
        except (json.JSONDecodeError, KeyError):
            continue
    return out


def diff_verdicts(old, new):
    """ZIPs whose level changed: {zip: (old_level, new_level)}."""
    return {z: (old[z], lvl) for z, lvl in new.items()
            if z in old and old[z] != lvl}


def render_email(zip_code, old_level, new_level, address="", token=""):
    worse = SEVERITY[new_level] > SEVERITY[old_level]
    word = WORDS[new_level]
    # Personalize to the home if we have the address; fall back to the area.
    home = address.strip() if address and address.strip() else f"your home in {zip_code}"
    # Lead with the ZIP and the new verdict — that is the whole message, and
    # it survives a phone truncating at ~35 characters.
    subject = f"{EMOJI[new_level]} {zip_code} is now {word}"
    if new_level == "strong":
        headline = f"The market for {home} is unusually strong for sellers."
    elif old_level == "strong":
        headline = f"The market for {home} has cooled from a strong seller's market."
    else:
        headline = (
            f"The market for {home} has deteriorated." if worse
            else f"The market for {home} has improved.")
    action = {
        "red": "Multiple sell-signals are now tripped in your area. If selling was on your mind, it's time to act on a plan — review your numbers and talk to a local expert this week.",
        "yellow": "The market around your home needs watching. Know your numbers now so you can move quickly if it deteriorates further.",
        "green": "Pressure has eased in your area. No action needed — we'll keep an eye on it for you.",
        "strong": "Buyers are competing for homes in your area — multiple strength signals are past their thresholds. If selling was already on your mind, conditions favor you right now.",
    }[new_level]
    report_url = f"{SITE}/my-report.html?token={token}&zip={zip_code}" if token else f"{SITE}/?zip={zip_code}"
    html = f"""{preheader(headline + " " + action)}
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">🚦 MyMarketCheckup Alert</p>
  <h1 style="font-size:26px;margin:6px 0 4px">{EMOJI[new_level]} The market for your home is now <span style="color:{'#e03e36' if new_level=='red' else '#e8a317' if new_level=='yellow' else '#1f3a5f' if new_level=='strong' else '#12a150'}">{word}</span></h1>
  <p style="font-size:14px;color:#667085">{home} · changed from {WORDS[old_level]} → {word}</p>
  <p style="font-size:16px;line-height:1.6"><b>{headline}</b> {action}</p>
  <p style="margin:24px 0"><a href="{report_url}" style="background:#1f3a5f;color:#fff;padding:13px 24px;border-radius:10px;text-decoration:none;font-family:Arial,sans-serif;font-size:15px;font-weight:bold">Open your home's report →</a></p>
  <p style="font-size:12px;color:#98a2b3;line-height:1.5">We monitor local market conditions for the area your home is in — this is general market information, not an appraisal of your specific home. Data provided by <a href="https://www.redfin.com" style="color:#98a2b3">Redfin</a>, a national real estate brokerage. Not financial advice. You receive these because you set up MyMarketCheckup monitoring for this home.</p>
</div>"""
    return subject, html


def _req(url, headers=None, data=None):
    req = urllib.request.Request(url, headers=headers or {},
                                 data=json.dumps(data).encode() if data else None,
                                 method="POST" if data else "GET")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode() or "null")


def fetch_subscribers(supabase_url, service_key, zips):
    """Active monitor-plan subscribers for the given ZIPs (batched in_ queries)."""
    subs, zips = [], sorted(zips)
    for i in range(0, len(zips), 100):
        batch = ",".join(zips[i:i + 100])
        url = (f"{supabase_url}/rest/v1/subscribers"
               f"?select=email,zip,address,access_token"
               f"&plan=eq.monitor&status=eq.active&zip=in.({batch})")
        subs += _req(url, headers={"apikey": service_key,
                                   "Authorization": f"Bearer {service_key}"})
    return subs


def send_email(api_key, sender, to, subject, html):
    return _req("https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}",
                         "Content-Type": "application/json"},
                data={"from": sender, "to": [to], "subject": subject, "html": html})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", required=True)
    ap.add_argument("--new", required=True)
    ap.add_argument("--max-sends", type=int, default=2000)
    args = ap.parse_args()

    old, new = load_dir(args.old), load_dir(args.new)
    if not old:
        print("No previous verdicts (first run?) — nothing to diff.")
        return
    changes = diff_verdicts(old, new)
    print(f"{len(changes)} ZIPs changed verdict.")
    if not changes:
        return

    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    rs_key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("ALERT_FROM", "ShouldISellYet <support@shouldisellyet.com>")

    if not (sb_url and sb_key and rs_key):
        sample = list(changes.items())[:5]
        print("Secrets not configured — DRY RUN. Sample changes:", sample)
        return

    subs = fetch_subscribers(sb_url, sb_key, changes.keys())
    print(f"{len(subs)} subscribers to notify.")
    sent = 0
    for s in subs:
        if sent >= args.max_sends:
            print("Send cap reached.")
            break
        old_l, new_l = changes[s["zip"]]
        subject, html = render_email(s["zip"], old_l, new_l,
                                     address=s.get("address", ""),
                                     token=s.get("access_token", ""))
        try:
            send_email(rs_key, sender, s["email"], subject, html)
            sent += 1
        except Exception as e:  # one bad address must not kill the batch
            print(f"send failed for {s['email']}: {e}", file=sys.stderr)
    print(f"Sent {sent} alerts.")


if __name__ == "__main__":
    main()
