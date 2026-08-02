"""
ShouldISellYet — weekly rate check.

Emails ONLY when the 30-year rate has moved at least RATE_BURST_POINTS since
the last digest. Silence is the normal outcome; a quiet job that emails every
week trains the operator to ignore it.

  python pipeline/rate_watch.py [--dry-run] [--force-rate 6.10]

Reuses fetch_data.fetch_mortgage_rates(), so it inherits the PMMS-primary /
FRED-fallback behaviour and its warnings. Writes no snapshot: the monthly
digest owns the rate stamp, and this job only compares against it.
"""

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_data import fetch_mortgage_rates
from growth_config import RATE_BURST_POINTS
from growth_digest import (SNAP_DIR, pretty_month, recipients, send_email)

import json


def last_stamp():
    """Most recent rate-{YYYY-MM}.json the monthly digest wrote."""
    files = sorted(SNAP_DIR.glob("rate-*.json"))
    if not files:
        return None, None
    p = files[-1]
    try:
        return json.loads(p.read_text()).get("now"), p.stem.replace("rate-", "")
    except (ValueError, OSError):
        return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force-rate", type=float, default=None,
                    help="skip the fetch and use this rate (testing both paths)")
    args = ap.parse_args()

    prior, period = last_stamp()
    if prior is None:
        print("no prior rate stamp yet — nothing to compare; staying silent")
        return

    if args.force_rate is not None:
        now = args.force_rate
        print(f"--force-rate {now}")
    else:
        r = fetch_mortgage_rates()
        if not r:
            print("rate fetch failed — staying silent (the monthly digest will report the gap)")
            return
        now = r["now"]

    delta = now - prior
    print(f"now {now:.2f}% vs {prior:.2f}% ({period}) = {delta:+.2f} pts "
          f"· threshold ±{RATE_BURST_POINTS}")
    if abs(delta) < RATE_BURST_POINTS:
        print("below threshold — no email sent")
        return

    direction = "dropped" if delta < 0 else "rose"
    play = ("Run the rate-drop play: buyers just gained purchasing power, which is the "
            "moment sellers care about." if delta < 0 else
            "Rates rose — the pressure story is live: every point costs your sellers' buyers "
            "real purchasing power.")
    subject = f"Rate moved {delta:+.2f} — burst window open"
    html = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"></head>'
            f'<body style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
            f'font-size:15px;line-height:1.6;color:#1c2430;padding:20px">'
            f'<div style="max-width:560px;margin:0 auto">'
            f'<div style="font-size:12px;letter-spacing:.12em;color:#8a7a55;font-weight:700">'
            f'RATE WATCH</div>'
            f'<h1 style="font-size:22px;margin:6px 0 4px">The 30-year rate {direction} '
            f'{abs(delta):.2f} points</h1>'
            f'<div style="font-size:28px;font-weight:700;margin:10px 0 2px">{now:.2f}%</div>'
            f'<div style="color:#5c6673;font-size:13px">was {prior:.2f}% at the '
            f'{pretty_month(period)} data refresh</div>'
            f'<div style="background:#e9f4ee;border:1px solid #bcdcc9;border-radius:8px;'
            f'padding:12px 14px;margin-top:14px"><b>Burst window open.</b> {play}</div>'
            f'<div style="margin-top:20px;padding-top:12px;border-top:1px solid #e7e2d8;'
            f'font-size:12px;color:#8a8578">Sent only when the move clears '
            f'{RATE_BURST_POINTS} points — no email otherwise. Contains no personal data.'
            f'</div></div></body></html>')

    if args.dry_run:
        print(f"--dry-run: would email {recipients()} · subject: {subject}")
        return
    if send_email(subject, html, recipients()):
        print(f"emailed {len(recipients())} recipient(s): {subject}")


if __name__ == "__main__":
    main()
