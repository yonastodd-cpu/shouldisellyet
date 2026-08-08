"""
ShouldISellYet — Growth Ops digest.

Runs at the end of each data refresh. Writes a verdict snapshot, diffs it
against last month's, and emails the operator one actionable digest.

  python pipeline/growth_digest.py [--data web/data] [--dry-run] [--out DIR]

Deterministic: every number and sentence comes from the data files and
Supabase counts. No LLM calls, no network beyond Supabase/Resend.

PRIVACY — governs this whole module. The digest reports COUNTS PER ZIP and
nothing else. It must never contain a subscriber name, email, address, or any
personal financial input (value, balance, equity, walk-away, rate, PITI).
Supabase reads below select only `zip` and aggregate, never contact columns.

Env (all optional — anything missing degrades to a labelled gap, never a crash):
  SUPABASE_URL, SUPABASE_SERVICE_KEY   subscriber / match-request counts
  RESEND_API_KEY, ALERT_FROM           delivery
  OPS_DIGEST_RECIPIENTS                comma-separated; overrides config
"""

import argparse
import csv
import glob
import json
import os
import sys
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from growth_config import (ANGLE_COUNT, DIGEST_RECIPIENTS, MIN_SOLD_FOR_ANGLE,
                           RATE_BURST_POINTS, is_dmv)

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = Path(__file__).parent / "snapshots"
WORD = {"green": "HOLD", "yellow": "WATCH", "red": "ACT", "strong": "STRONG"}
COLOR = {"green": "#1e7a42", "yellow": "#96650c", "red": "#c02f2f", "strong": "#1f3a5f"}
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def pretty_month(p):
    return f"{MONTHS[int(p[5:7]) - 1]} {p[:4]}" if len(p) == 7 else p


def prev_period(p):
    y, m = int(p[:4]), int(p[5:7])
    return f"{y - 1:04d}-12" if m == 1 else f"{y:04d}-{m - 1:02d}"


# ————— snapshot + diff —————

def load_current(data_dir):
    """zip -> {l, m, h, st} for every scored ZIP."""
    out = {}
    for f in sorted(Path(data_dir, "zips").glob("*.json")):
        st = f.stem
        for z, e in json.loads(f.read_text()).items():
            e["st"] = e.get("st") or st
            out[z] = e
    return out


def write_snapshot(entries, period):
    """Compact zip -> verdict-level map, committed to the repo.

    NOT written to archive/{YYYY-MM}: those are 90-day workflow artifacts and
    are gitignored, so a verdict history kept there would silently vanish and
    the diff would break every quarter. 387KB/month in-repo is durable.
    """
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    p = SNAP_DIR / f"verdicts-{period}.json"
    p.write_text(json.dumps({z: e["l"] for z, e in entries.items()},
                            separators=(",", ":"), sort_keys=True))
    return p


def load_snapshot(period):
    p = SNAP_DIR / f"verdicts-{period}.json"
    return json.loads(p.read_text()) if p.exists() else None


def diff_verdicts(prev, entries):
    """Flip buckets. 'strong' is an upside verdict, so →strong is an
    improvement even though it shares the ACT word."""
    RANK = {"red": 0, "yellow": 1, "green": 2, "strong": 3}
    flips = {"to_watch": [], "to_act": [], "to_hold": [], "to_strong": []}
    for z, e in entries.items():
        was = prev.get(z)
        now = e["l"]
        if was is None or was == now:
            continue
        if now == "yellow":
            flips["to_watch"].append(z)
        elif now == "red":
            flips["to_act"].append(z)
        elif now == "strong":
            flips["to_strong"].append(z)
        elif now == "green" and RANK[was] < RANK["green"]:
            flips["to_hold"].append(z)
    for k in flips:
        flips[k].sort(key=lambda z: (not is_dmv(z), z))
    return flips


# ————— places (city names, reused from the page generator) —————

def load_places():
    p = Path(__file__).parent / "data" / "zip_places.csv"
    if not p.exists():
        return {}
    return {r["zip"]: (r["city"], r["state"]) for r in csv.DictReader(open(p, encoding="utf-8"))}


def label(z, places):
    c = places.get(z)
    return f"{z} ({c[0]}, {c[1]})" if c else z


# ————— angle bank —————

def build_angles(entries, flips, places, period, want=ANGLE_COUNT):
    """Five paste-ready facts. Rules applied in order, DMV pool first, then
    national; a ZIP is used at most once so five rules give five distinct ZIPs."""
    used, out = set(), []
    month_name = MONTHS[int(period[5:7]) - 1] if len(period) == 7 else ""

    def pool(dmv_only):
        return [(z, e) for z, e in entries.items()
                if (is_dmv(z) == dmv_only)
                and (e.get("m", {}).get("sold") or 0) >= MIN_SOLD_FOR_ANGLE
                and z in places]

    def take(rule, dmv_only):
        cands = [(z, e) for z, e in pool(dmv_only) if z not in used]
        got = rule(cands)
        if got:
            used.add(got[0])
            out.append(got[1])
        return bool(got)

    def r_dom(c):
        c = [(z, e) for z, e in c if e.get("m", {}).get("domy") is not None]
        if not c: return None
        z, e = max(c, key=lambda t: abs(t[1]["m"]["domy"]))
        d = round(e["m"]["domy"])
        if d == 0: return None
        return z, (f"Homes in {label(z, places)} are taking {abs(d)} day{'s' if abs(d) != 1 else ''} "
                   f"{'longer' if d > 0 else 'less'} to sell than a year ago "
                   f"({round(e['m']['dom'])} days now).")

    def r_supply(c):
        c = [(z, e) for z, e in c if e.get("m", {}).get("mos") is not None]
        if not c: return None
        z, e = min(c, key=lambda t: t[1]["m"]["mos"])
        return z, (f"{label(z, places)} has just {e['m']['mos']:.1f} months of supply — "
                   f"at that pace every home listed there sells in under "
                   f"{max(1, round(e['m']['mos'] * 4))} weeks.")

    def r_price(c):
        c = [(z, e) for z, e in c if e.get("m", {}).get("spy") is not None]
        if not c: return None
        z, e = max(c, key=lambda t: abs(t[1]["m"]["spy"]))
        v = e["m"]["spy"]
        return z, (f"Typical sale prices in {label(z, places)} are "
                   f"{'up' if v >= 0 else 'down'} {abs(v) * 100:.1f}% versus a year ago.")

    def r_flip(c):
        ok = {z for z, _ in c}
        for bucket, verb in (("to_act", "crossed into ACT"), ("to_watch", "moved to WATCH"),
                             ("to_strong", "flipped to a strong seller's market"),
                             ("to_hold", "recovered to HOLD")):
            for z in flips.get(bucket, []):
                if z in ok:
                    return z, f"{label(z, places)} {verb} this month — its first change since the last data release."
        return None

    def r_season(c):
        best = None
        for z, e in c:
            h = e.get("h") or {}
            d = h.get("d") or []
            if not d or not h.get("s"): continue
            start = int(h["s"][5:7])
            by = defaultdict(list)
            for i, v in enumerate(d):
                if v is not None:
                    by[(start - 1 + i) % 12].append(v)
            cand = [(mo, sum(a) / len(a)) for mo, a in by.items() if len(a) >= 2]
            if not cand: continue
            mo, avg = min(cand, key=lambda t: t[1])
            if MONTHS[mo] == month_name:
                best = (z, f"{month_name} is historically the fastest-selling month in "
                           f"{label(z, places)} — homes move in about {round(avg)} days.")
                break
        return best

    for rule in (r_dom, r_supply, r_price, r_flip, r_season):
        if len(out) >= want: break
        if not take(rule, True):        # DMV first
            take(rule, False)           # then national
    # top up from the national pool if some rule found nothing
    for rule in (r_dom, r_supply, r_price):
        while len(out) < want and take(rule, False):
            pass
    return out[:want]


# ————— press hook —————

def press_hook(flips, entries, places):
    """Largest same-state cluster of same-direction flips."""
    best = None
    for bucket, phrase in (("to_act", "crossed into ACT"),
                           ("to_watch", "moved to WATCH"),
                           ("to_strong", "flipped to a strong seller's market"),
                           ("to_hold", "recovered to HOLD")):
        by_state = defaultdict(list)
        for z in flips.get(bucket, []):
            by_state[entries[z].get("st", "??")].append(z)
        for st, zips in by_state.items():
            if best is None or len(zips) > len(best["zips"]):
                best = {"bucket": bucket, "phrase": phrase, "state": st, "zips": sorted(zips)}
    return best


def write_hook_csv(hook, entries, places, out_dir, period):
    if not hook:
        return None
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / f"press-hook-{period}.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["zip", "city", "state", "verdict", "months_of_supply",
                    "price_yoy", "median_dom", "dom_yoy", "homes_for_sale", "homes_sold"])
        for z in hook["zips"]:
            e = entries[z]; m = e.get("m", {}); c = places.get(z, ("", ""))
            w.writerow([z, c[0], c[1], WORD.get(e["l"], e["l"]), m.get("mos"), m.get("spy"),
                        m.get("dom"), m.get("domy"), m.get("inv"), m.get("sold")])
    return p


# ————— Supabase counts (per-ZIP only, never contact columns) —————

def _sb(url, key, path, params):
    """GET against PostgREST. Returns (rows, error_string)."""
    q = urllib.parse.urlencode(params, safe="().,*")
    req = urllib.request.Request(f"{url}/rest/v1/{path}?{q}",
                                 headers={"apikey": key, "Authorization": f"Bearer {key}",
                                          "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r), None
    except Exception as exc:                       # missing table, bad key, offline
        return None, f"{type(exc).__name__}: {exc}"


def supabase_counts():
    """Per-ZIP counts. Selects ONLY the zip column plus aggregates — no email,
    no name, no address, no calc_inputs. Any failure returns a labelled gap.

    Returns (data, gaps) where data has subscribers/alerts/match_requests as
    {zip: count} and `recent` 30-day totals."""
    url, key = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_SERVICE_KEY", "")
    gaps = []
    if not (url and key):
        return None, ["Supabase not configured (SUPABASE_URL / SUPABASE_SERVICE_KEY unset)"]

    data = {"subscribers": Counter(), "alerts": Counter(),
            "match_requests": Counter(), "recent": {}}

    rows, err = _sb(url, key, "subscribers", {"select": "zip,plan,status,watches,created_at"})
    if err:
        gaps.append(f"subscribers table unreadable — {err}")
    else:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        new30 = plan30 = 0
        for r in rows or []:
            z = (r.get("zip") or "").strip()
            if z:
                data["subscribers"][z] += 1
                w = r.get("watches")
                if isinstance(w, list) and w:
                    data["alerts"][z] += len(w)
            if (r.get("created_at") or "") >= since:
                new30 += 1
                if r.get("plan") == "monitor":
                    plan30 += 1
        data["recent"]["new_subscribers_30d"] = new30
        data["recent"]["equitywatch_signups_30d"] = plan30
        data["recent"]["report_purchases_30d"] = sum(
            1 for r in rows or [] if r.get("plan") == "report" and (r.get("created_at") or "") >= since)

    rows, err = _sb(url, key, "match_requests", {"select": "zip,created_at"})
    if err:
        gaps.append(f"match_requests table unreadable (not deployed yet?) — {err}")
    else:
        since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
        n = 0
        for r in rows or []:
            z = (r.get("zip") or "").strip()
            if z:
                data["match_requests"][z] += 1
            if (r.get("created_at") or "") >= since:
                n += 1
        data["recent"]["match_requests_30d"] = n
    return data, gaps


def rate_now_and_prior(data_dir, prev_period_str):
    """(current, prior, asof). Prior comes from the stored rate stamp for last
    month — meta.json only ever holds the current figure."""
    meta = json.loads(Path(data_dir, "meta.json").read_text())
    mort = (meta.get("national") or {}).get("mortgage") or {}
    now, asof = mort.get("now"), mort.get("asof")
    prior = None
    p = SNAP_DIR / f"rate-{prev_period_str}.json"
    if p.exists():
        try:
            prior = json.loads(p.read_text()).get("now")
        except (ValueError, OSError):
            prior = None
    return now, prior, asof


def write_rate_stamp(period, now, asof):
    if now is None:
        return
    SNAP_DIR.mkdir(parents=True, exist_ok=True)
    (SNAP_DIR / f"rate-{period}.json").write_text(
        json.dumps({"now": now, "asof": asof}, separators=(",", ":")))


# ————— demo mode —————

def demo_inputs(entries, period):
    """Synthetic prior-month verdicts and Supabase counts so the digest can be
    previewed in full without waiting for a real month-over-month diff.

    Seeded, so the same data always yields the same preview. Every demo render
    carries a banner — a preview must never be mistakable for a real digest.
    """
    import random
    rnd = random.Random(20874)
    zips = sorted(entries)
    dmv_z = [z for z in zips if is_dmv(z)]
    flipped = set(rnd.sample(dmv_z, min(44, len(dmv_z)))) | set(rnd.sample(zips, min(330, len(zips))))
    swap = {"green": "yellow", "yellow": "green", "red": "yellow", "strong": "green"}
    prev = {z: (swap[entries[z]["l"]] if z in flipped else entries[z]["l"]) for z in zips}

    # counts land on ZIPs that actually flipped, which is what makes sections
    # 4 and 5 interesting; weighted toward the DMV, as real signups are.
    subs, alerts, mreq = Counter(), Counter(), Counter()
    pool = [z for z in flipped if is_dmv(z)] or list(flipped)
    for z in rnd.sample(pool, min(12, len(pool))):
        subs[z] = rnd.randint(2, 19)
        alerts[z] = rnd.randint(0, subs[z])
    for z in rnd.sample(pool, min(5, len(pool))):
        mreq[z] = rnd.randint(1, 4)
    counts = {"subscribers": subs, "alerts": alerts, "match_requests": mreq,
              "recent": {"new_subscribers_30d": 63, "equitywatch_signups_30d": 21,
                         "report_purchases_30d": 14, "match_requests_30d": 6}}
    return prev, counts


# ————— HTML —————

H = lambda s: (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
SITE = "https://shouldisellyet.com"

CSS = ("font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
       "font-size:15px;line-height:1.6;color:#1c2430")


def _sec(n, title, sowhat, body):
    return (f'<h2 style="font-size:16px;margin:30px 0 2px">{n}. {H(title)}</h2>'
            f'<div style="font-size:13px;color:#5c6673;margin-bottom:10px">'
            f'<b>So what:</b> {H(sowhat)}</div>{body}')


def _chip(level, text):
    return (f'<span style="display:inline-block;font-weight:700;color:{COLOR.get(level,"#1c2430")}">'
            f'{H(text)}</span>')


def render_digest(period, entries, flips, angles, hook, hook_csv, counts, gaps,
                  rate_now, rate_prior, rate_asof, places, baseline=False, demo=False,
                  research_html=""):
    pm = pretty_month(period)
    n_flips = sum(len(v) for v in flips.values())
    dmv_flips = [(b, z) for b, zs in flips.items() for z in zs if is_dmv(z)]

    # Full document with an explicit charset: the digest is full of → and —,
    # and without this both browsers and some mail clients guess Latin-1 and
    # render mojibake.
    parts = ['<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1">'
             f'<title>Growth Ops — {H(pretty_month(period))}</title></head>'
             '<body style="margin:0;padding:20px;background:#faf8f4">',
             f'<div style="{CSS};max-width:680px;margin:0 auto">',
             f'<div style="font-size:12px;letter-spacing:.12em;color:#8a7a55;font-weight:700">'
             f'GROWTH OPS DIGEST</div>',
             f'<h1 style="font-size:24px;margin:6px 0 2px">{H(pm)}</h1>',
             f'<div style="color:#5c6673;font-size:13px;margin-bottom:6px">'
             f'{len(entries):,} scored ZIPs · data through {H(pm)}</div>']

    if demo:
        parts.append('<div style="background:#fbe9e9;border:1px solid #ecc3c3;border-radius:8px;'
                     'padding:12px 14px;margin:14px 0;font-size:14px"><b>DEMO PREVIEW — not a real digest.</b> '
                     'Market data is real; the month-over-month flips and all subscriber counts are '
                     'synthetic sample data, generated to show every section populated.</div>')
    if baseline:
        parts.append('<div style="background:#faf1dd;border:1px solid #e8d5a8;border-radius:8px;'
                     'padding:12px 14px;margin:14px 0;font-size:14px"><b>Baseline run.</b> '
                     'No prior month snapshot existed, so there are no flips to report. '
                     'Next refresh will diff against this one.</div>')

    if research_html:
        parts.append(research_html)

    # 1 — headline counts
    rows = "".join(
        f'<tr><td style="padding:4px 14px 4px 0">{_chip(lv, w)}</td>'
        f'<td style="padding:4px 0;font-weight:700">{len(flips[k]):,}</td></tr>'
        for k, lv, w in (("to_act", "red", "→ ACT"), ("to_watch", "yellow", "→ WATCH"),
                         ("to_hold", "green", "→ HOLD"), ("to_strong", "strong", "→ STRONG")))
    body = f'<table style="border-collapse:collapse;font-size:14px">{rows}</table>'
    if dmv_flips:
        items = "".join(
            f'<li>{_chip(entries[z]["l"], WORD.get(entries[z]["l"], ""))} — {H(label(z, places))}</li>'
            for _, z in sorted(dmv_flips, key=lambda t: t[1]))
        body += (f'<div style="margin-top:12px;font-size:14px"><b>DMV flips ({len(dmv_flips)}):</b>'
                 f'<ul style="margin:6px 0 0;padding-left:20px">{items}</ul></div>')
    elif not baseline:
        body += '<div style="margin-top:10px;font-size:14px;color:#5c6673">No DMV flips this month.</div>'
    parts.append(_sec(1, "Flips this month", "Anything in the DMV list is a call or a post this week.", body))

    # 2 — angle bank
    items = "".join(f'<li style="margin-bottom:8px">{H(a)}</li>' for a in angles) or \
            '<li style="color:#5c6673">No ZIP cleared the minimum-sales bar for a reliable angle.</li>'
    parts.append(_sec(2, "Local angle bank", "Paste any of these straight into a post — numbers are already filled in.",
                      f'<ol style="margin:0;padding-left:20px;font-size:14px">{items}</ol>'))

    # 3 — press hook
    if hook and hook["zips"]:
        st = hook["state"]
        line = f'<b>{len(hook["zips"])} {H(st)} ZIP codes {H(hook["phrase"])} this month.</b>'
        csvline = (f'<div style="font-size:13px;color:#5c6673;margin-top:6px">Supporting rows: '
                   f'<code>{H(hook_csv.name)}</code> in this month\'s archive folder.</div>'
                   if hook_csv else "")
        body = f'<div style="font-size:15px">{line}</div>{csvline}'
    else:
        body = '<div style="font-size:14px;color:#5c6673">No same-state cluster this month — skip the pitch.</div>'
    parts.append(_sec(3, "Press hook of the month", "One line a local reporter can run with; CSV backs it up.", body))

    # 4 — subscriber-adjacent flips
    if counts:
        lines = []
        for bucket, zs in flips.items():
            for z in zs:
                s, a = counts["subscribers"].get(z, 0), counts["alerts"].get(z, 0)
                if s or a:
                    city = places.get(z, ("", ""))[0]
                    lines.append(f'<li><b>{z} → {WORD.get(entries[z]["l"], "")}</b> · {s} subscriber'
                                 f'{"s" if s != 1 else ""}, {a} alert{"s" if a != 1 else ""} — '
                                 f'consider a {H(city or z)} group post this week.</li>')
        body = (f'<ul style="margin:0;padding-left:20px;font-size:14px">{"".join(sorted(lines))}</ul>'
                if lines else
                '<div style="font-size:14px;color:#5c6673">No flip this month landed in a ZIP with subscribers.</div>')
    else:
        body = '<div style="font-size:14px;color:#5c6673">Not available — Supabase counts unreadable (see gaps below).</div>'
    parts.append(_sec(4, "Subscriber-adjacent flips", "These people just got an alert — meet them where they already are.", body))

    # 5 — warm ZIPs. The "So what" line used to read "pitch /partners agents
    # here" and each line item called its ZIP "good agent-recruitment territory".
    # The ZIP-sponsorship program was taken down 2026-08-05 (/partners is now a
    # stub that redirects to the homepage) and its draft agreement was deleted
    # 2026-08-08, so this email was sending the operator to a redirect to recruit
    # for a program that is not operating. The DATA is untouched and still the
    # best signal in the digest — improving markets that already have real users.
    # Do NOT put an agent-recruitment call to action back here: a monthly email
    # the operator follows without re-reading the decision is exactly how a
    # retired program restarts by habit. This comment and docs/GROWTH-OPS.md
    # row 5 are a matched pair — change one, change the other.
    if counts:
        warm = []
        for z in flips["to_hold"] + flips["to_strong"]:
            s = counts["subscribers"].get(z, 0)
            mr = counts["match_requests"].get(z, 0)
            if s or mr:
                warm.append(f'<li><b>{H(label(z, places))}</b> → {WORD.get(entries[z]["l"], "")} · '
                            f'{s} subscriber{"s" if s != 1 else ""}, {mr} match request'
                            f'{"s" if mr != 1 else ""}.</li>')
        body = (f'<ul style="margin:0;padding-left:20px;font-size:14px">{"".join(sorted(warm))}</ul>'
                if warm else
                '<div style="font-size:14px;color:#5c6673">No improving ZIP has subscribers or match requests yet.</div>')
    else:
        body = '<div style="font-size:14px;color:#5c6673">Not available — Supabase counts unreadable (see gaps below).</div>'
    parts.append(_sec(5, "Warm ZIPs (referral triggers)", "Improving markets where you already have users — post locally or follow up directly.", body))

    # 6 — rate line
    if rate_now is None:
        body = '<div style="font-size:14px;color:#5c6673">Rate unavailable this refresh — pipeline fetch returned nothing.</div>'
    else:
        d = None if rate_prior is None else rate_now - rate_prior
        head = f'<div style="font-size:20px;font-weight:700">{rate_now:.2f}%</div>'
        sub = (f'<div style="font-size:13px;color:#5c6673">30-year fixed, as of {H(rate_asof or "latest")}'
               + (f' · was {rate_prior:.2f}% last month ({d:+.2f} pts)' if d is not None else
                  ' · no prior month on file yet') + '</div>')
        burst = ""
        if d is not None and abs(d) >= RATE_BURST_POINTS:
            burst = ('<div style="background:#e9f4ee;border:1px solid #bcdcc9;border-radius:8px;'
                     'padding:12px 14px;margin-top:10px;font-size:14px"><b>Burst window open — '
                     f'run the rate-drop play.</b> Rates moved {d:+.2f} points since last month.</div>')
        body = head + sub + burst
    parts.append(_sec(6, "Mortgage rate", "A big move is a marketing window; a small one is noise.", body))

    # 7 — scorecard
    r = (counts or {}).get("recent", {})
    def cell(lbl, key):
        v = r.get(key)
        val = f'{v:,}' if isinstance(v, int) else '<span style="color:#8a8578">not tracked yet</span>'
        return f'<tr><td style="padding:4px 14px 4px 0;color:#5c6673">{H(lbl)}</td><td style="padding:4px 0"><b>{val}</b></td></tr>'
    body = ('<table style="border-collapse:collapse;font-size:14px">'
            + cell("New subscribers", "new_subscribers_30d")
            + cell("MyMarketCheckup signups", "equitywatch_signups_30d")
            + cell("Report purchases", "report_purchases_30d")
            + cell("Match requests", "match_requests_30d")
            + '<tr><td style="padding:4px 14px 4px 0;color:#5c6673">Visits by utm_source</td>'
              '<td style="padding:4px 0"><b><span style="color:#8a8578">not tracked yet</span></b> '
              '<span style="font-size:12px;color:#8a8578">— no analytics installed</span></td></tr>'
            + '</table>')
    parts.append(_sec(7, "Scorecard — last 30 days", "If these are flat, the sections above are the levers.", body))

    if gaps:
        parts.append('<div style="margin-top:26px;padding:12px 14px;background:#fbf8f1;border:1px solid #e6dcc3;'
                     'border-radius:8px;font-size:13px;color:#5c6673"><b>Gaps this run:</b><ul style="margin:6px 0 0;'
                     'padding-left:18px">' + "".join(f"<li>{H(g)}</li>" for g in gaps) + '</ul></div>')

    # The citation belongs here even though the digest is internal: the angle
    # bank exists to be pasted verbatim into public posts, so the credit has to
    # travel with the numbers to wherever they end up. Exactly once, linked —
    # see docs/ATTRIBUTION.md.
    parts.append('<div style="margin-top:26px;padding-top:12px;border-top:1px solid #e7e2d8;'
                 'font-size:12px;color:#8a8578">Counts are per ZIP only — this digest never contains '
                 'subscriber names, emails, addresses, or any personal financial input. '
                 f'Generated automatically from the {H(pm)} data refresh. '
                 'Market figures: Data provided by '
                 '<a href="https://www.redfin.com" style="color:#8a8578">Redfin</a>, '
                 'a national real estate brokerage — keep this credit on anything you '
                 'post from the angle bank.</div></div>'
                 '</body></html>')
    return "".join(parts)


# ————— delivery —————


# ————— Research release (ShouldISellYet Research) —————

RESEARCH_DIR = Path(__file__).parent / "research"


def load_research(period):
    p = RESEARCH_DIR / f"research-{period}.json"
    return json.loads(p.read_text()) if p.exists() else None


def research_headline(rep):
    """One sentence, the same discipline as the release page: superlatives
    never reach across the source seam."""
    rec = rep["records"]
    wsi, delta = rec.get("wsi"), rec.get("delta")
    s = f"Warning signs are flashing in {wsi:.1f}% of scored U.S. ZIP markets"
    if delta is not None:
        s += (f", up from {rec['prev_wsi']:.1f}% last month" if delta > 0 else
              f", down from {rec['prev_wsi']:.1f}% last month" if delta < 0 else
              ", unchanged from last month")
        hs, ls = rec.get("highest_since"), rec.get("lowest_since")
        if delta > 0:
            s += (" — the highest share in the index's continuous history"
                  if hs == "record" else f" — the highest share since {pretty_month(hs)}")
        elif delta < 0:
            s += (" — the lowest share in the index's continuous history"
                  if ls == "record" else f" — the lowest share since {pretty_month(ls)}")
    return s + "."


def strongest_record(rep):
    """The one fact a pitch leads with, strongest first."""
    rec = rep["records"]
    delta = rec.get("delta")
    if delta is not None and delta > 0 and rec.get("highest_since") == "record":
        return "a record high for the index's continuous history"
    if delta is not None and delta < 0 and rec.get("lowest_since") == "record":
        return "a record low for the index's continuous history"
    if delta is not None and delta > 0 and rec.get("highest_since") not in (None, "record"):
        return f"the highest share since {pretty_month(rec['highest_since'])}"
    if delta is not None and delta < 0 and rec.get("lowest_since") not in (None, "record"):
        return f"the lowest share since {pretty_month(rec['lowest_since'])}"
    if rec.get("run_length", 0) >= 3:
        return (f"the {rec['run_length']}th consecutive monthly "
                f"{'rise' if rec['run_direction'] == 'up' else 'decline'}")
    return None


def research_bullets(rep):
    out = []
    sm = rep.get("state_moves") or []
    if sm:
        worst = max(sm, key=lambda r: r["delta"])
        best = min(sm, key=lambda r: r["delta"])
        if worst["delta"] > 0:
            out.append(f"Biggest deterioration: {worst['key']} — warning share "
                       f"{worst['share']:.1f}% (+{worst['delta']:.1f} pts).")
        if best["delta"] < 0:
            out.append(f"Biggest improvement: {best['key']} — warning share "
                       f"{best['share']:.1f}% ({best['delta']:.1f} pts).")
    ts = rep.get("top_streaks") or []
    if ts:
        s = ts[0]
        place = f"{s['city']}, {s['state']}" if s.get("city") else s.get("state", "")
        out.append(f"Longest current warning streak: {s['zip']} ({place}), "
                   f"{s['months']} months at WATCH or ACT.")
    n = len(rep.get("flips_to_warning") or [])
    if n:
        out.append(f"{n:,} ZIPs crossed the danger line this month (CSV in the release).")
    return out[:3]


def pitch_draft(rep):
    """Subject + ~120-word body, written to be REVIEWED and sent by a human.
    Nothing here auto-sends, ever."""
    rec = rep["records"]
    month = rep["pretty_month"]
    rel = f"{SITE}/research/{rep['month']}/"
    record = strongest_record(rep)
    hook = record or f"at {rec['wsi']:.1f}% of scored ZIP markets"
    subject = (f"Warning signs in {rec['wsi']:.1f}% of U.S. ZIP housing markets"
               + (f" — {record}" if record else "") + f" ({month} data)")
    body = f"""Hi {{name}},

New monthly number you can use: ShouldISellYet Research tracks a Warning-Sign
Index — the share of ~25,000 scored U.S. ZIP housing markets showing warning
signs (elevated supply, falling prices, slowing sales) against fixed,
published danger lines. For {month}: {rec['wsi']:.1f}%, {hook}.

The release has state and metro league tables, the ZIPs that crossed the
danger line this month, and free downloadable CSVs (state, metro, ZIP level)
— free to use with citation. Local numbers for your coverage area are
pre-computed on the page.

{rel}

Happy to pull a custom cut for your market. Methodology and the FHFA
backtest are linked from the release.

— ShouldISellYet Research
{SITE}/research/"""
    return subject, body


def research_section(rep, out_dir):
    """The digest's 'Research release' block: the operator's launch kit —
    headline, bullets, every asset link, and the pitch draft inline."""
    if not rep:
        return ""
    month = rep["month"]
    rel = f"{SITE}/research/{month}/"
    subject, body = pitch_draft(rep)
    bullets = "".join(f"<li style='margin:5px 0'>{H(b)}</li>" for b in research_bullets(rep))
    assets = " · ".join(
        f'<a href="{rel}{f}">{t}</a>' for f, t in [
            ("", "release page"), ("wsi-chart.png", "WSI chart"),
            ("state-map.png", "state map"), ("wsi-history.csv", "history CSV"),
            (f"zip-flips-{month}.csv", "flip list")])
    return (
        '<h2 style="font-size:17px;margin:26px 0 6px">📊 Research release — '
        f'{H(rep["pretty_month"])}</h2>'
        f'<div style="font-size:15px;line-height:1.6"><b>{H(research_headline(rep))}</b></div>'
        f'<ul style="font-size:14px;line-height:1.55;padding-left:20px">{bullets}</ul>'
        f'<div style="font-size:13px;color:#5c6673">Assets: {assets}</div>'
        '<div style="background:#f4f2ec;border:1px solid #e7e2d8;border-radius:8px;'
        'padding:12px 14px;margin:12px 0;font-size:13px;line-height:1.55">'
        f'<div style="color:#8a7a55;font-weight:700;letter-spacing:.08em;font-size:11px">'
        'PITCH DRAFT — REVIEW, PERSONALISE, SEND YOURSELF</div>'
        f'<div style="margin-top:6px"><b>Subject:</b> {H(subject)}</div>'
        f'<pre style="white-space:pre-wrap;font-family:inherit;margin:8px 0 0">{H(body)}</pre>'
        '</div>')


def write_press_drafts(rep, out_dir):
    """PRESS_LIST env (comma-separated emails) → one draft file per outlet in
    the archive folder. Generated, never sent — sending is a human decision,
    and the file layout makes that the only possible flow."""
    raw = os.environ.get("PRESS_LIST", "").strip()
    if not raw or not rep:
        return 0
    subject, body = pitch_draft(rep)
    drafts = out_dir / "press-drafts"
    drafts.mkdir(parents=True, exist_ok=True)
    n = 0
    for addr in [a.strip() for a in raw.split(",") if a.strip()]:
        name = addr.split("@")[0].replace(".", " ").title()
        (drafts / f"{addr.replace('@', '_at_')}.txt").write_text(
            f"To: {addr}\nSubject: {subject}\n\n" + body.replace("{name}", name),
            encoding="utf-8")
        n += 1
    return n


def send_email(subject, html, recipients):
    key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("ALERT_FROM", "ShouldISellYet <support@shouldisellyet.com>")
    if not key:
        print("RESEND_API_KEY unset — digest not emailed (rendered file still written)")
        return False
    body = json.dumps({"from": sender, "to": recipients, "subject": subject, "html": html}).encode()
    req = urllib.request.Request("https://api.resend.com/emails", data=body, method="POST",
                                 headers={"Authorization": f"Bearer {key}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
        return True
    except Exception as exc:
        print(f"resend error: {type(exc).__name__}: {exc}")
        return False


def recipients():
    env = os.environ.get("OPS_DIGEST_RECIPIENTS", "").strip()
    return [x.strip() for x in env.split(",") if x.strip()] or list(DIGEST_RECIPIENTS)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "web" / "data"))
    ap.add_argument("--out", default="", help="archive dir for the digest + csv (default archive/{period})")
    ap.add_argument("--dry-run", action="store_true", help="render, don't email")
    ap.add_argument("--force-period", default="", help="override the data period (testing)")
    ap.add_argument("--demo", action="store_true",
                    help="preview with synthetic flips and counts; never emails, never writes snapshots")
    args = ap.parse_args()

    meta = json.loads(Path(args.data, "meta.json").read_text())
    period = args.force_period or meta.get("period", "")
    out_dir = Path(args.out) if args.out else ROOT / "archive" / period

    entries = load_current(args.data)
    places = load_places()
    prev = load_snapshot(prev_period(period))
    baseline = prev is None
    flips = diff_verdicts(prev or {}, entries) if prev else \
            {"to_watch": [], "to_act": [], "to_hold": [], "to_strong": []}

    if args.demo:
        prev, counts = demo_inputs(entries, period)
        baseline = False
        flips = diff_verdicts(prev, entries)
        gaps = []
    else:
        counts, gaps = supabase_counts()
    rate_now, rate_prior, rate_asof = rate_now_and_prior(args.data, prev_period(period))
    angles = build_angles(entries, flips, places, period)
    hook = press_hook(flips, entries, places) if not baseline else None
    hook_csv = write_hook_csv(hook, entries, places, out_dir, period)

    if args.demo and rate_prior is None and rate_now is not None:
        rate_prior = round(rate_now - 0.31, 2)      # show the burst banner
    research = load_research(period)
    html = render_digest(period, entries, flips, angles, hook, hook_csv, counts, gaps,
                         rate_now, rate_prior, rate_asof, places,
                         baseline=baseline, demo=args.demo,
                         research_html=research_section(research, out_dir))

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"digest-{period}.html").write_text(html, encoding="utf-8")
    n_drafts = write_press_drafts(research, out_dir)
    if n_drafts:
        print(f"press drafts: {n_drafts} file(s) in {out_dir / 'press-drafts'} — review and send by hand")

    # Snapshots written LAST: if anything above throws, this month's snapshot
    # isn't recorded and the next run still has a clean prior to diff against.
    # Demo renders never touch them — a preview must not poison the real diff.
    if not args.demo:
        write_snapshot(entries, period)
        write_rate_stamp(period, rate_now, rate_asof)

    n = sum(len(v) for v in flips.values())
    dmv = sum(1 for zs in flips.values() for z in zs if is_dmv(z))
    subject = f"Growth Ops — {pretty_month(period)}: {n} flips, {dmv} local"
    print(f"digest: {subject}")
    print(f"  angles {len(angles)} · hook {(hook or {}).get('state', '—')} "
          f"{len((hook or {}).get('zips', []))} · gaps {len(gaps)}")
    print(f"  written {out_dir / f'digest-{period}.html'}")
    if args.demo:
        print("  --demo: synthetic flips/counts, nothing emailed, no snapshot written")
        return
    if args.dry_run:
        print("  --dry-run: not emailed")
        return
    if send_email(subject, html, recipients()):
        print(f"  emailed {len(recipients())} recipient(s)")


if __name__ == "__main__":
    main()
