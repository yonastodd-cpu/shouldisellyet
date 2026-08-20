"""
ShouldISellYet — marketing queue generator.

    python3 pipeline/marketing_tasks.py [--data web/data] [--dry-run]
                                        [--force-period YYYY-MM] [--now ISO]

Runs in the refresh workflow (update.yml, changed==true path) BEFORE
growth_digest.py, so the digest reports this refresh's queue and not last
refresh's. Derives NOTHING itself — every candidate reuses a fact another
module already computed:

  research     pipeline/research/research-{period}.json (growth_digest.load_research)
  velocity     web/data/velocity-aggregates.json (gathering rows) + the
               committed pipeline/velocity/velocity-{prev}.json for crossings
  angles       growth_digest.build_angles — the digest's own five facts
  receipts     public.press_corroboration via PostgREST (service key)
  cases        web/data/cases/*.json (kind != "miss" only)
  windows      public.marketing_windows via PostgREST — THE DB IS THE
               RULEBOOK; marketing_config.FALLBACK_WINDOWS only in dry-run
  demotions    public.marketing_demotions view (derived, no table)
  narrative    marketing_config.NARRATIVE (operator, monthly)

and writes rows to public.marketing_tasks. Nothing here posts, emails, or
auto-sends anything, ever: the queue is a list of things a human may choose
to do.

REFUSE, DON'T WARN. A candidate that cannot be placed inside the caps is
never written anywhere — it prints `REFUSED <dedupe_key> <reason>` and is
returned in the Plan for tests. Python refuses first; the marketing_tasks
trigger is the backstop, which is why rows go up ONE PER POST (a PostgREST
array is one statement — one refused row would roll back the whole batch).

IDEMPOTENT. dedupe_key = utm_campaign = asset filename stem (pipeline/utm.py),
deterministic from the triggering fact; inserts use ?on_conflict=dedupe_key
with `Prefer: resolution=ignore-duplicates,return=minimal`, so a re-run
inserts zero new rows and never clobbers a status the operator set —
ignore-duplicates, not merge, is the whole design.

DETERMINISTIC. No LLM calls, no wall-clock reads outside the --now default:
the same data files, DB reads, and --now instant produce the same rows and
the same pack-manifest bytes.

Missing config prints and exits 0, always: no Supabase env = full dry run —
the plan prints WOULD-INSERT lines, nothing is written, a fork without
secrets stays green.
"""

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import marketing_config as MC
from build_research import mtl_prose            # the "0.0 months" guard — one home
from growth_digest import (build_angles, diff_verdicts, load_current,
                           load_places, load_research, load_snapshot,
                           pitch_draft, pretty_month, prev_period,
                           strongest_record)
from utm import SLUG_RE, metro_slug, metro_tag, slug, token, utm_url
from velocity import load_cbsa                  # zip -> cbsa, cbsa -> title

ROOT = Path(__file__).resolve().parents[1]
CASES_DIR = ROOT / "pipeline" / "cases"   # moved out of web/ 2026-08-19
PACK_DIR = Path(__file__).parent / "marketing"  # tests point this at a tmpdir
SCHEMA_V23 = ROOT / "supabase" / "schema-v23.sql"

# Signal label vocabulary — mirrors admin.html's VEL_SIG_LABEL and the
# research page's dial names. Keep the pairs in step.
SIG_LABEL = {"spy": "price trend", "dom": "time to sell",
             "mos": "supply", "pd": "price cuts"}

# Deterministic slot ordering when several channels share an instant (the
# three Sunday anchors): the rotation the audience actually sees first.
CHANNEL_ORDER = ("ig", "x", "fb", "nextdoor_naomi")

# corroborates value -> the word the receipt copy uses for our flag.
FLAG_WORD = {"first_watch": "WATCH", "first_act": "ACT",
             "gathering_entry": "gathering-list"}


# ————— ET clock arithmetic —————
# scheduled_for is timestamptz and CI runs UTC; every window is an ET wall
# time. zoneinfo (stdlib) first; on a machine with no tz database the
# fallback is the post-2007 US DST rule — second Sunday of March to first
# Sunday of November = UTC-4, else UTC-5 — which is only wrong inside the
# 02:00 transition hour itself, and no configured slot can occupy it.
try:
    from zoneinfo import ZoneInfo
    _ET = ZoneInfo("America/New_York")
except Exception:                                # pragma: no cover
    _ET = None


def _dst(d):
    """True when US Eastern daylight time is in effect on date d."""
    def nth_sunday(month, n):
        first = date(d.year, month, 1)
        first += timedelta(days=(6 - first.weekday()) % 7)
        return first + timedelta(days=7 * (n - 1))
    return nth_sunday(3, 2) <= d < nth_sunday(11, 1)


def et_to_utc(d, hhmm):
    """Naive America/New_York wall time -> aware UTC datetime."""
    h, m = int(hhmm[:2]), int(hhmm[3:5])
    naive = datetime(d.year, d.month, d.day, h, m)
    if _ET is not None:
        return naive.replace(tzinfo=_ET).astimezone(timezone.utc)
    return (naive + timedelta(hours=4 if _dst(d) else 5)).replace(tzinfo=timezone.utc)


def et_date(dt):
    """UTC instant -> ET calendar date (same zoneinfo/arithmetic pair)."""
    if _ET is not None:
        return dt.astimezone(_ET).date()
    d = (dt - timedelta(hours=5)).date()
    return (dt - timedelta(hours=4)).date() if _dst(d) else d


def week_start(d_et):
    """The marketing week starts SUNDAY in ET — the Sunday 19:30 anchor is
    the week's first slot, not the last of the previous one. Mirrors
    public.marketing_week_start in schema-v23.sql; change one, change both."""
    return d_et - timedelta(days=(d_et.weekday() + 1) % 7)


def _fmt_et(dt):
    """'Sun Aug 9, 9:00 AM ET' — no leading-zero day/hour, no %-d (BSD/GNU
    strftime disagree on it)."""
    local = dt.astimezone(_ET) if _ET is not None else \
        dt.astimezone(timezone(timedelta(hours=-4 if _dst(et_date(dt)) else -5)))
    h = local.hour % 12 or 12
    ampm = "AM" if local.hour < 12 else "PM"
    return (f"{local.strftime('%a %b')} {local.day}, {h}:{local.minute:02d} "
            f"{ampm} ET")


def _mon_day(dt):
    """'Aug 9' without a leading zero."""
    return f"{dt.strftime('%b')} {dt.day}"


def parse_ts(s):
    """ISO timestamp (Z or offset) -> aware UTC datetime."""
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_z(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ordinal(n):
    if 10 <= n % 100 <= 20:
        suf = "th"
    else:
        suf = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suf}"


# ————— Supabase I/O (urllib only, the growth_digest._sb pattern) —————

def sb_env():
    """(url, key) from the PIPELINE env names. Edge functions use
    SUPABASE_SERVICE_ROLE_KEY; that name is never read here."""
    return (os.environ.get("SUPABASE_URL", "").rstrip("/"),
            os.environ.get("SUPABASE_SERVICE_KEY", ""))


def _http(req):
    """One seam for the tests to monkeypatch. Returns (status, body_text)."""
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "replace")


def sb_get(url, key, path, params):
    """GET against PostgREST. (rows, error_string) — a failure is a labelled
    gap for the caller to print, never a raise."""
    q = urllib.parse.urlencode(params, safe="().,*:-")
    req = urllib.request.Request(
        f"{url}/rest/v1/{path}?{q}",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Accept": "application/json"})
    try:
        _, body = _http(req)
        return json.loads(body), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def post_task_row(url, key, row):
    """ONE row per POST — the v23 trigger raises per row, and a PostgREST
    array is a single statement, so batching would let one refused row roll
    back every task beside it. (ok, error_string)."""
    req = urllib.request.Request(
        f"{url}/rest/v1/marketing_tasks?on_conflict=dedupe_key",
        data=json.dumps([row]).encode(),
        method="POST",
        headers={"apikey": key, "Authorization": f"Bearer {key}",
                 "Content-Type": "application/json",
                 "Prefer": "resolution=ignore-duplicates,return=minimal"})
    try:
        _http(req)
        return True, None
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("message", "")
        except Exception:
            detail = ""
        return False, f"HTTP {exc.code} {detail}".strip()
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


# ————— data loaders —————

def load_windows(url, key, dry):
    """The posting calendar. The DATABASE is the single rulebook; the
    FALLBACK_WINDOWS mirror serves dry runs and secretless forks, and a
    fetch failure degrades to it with a labelled line (the trigger still
    enforces the real calendar on insert)."""
    if dry or not (url and key):
        return [dict(w) for w in MC.FALLBACK_WINDOWS], "fallback"
    rows, err = sb_get(url, key, "marketing_windows",
                       {"select": "channel,dow,at_time,label,anchor"})
    if err or rows is None:
        print(f"windows unreadable — {err}; planning against FALLBACK_WINDOWS "
              f"(the DB trigger still enforces the real calendar)")
        return [dict(w) for w in MC.FALLBACK_WINDOWS], "fallback"
    for w in rows:
        w["at_time"] = str(w["at_time"])[:5]     # PostgREST time -> 'HH:MM'
    return rows, "db"


def load_receipts(url, key, getter=sb_get):
    """press_corroboration rows, or [] with a labelled gap printed."""
    rows, err = getter(url, key, "press_corroboration",
                       {"select": "id,url,outlet,headline,published_on,"
                                  "metro_cbsa,zip,corroborates,flag_date"})
    if err or rows is None:
        print(f"receipts unreadable — {err} (rule sits out)")
        return []
    return rows


def load_demotions(url, key, getter=sb_get):
    """The marketing_demotions VIEW — derived from the skip log, no second
    source of truth. [] with a labelled gap on failure (a metro is then
    simply not demoted this run; the disclosure returns next run)."""
    rows, err = getter(url, key, "marketing_demotions",
                       {"select": "metro_cbsa,metro_name,skips,last_skip_at,expires_at"})
    if err or rows is None:
        print(f"demotions unreadable — {err} (no demotions applied this run)")
        return []
    return rows


def load_existing(url, key, h_start, h_end):
    """Rows the plan must respect: anything scheduled inside the horizon
    ±METRO_COOLDOWN_DAYS that still holds a slot or a metro. Skipped rows
    release everything they held and are not fetched."""
    pad = timedelta(days=MC.METRO_COOLDOWN_DAYS)
    rows, err = sb_get(url, key, "marketing_tasks", [
        ("select", "dedupe_key,channel,scheduled_for,metro_cbsa,status"),
        ("scheduled_for", f"gte.{iso_z(h_start - pad)}"),
        ("scheduled_for", f"lte.{iso_z(h_end + pad)}"),
        ("status", "in.(suggested,scheduled,posted)")])
    if err or rows is None:
        print(f"existing tasks unreadable — {err}; planning against an empty "
              f"queue (on_conflict still prevents duplicates)")
        return []
    return rows


def existing_keys(url, key, keys):
    """Which candidate dedupe_keys already have rows (any status, any age —
    a receipt task posted last month must not be re-planned this month)."""
    out = set()
    for i in range(0, len(keys), 100):
        chunk = keys[i:i + 100]
        rows, err = sb_get(url, key, "marketing_tasks", {
            "select": "dedupe_key",
            "dedupe_key": "in.(" + ",".join(chunk) + ")"})
        if err or rows is None:
            print(f"dedupe pre-check unreadable — {err}; relying on "
                  f"on_conflict=dedupe_key alone")
            return out
        out |= {r["dedupe_key"] for r in rows}
    return out


def load_history():
    """pipeline/research/history.json — the per-metro monthly verdict counts.
    Complete back to 2012, which is what lets the taxonomy rules ask about six
    months of a metro without holes."""
    p = ROOT / "pipeline" / "research" / "history.json"
    try:
        return json.loads(p.read_text())
    except Exception as exc:
        print(f"history unavailable ({exc}) — divergence/steady/spotlight sit out")
        return None


def load_streaks():
    p = ROOT / "pipeline" / "research" / "streaks.json"
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def load_velocity_current(data_dir):
    p = Path(data_dir) / "velocity-aggregates.json"
    return json.loads(p.read_text()) if p.exists() else None


def load_velocity_prev(period):
    p = Path(__file__).parent / "velocity" / f"velocity-{prev_period(period)}.json"
    return json.loads(p.read_text()) if p.exists() else None


def load_case_index():
    p = CASES_DIR / "index.json"
    if not p.exists():
        return []
    return json.loads(p.read_text()).get("published") or []


def case_cbsa(cid):
    p = CASES_DIR / f"{cid}.json"
    if not p.exists():
        return None
    return json.loads(p.read_text()).get("cbsa")


# ————— copy guards —————

def guard(cand):
    """The generator-side mirror of the DB's refusals, plus the two lists
    the DB does not know. Returns the tripped words (empty = compliant).

    BANNED (affiliation grammar) is checked on every field, byte-matching
    the marketing_tasks_no_affiliation_claim constraint. NAOMI_NEVER is
    checked on every field — a real, unaffiliated person's name never rides
    generated copy. HYPE is checked on the CAPTION only: captions are what
    gets pasted into public channels, and the contrarian headline must be
    allowed to QUOTE a hype-laden narrative in order to refute it. The
    zero-months regex enforces the mtl_prose discipline mechanically on
    every field — our own templates route through mtl_prose, but reused
    sentences (the angle bank) must clear the same bar."""
    everything = " ".join(filter(None, [cand.get("why_headline"),
                                        cand.get("why_detail"),
                                        cand.get("caption"),
                                        cand.get("hashtags")])).lower()
    capt = (cand.get("caption") or "").lower()
    hits = [w for w in MC.BANNED if w in everything]
    hits += [w for w in MC.NAOMI_NEVER if w in everything]
    hits += [w for w in MC.HYPE if w in capt]
    if re.search(r"\b0(\.0)? months?\b", everything):
        hits.append("zero-months")
    return hits


# ————— the six triage rules —————
# Every builder returns plain dicts:
#   key/type/tier/why_headline/why_detail/caption (with a literal {utm_url}
#   placeholder — the link needs the channel, which the scheduler assigns) /
#   metro_cbsa/metro_name/zip/asset_path/source_id, plus optional
#   channel (pin), week (pin), fixed_time / fixed_source (cap-exempt rows).

def _record_is_alarming(rec, sup):
    """Does this month's superlative point the WRONG way for a seller?

    True only when the index ROSE into the record (more markets showing warning
    signs). A record low, a "lowest since", or a falling run is good news and
    must not be dressed as an alarm. Reads the same fields detect_records()
    emits — no second source of truth about direction.
    """
    s = (sup or "").lower()
    if "lowest" in s:
        return False
    if "highest" in s:
        return True
    # A run: the direction field is authoritative. Otherwise fall back to the
    # month-over-month delta, and default to the calmer framing when unknown.
    if rec.get("run_direction"):
        return rec["run_direction"] == "up"
    return (rec.get("delta") or 0) > 0


def cand_record(rep):
    """Tier 1: the WSI printed a superlative this month. Trigger is
    strongest_record() — the same function the digest pitch leads with, so a
    fact strong enough to pitch is exactly a fact strong enough to post."""
    if not rep:
        return None
    rec, sup = rep["records"], strongest_record(rep)
    if not sup:
        print("records: no record-shaped fact this month — rule sits out")
        return None
    period = rep["month"]
    lines = [f"- Warning signs in {rec['wsi']:.1f}% of ~25,000 scored U.S. ZIP markets"
             + (f", {'up' if rec['delta'] > 0 else 'down'} from {rec['prev_wsi']:.1f}% "
                f"({rec['delta']:+.1f} pts)." if rec.get("delta") else ".")]
    if rec.get("run_length", 0) >= 2:
        lines.append(f"- {ordinal(rec['run_length'])} consecutive monthly "
                     f"{'rise' if rec['run_direction'] == 'up' else 'decline'}.")
    lines.append(f"- Basis: continuous series since {pretty_month(rec['basis_since'])} "
                 f"({rec['basis_months']} months) — superlatives never cross the "
                 f"source seam.")
    sentence = lambda s: (s[:1].upper() + s[1:]) if s else s
    # Small ordinals as WORDS in prose: "the third month in a row" reads, and
    # "3rd" spends one of the three numbers a caption is allowed on a figure
    # nobody needs to hold precisely.
    _ordinal_word = lambda n: {2: "second", 3: "third", 4: "fourth", 5: "fifth",
                               6: "sixth", 7: "seventh", 8: "eighth",
                               9: "ninth"}.get(n, ordinal(n))
    direction = "More" if _record_is_alarming(rec, sup) else "Fewer"
    moved = ((f", down from {rec['prev_wsi']:.1f}%" if (rec.get('delta') or 0) < 0
              else f", up from {rec['prev_wsi']:.1f}%") if rec.get('prev_wsi') else "")
    _rec_long, _rec_short = compose(
        hook=(f"{direction} neighborhoods across the country are showing housing "
              f"warning signs than at any point since {pretty_month(rec['basis_since']) if sup.startswith('a record') else sup.split('since ')[-1].rstrip('.')}."),
        contrast=(f"We check about 25,000 ZIP codes every month against the same "
                  f"danger lines — the levels where sellers have historically "
                  f"started losing leverage. Right now {rec['wsi']:.1f}% are "
                  f"showing at least one{moved}."),
        evidence=(f"That is the {_ordinal_word(rec['run_length'])} month in a row the "
                  f"share has fallen." if (rec.get("run_length") or 0) >= 2
                  and rec.get("run_direction") == "down" else
                  f"{sentence(sup)}."),
        period=period,
        short_hook=(f"{direction} neighborhoods are showing housing warning signs "
                    f"than at any point in recent months: {rec['wsi']:.1f}% of the "
                    f"25,000 ZIP codes we track{moved}."),
        short_contrast=f"{sentence(sup)}.")
    return {
        "key": token("record", period=period), "type": "post",
        "post_type": "national_pulse", "tier": 1,
        "why_headline": f"WSI hit {rec['wsi']:.1f}% — {sup}. Records are "
                        f"headlines by construction.",
        "why_detail": "\n".join(lines),
        # THE CAPTION FOLLOWS THE DATA, NOT THE MOOD. strongest_record() returns
        # whichever superlative is strongest, and roughly half of them are GOOD
        # news — a record low, or the lowest share since some month. An
        # unconditional "warning signs are flashing" opener published against a
        # falling index would contradict this card's own why_detail two lines
        # down ("3rd consecutive monthly decline") and would be the exact kind
        # of claim docs/GROWTH-OPS.md's reply bank tells us not to make. guard()
        # cannot catch this: no banned word is involved, only a framing that
        # does not track the direction. So the opener is chosen by direction.
        # Written for a homeowner, not an economist: no index name, no "share",
        # no "basis points". The number stays exact; the sentence around it
        # says what the number means for a person who owns one house.
        "caption": _rec_long, "caption_short": _rec_short,
        "asset_path": f"/research/{period}/social/1-wsi.png",
        "render": {"wsi": rec["wsi"], "prev_wsi": rec.get("prev_wsi"),
                   "delta": rec.get("delta"), "superlative": sup},
    }


def _wsi_series(n=12):
    """The last n months of the national Warning-Sign Index, as [(month, wsi)].

    Read through research.national_series(segment="continuous") so the line can
    never cross the 2020-06 source seam — the same discipline that stops a
    superlative reaching across it. Returns [] if the history is missing, and
    the card falls back to a number-only layout rather than drawing a lie.
    """
    try:
        import research as _R
        h = json.loads((ROOT / "pipeline" / "research" / "history.json").read_text())
        return [[m, round(w, 1)] for m, w in _R.national_series(h, segment="continuous")[-n:]]
    except Exception as exc:
        print(f"contrarian: no WSI history for the chart ({exc}) — card will be text-only")
        return []


def cand_contrarian(rep, period):
    """Tier 2: the data contradicts the month's dominant narrative.
    NARRATIVE is operator-set monthly in marketing_config.py; unset, stale,
    or gap-less all degrade to a printed line, never a crash and never a
    stale claim. The caption never quotes the narrative text — operator
    prose does not ride into public copy, only the counter-numbers do."""
    n = getattr(MC, "NARRATIVE", None) or {}
    text = (n.get("text") or "").strip()
    if n.get("period") != period or not text:
        print(f"contrarian: NARRATIVE unset/stale for {period} — rule skipped "
              f"(set it in pipeline/marketing_config.py)")
        return None
    rec = rep["records"] if rep else {}
    wsi, delta = rec.get("wsi"), rec.get("delta")
    if wsi is None:
        print("contrarian: no research file this month — rule skipped")
        return None
    hold = 100.0 - wsi
    stance = n.get("stance", "bearish")
    if stance == "bearish" and (wsi < MC.CONTRARIAN_CALM_WSI or (delta or 0) < 0):
        # LEAD WITH WHATEVER ACTUALLY MAKES THE GAP. Two different facts can
        # open this branch and they are not equally honest to lead with.
        # When the LEVEL is calm (wsi below the calm line) the HOLD share is
        # the counter. When the level is high and only the TREND is falling —
        # 62.2% warning, down 2.4 pts — leading with "37.8% still rate HOLD or
        # better" picks the weaker half of our own data and reads as spin,
        # which is the failure the 20841 angle was pulled for. The trend is
        # the honest counter there, and it is also the stronger one.
        run = rec.get("run_length") or 0
        if wsi < MC.CONTRARIAN_CALM_WSI:
            # The LEVEL is the gap: most markets are fine, whatever the
            # coverage says. That is the strongest true counter, so it leads,
            # and a falling trend rides along as support.
            counter = f"{hold:.1f}% of the ZIP codes we track still look healthy"
            if (delta or 0) < 0:
                counter += ", and fewer are showing warning signs than last month"
        else:
            # The level is NOT calm — only the trend makes this a gap. Leading
            # with the HOLD share here would pick the weaker half of our own
            # data (37.8% while 62.2% show warning signs), which is the spin
            # the 20841 angle was pulled for.
            counter = "fewer neighborhoods are showing warning signs than last month"
            if run >= 2 and rec.get("run_direction") == "down":
                counter += f" — the {ordinal(run)} month in a row they have dropped"
            if rec.get("lowest_since"):
                counter += (", the fewest we have ever recorded"
                            if rec["lowest_since"] == "record"
                            else f", and the fewest since {pretty_month(rec['lowest_since'])}")
    elif stance == "bullish" and wsi > MC.CONTRARIAN_HOT_WSI and (delta or 0) > 0:
        counter = (f"warning signs are flashing in {wsi:.1f}% of scored ZIP "
                   f"markets, up {delta:+.1f} pts this month")
    else:
        print(f"contrarian: narrative set but no gap (stance {stance}, "
              f"WSI {wsi:.1f}%, delta {delta}) — rule skipped")
        return None
    _con_long, _con_short = compose(
        hook="The headlines are telling one story. The data tells a quieter one.",
        contrast=(f"Across the roughly 25,000 ZIP codes we track against fixed "
                  f"danger lines — the levels where sellers have historically "
                  f"started losing leverage — {counter}."),
        evidence="We publish the same measurement every month, moved or not.",
        period=period,
        short_hook="The headlines are telling one story. The data tells a quieter one:",
        short_contrast=f"across the 25,000 ZIP codes we track, {counter}.")
    return {
        "key": token("contrarian", period=period), "type": "post",
        "post_type": "contrarian", "tier": 2,
        "why_headline": f'The narrative says "{text}" — the data says {counter}.',
        "why_detail": "\n".join([
            f"- Verdict mix for {pretty_month(period)}: {wsi:.1f}% warning, "
            f"{hold:.1f}% HOLD-or-better, across ~25,000 scored ZIPs against "
            f"fixed danger lines.",
            f"- Narrative set by the operator for {period} in "
            f"pipeline/marketing_config.py; this card exists only because the "
            f"verdict mix points the other way."]),
        "caption": _con_long, "caption_short": _con_short,
        "asset_path": f"/assets/mkt/{period}/{token('contrarian', period=period)}.png",
        "render": {"wsi": wsi, "delta": delta, "counter": counter,
                   "card": "contrarian",
                   "run_length": rec.get("run_length"),
                   "run_direction": rec.get("run_direction"),
                   "series": _wsi_series(12),
                   "period_pretty": pretty_month(period)},
    }


def cand_receipts(rows, today, cbsa_names, places, period):
    """Tier 2, type receipt_quote — one task per FRESH receipt where we were
    actually ahead. lead_days <= 0 is skipped (a receipt where we were not
    ahead is not a brag), stale (> RECEIPT_LOOKBACK_DAYS) is skipped. The
    token carries the row uuid, so a receipt mints one task in its lifetime
    no matter how many refreshes see it."""
    out = []
    for r in rows:
        try:
            pub = date.fromisoformat(str(r["published_on"]))
            flag = date.fromisoformat(str(r["flag_date"]))
        except (KeyError, ValueError):
            continue
        lead = (pub - flag).days
        if (today - pub).days > MC.RECEIPT_LOOKBACK_DAYS or lead <= 0:
            continue
        geo = cbsa_names.get(r.get("metro_cbsa") or "")
        if not geo and r.get("zip") and r["zip"] in places:
            c = places[r["zip"]]
            geo = f"{c[0]}, {c[1]}"
        geo = geo or f"CBSA {r.get('metro_cbsa') or '?'}"
        word = FLAG_WORD.get(r.get("corroborates"), "WATCH")
        hl = (r.get("headline") or "").strip().rstrip(".")
        out.append({
            "key": token("receipt", uuid=r["id"]), "type": "receipt_quote",
            "tier": 2, "source_id": r["id"],
            "metro_cbsa": r.get("metro_cbsa"), "metro_name": geo,
            "zip": r.get("zip"),
            "why_headline": f"Receipt: {r['outlet']} reported what our index "
                            f"flagged in {geo} {lead} days earlier.",
            "why_detail": "\n".join([
                f"- Our first {word} flag: {_mon_day_full(flag)}. Their piece: "
                f'"{hl}" ({_mon_day_full(pub)}).',
                f"- Receipt logged in press_corroboration with the source URL "
                f"— the claim is checkable."]),
            "caption": (f"On {_mon_day_d(flag)} our index flagged {geo}. On "
                        f'{_mon_day_d(pub)}, {r["outlet"]} reported it: "{hl}." '
                        f"A {lead}-day head start is the kind sellers can "
                        f"actually use. Check your ZIP free: {{utm_url}}"),
            "asset_path": f"/assets/mkt/{period}/{token('receipt', uuid=r['id'])}.png",
            "render": {"outlet": r["outlet"], "headline": hl, "geo": geo,
                       "flag_word": word, "flag_date": str(r["flag_date"]),
                       "published_on": str(r["published_on"]),
                       "lead_days": lead},
        })
    return out


def _mon_day_full(d):
    return f"{d.strftime('%B')} {d.day}, {d.year}"


def _mon_day_d(d):
    return f"{d.strftime('%b')} {d.day}"


def short_metro(name):
    """"Grand Rapids-Wyoming-Kentwood, MI" -> "Grand Rapids, MI".

    Census CBSA titles name every principal city and every state they touch.
    Nobody says that out loud, and in a caption it reads like a spreadsheet
    got pasted in. The first city and the first state is what a homeowner
    calls the place they live. Kept OUT of why_headline and the admin card,
    which stay precise — this is for public copy only.
    """
    if not name or "," not in name:
        return name or ""
    city, states = name.rsplit(",", 1)
    return f"{city.split('-')[0].strip()}, {states.strip().split('-')[0]}"


def cand_flips(vel, vel_prev, period):
    """Tier 3: a top-30 metro's deteriorating share crossed BIG_FLIP_SHARE
    upward. Current month = the gathering rows in web/data/velocity-aggregates
    .json; the crossing is asserted against the committed velocity-{prev}
    .json metros — no prior file, no crossings, printed. Every median_mtl is
    phrased through build_research.mtl_prose so a 0.0 median renders
    'already at its danger line', never '0.0 months' — these strings end up
    in press emails."""
    if not vel or not (vel.get("gathering") or []):
        print("metro flips: no velocity aggregates — rule sits out")
        return []
    if not vel_prev:
        print("metro flips: no prior velocity file — cannot assert a "
              "crossing; rule sits out")
        return []
    rows = sorted(vel["gathering"], key=lambda g: (-g["zips"], g["cbsa"]))
    top = rows[:MC.BIG_METRO_COUNT]
    prev_metros = vel_prev.get("metros") or {}
    out = []
    for rank, g in enumerate(top, 1):
        prev = prev_metros.get(g["cbsa"]) or {}
        # SURGE is the trigger — velocity.py sets it when a metro enters the
        # gathering top-10 for the first time in six months, which is the
        # thing that is actually new. The two floors below only stop a surge
        # into a mild or tiny metro from being announced as a story.
        if not g.get("surge"):
            continue
        if (g.get("share_det") or 0) < MC.BIG_STORY_MIN_SHARE:
            continue
        if (g.get("zips") or 0) < MC.BIG_STORY_MIN_ZIPS:
            continue
        tok = token("flip", period=period, cbsa=g["cbsa"])
        lines = [f"- A top-{MC.BIG_METRO_COUNT} metro by coverage (#{rank} of "
                 f"{len(rows)} on the gathering list, {g['zips']} scored ZIPs) "
                 f"— big enough that this is a story, not noise.",
                 f"- First time in the gathering top-10 in six months — that "
                 f"is what makes it news this month, not the level alone."]
        # Only when it actually moved: the prior-month cache can hold the same
        # figure, and "(+0.0 pts)" in a why is a line that costs attention and
        # pays nothing.
        if prev.get("share_det") is not None and abs(g["share_det"] - prev["share_det"]) >= 0.05:
            lines.append(f"- Was {prev['share_det']:.1f}% deteriorating last "
                         f"month ({g['share_det'] - prev['share_det']:+.1f} pts).")
        sig = g.get("sig") or {}
        if sig:
            dk = max(sig, key=lambda k: (sig[k].get("near") or 0, k))
            d = sig[dk]
            lines.append(f"- The dial that moved: {SIG_LABEL.get(dk, dk)} — near "
                         f"its danger line in {d['near']} of {g['zips']} ZIPs, "
                         f"median {mtl_prose(d.get('median_mtl'))} at the "
                         f"current 3-month pace.")
        name = short_metro(g["name"])
        det, hold = round(g["share_det"]), round(g["hold_share"])
        hook = (f"{det}% of the ZIP codes we track in {name} are now moving "
                f"toward a danger line — the level where local price trends "
                f"have historically turned against sellers.")
        # hold_share counts green AND strong — HOLD or better, not HOLD. Calling
        # it "rate HOLD" both overstates the calm and contradicts the metro page
        # this post links to, which says "N of M rate HOLD or better today".
        # STRONG is its own verdict; the site was fixed elsewhere for exactly
        # this conflation.
        contrast = (f"On the surface the market looks steady: {hold}% of "
                    f"neighborhoods still rate HOLD or better today. Underneath, most of "
                    f"those same neighborhoods are drifting the same way, and "
                    f"at the pace of the last three months the typical one is "
                    f"{mtl_prose(g.get('median_mtl'))}.")
        # WAS: "This is {name}'s first month among the fastest-shifting markets
        # we track." Not what the flag means, and not true. velocity.py sets
        # surge when a metro enters the top 10 having been absent from it in the
        # previous six files — a RANK move over a six-file window. York-Hanover
        # was on the gathering list in eight earlier months, including the month
        # immediately before, at an identical 83.3%. The post announced an
        # arrival at a place the metro had occupied for a year.
        #
        # What IS true is its standing this month, phrased so a tie cannot make
        # it false: two metros share 83.3%, so "third-highest" would be wrong
        # and "second" would be arguable. Counting how many are strictly above
        # is exactly right either way.
        #
        # And when the metro's own share has not moved, that is the story: it
        # climbed the list because other markets improved, not because it got
        # worse. Saying so is the difference between a fact and a narrative.
        above = sum(1 for r in (vel.get("gathering") or [])
                    if (r.get("share_det") or 0) > g["share_det"])
        # Spelled out, not because it reads better but because the caption has a
        # budget of three FIGURES and this sentence is not carrying one of them.
        # The reader's three are the share, the hold share and last month's.
        _w = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
              7: "seven", 8: "eight", 9: "nine", 10: "ten"}
        evidence = ("No metro we track has a higher share this month."
                    if above == 0 else
                    f"Only {_w.get(above, above)} metro"
                    f"{'' if above == 1 else 's'} we track "
                    f"{'has' if above == 1 else 'have'} a higher share this month.")
        prev_det = prev.get("share_det")
        if prev_det is not None:
            if abs(g["share_det"] - prev_det) < 0.5:
                evidence += (" Its own share has not moved since last month — it sits "
                             "this high because other markets improved, not because "
                             "this one got worse.")
            else:
                evidence += f" Last month it was {round(prev_det)}%."
        short_hook = (f"{det}% of ZIP codes we track in {name} are moving toward "
                      f"a danger line — where sellers start losing leverage.")
        short_contrast = f"{hold}% still rate HOLD or better: largely the same neighborhoods."
        cap_long, cap_short = compose(hook, contrast, evidence, period,
                                      short_hook, short_contrast)
        out.append({
            "key": tok, "type": "post", "post_type": "metro_mover", "tier": 3,
            "caption": cap_long, "caption_short": cap_short,
            "metro_cbsa": g["cbsa"], "metro_name": g["name"],
            "why_headline": f"{g['name']} is high on our watch list — "
                            f"{g['share_det']:.0f}% of its {g['zips']} scored "
                            f"ZIPs are deteriorating or drifting.",
            "why_detail": "\n".join(lines),
            # The post_metro paste pattern — zero numeral literals in the
            # template itself; every figure arrives from the data.
            # THE TWO SHARES OVERLAP, AND THE CAPTION HAS TO SAY SO. hold_share
            # is the share of ZIPs whose VERDICT is HOLD today; share_det is the
            # share whose velocity state is deteriorating — approaching a line
            # they have not crossed. A ZIP is routinely in both, which is the
            # entire point of the velocity layer. Printed as "63% still rate
            # HOLD — but 76% are deteriorating" they read as disjoint groups
            # summing past 100%, and the post looks like it cannot add up. The
            # overlap is the story, so it is stated rather than left to trip
            # the reader.
"asset_path": f"/assets/mkt/{period}/{tok}.png",
            "render": {"name": g["name"], "short_name": short_metro(g["name"]),
                       "zips": g["zips"],
                       "share_det": g["share_det"],
                       "prev_share_det": prev.get("share_det"),
                       "hold_share": g["hold_share"],
                       "median_mtl": g.get("median_mtl"),
                       "sig": sig, "period_pretty": pretty_month(period)},
        })
    return out


# ————— the caption skeleton —————
# Every public caption is assembled here rather than written out by each rule,
# so the SHAPE is structural: hook, contrast, evidence, one CTA, attribution,
# two tags. A rule supplies three plain-language parts and cannot produce an
# off-skeleton post even by accident.
#
# TWO LENGTHS FROM THE SAME FACTS. X is not premium (MC.X_PREMIUM), so a post
# there is 280 characters including the link and the tags — and the long
# caption does not survive truncation: cutting it mid-contrast destroys the
# one move the brand has. So a rule also supplies a tight version of the hook
# and contrast, and the short caption is BUILT, never cut.
CTA = "See where your ZIP stands (free): {short_url}"


def compose(hook, contrast, evidence, period, short_hook=None, short_contrast=None):
    """(long, short). Placeholders {short_url} and {tags} resolve at row build,
    where the channel is finally known."""
    pm = pretty_month(period)
    long_parts = [hook, contrast, evidence, CTA,
                  f"ShouldISellYet Research · data through {pm}\n{{tags}}"]
    long_caption = "\n\n".join(x for x in long_parts if x)

    # The short one drops the why-now line first (it is the least load-bearing
    # of the three) and runs hook and contrast together as one paragraph.
    lead = " ".join(x for x in (short_hook or hook, short_contrast or contrast) if x)
    short_caption = (f"{lead}\n\n{{short_url}}\n"
                     f"ShouldISellYet · {pm}\n{{tags}}")
    return long_caption, short_caption


# ————— the linter —————
# NOT a regenerate loop: there is no LLM here and the templates are pure
# functions, so re-running one returns the identical string forever. What a
# linter can do is (a) fail the build when a TEMPLATE could emit something
# banned, via the tests, and (b) attach a reason to a row so the operator sees
# it on the card before posting. Both, rather than a retry that cannot work.
MONTHS_RE = "|".join(["January", "February", "March", "April", "May", "June",
                      "July", "August", "September", "October", "November",
                      "December"])
# Thousands separators keep their number whole ("25,000" is one figure a reader
# holds, not two), and a year following a month name is a date, not a stat.
NUMERAL_RE = re.compile(r"(?<![\d,.])\d[\d,]*(?:\.\d+)?%?")
DATE_YEAR_RE = re.compile(rf"(?:{MONTHS_RE})\s+\d{{4}}")


def lint_caption(text, channel, hashtags, short_url="", target=None,
                 reply=False):
    """Everything wrong with this caption, as plain sentences. [] means clean.

    short_url MUST be the real link. Linting against a stand-in shorter than
    the live one is how a 299-character post passes a 280-character check.

    reply=True lints a thread REPLY, which is held to a different contract for
    two rules and the same one for every other. A reply carries no link and no
    attribution line: the lead two inches above it already said who is speaking
    and where to click, and repeating either five times is how a thread reads as
    five adverts instead of one argument. Everything else — length, hashtags,
    the number budget, shouting, banned constructions — applies unchanged,
    because a reply is published copy like any other.
    """
    out = []
    if not text:
        return ["caption is empty"]
    body = (text.replace("{short_url}", short_url or "shouldisellyet.com/go/placeholder/")
                .replace("{tags}", hashtags or ""))
    n = len(body)
    if channel == "x" and not MC.X_PREMIUM:
        if n > MC.CAPTION_MAX_SHORT:
            out.append(f"{n} characters — X allows {MC.CAPTION_MAX_SHORT} without premium")
    else:
        lo, hi = MC.CAPTION_RANGE_LONG
        if n > hi:
            out.append(f"{n} characters — over the {hi} target")
    links = body.count("shouldisellyet.com")
    if reply:
        if links:
            out.append(f"{links} links in a reply — the link belongs on the lead")
    elif links != 1:
        out.append(f"{links} links — a post gets exactly one")
    # A homepage destination is a wasted click, so it is a lint failure and not
    # a style note. Checked on the RESOLVED target, because the visible link is
    # a /go/ redirect and reveals nothing about where it lands.
    if target is not None and target in ("/", "", None) and not reply:
        out.append("link lands on the homepage — a post must open the page it is about")
    tags = body.count("#")
    if tags > MC.MAX_HASHTAGS:
        out.append(f"{tags} hashtags — the cap is {MC.MAX_HASHTAGS}")
    # Numbers, excluding the ones inside the link and the attribution date.
    countable = DATE_YEAR_RE.sub("", body.split("shouldisellyet.com")[0])
    # A bare five-digit integer in this domain is a ZIP code — an identifier and
    # the subject of the sentence, not a competing figure. A price carries a $
    # or a separator and still counts.
    countable = re.sub(r"(?<![\d$,.])\d{5}(?![\d,.%])", "", countable)
    nums = NUMERAL_RE.findall(countable)
    if len(nums) > MC.MAX_NUMBERS_LONG:
        out.append(f"{len(nums)} numbers ({', '.join(nums[:5])}…) — at most "
                   f"{MC.MAX_NUMBERS_LONG}, one of them the hero")
    if "ShouldISellYet" not in body and not reply:
        out.append("attribution line missing")
    low = body.lower()
    # ACRONYMS NEVER LEAD. An index name in the hook asks a stranger to care
    # about our vocabulary before they have been given a reason to care about
    # the number. The plain-language meaning leads; the acronym may appear once,
    # later, in parentheses. All-caps anywhere is checked by the same pass —
    # shouting is not tone.
    hook = re.split(r"(?<=[.!?])\s", body.strip())[0] if body.strip() else ""
    shouted = [w for w in re.findall(r"\b[A-Z][A-Z.]{1,}\b", hook)
               if w.upper().replace(".", "") not in MC.CAPS_ALLOWED]
    if shouted:
        out.append(f"acronym or all-caps in the hook ({', '.join(sorted(set(shouted)))}) "
                   f"— lead with what it means")
    body_caps = [w for w in re.findall(r"\b[A-Z][A-Z.]{2,}\b", body)
                 if w.upper().replace(".", "") not in MC.CAPS_ALLOWED]
    if body_caps:
        out.append(f"all-caps word(s) ({', '.join(sorted(set(body_caps)))})")

    # "76% of 76 scored ZIPs" reads as a typo. Restate as a count OR a share.
    for a, b in re.findall(r"(\d+)%[^.]{0,26}?\bof\b[^.]{0,14}?(\d+)\b", body):
        if abs(int(a) - int(b)) <= MC.NEAR_EQUAL_TOLERANCE:
            out.append(f"{a}% sits beside a near-equal denominator ({b}) — "
                       f"state a count or a share, not both")
            break

    if "danger line" in low:
        after = low.split("danger line", 1)[1][:90]
        if not any(g in after for g in MC.DANGER_LINE_GLOSSES):
            out.append('"danger line" used without defining it in plain words')
    return out


def publishable(z, entries):
    """Is this ZIP's angle safe to PUBLISH? Returns None if fine, or the
    reason to drop it.

    The angle bank was written for the operator digest, where a strange number
    is informative and a human reads it in context. The queue is different: its
    sentences get pasted into public feeds, so a fact that is arithmetically
    true but publicly indefensible has to be stopped here rather than trusted
    to the operator's eye at 7:30 on a Sunday.

    Two ways an angle goes wrong, both seen in the first filled queue:

    MIX SHIFT. 22044 printed "prices are up 193.0% versus a year ago" off 36
    sales. Its median went 290k → 855k because DIFFERENT HOMES sold, not
    because anything appreciated 193%. MIN_SOLD_FOR_ANGLE (15) guards against
    one sale swinging a percentage; it cannot guard against the composition of
    the basket changing, and no sales floor can. A y/y move past
    MAX_PLAUSIBLE_SPY is treated as a data artifact and dropped — a real
    housing market does not do that, so a number that says it did is telling
    us about the basket, not the market.

    OFF-MESSAGE. 20841 printed "taking 43 days LESS to sell than a year ago"
    while that same ZIP's verdict is price_falling and its prices are down
    4.1%. Every word of it is true and it is still the wrong half of the
    picture: this brand is a smoke detector, and posting the cheerful half of
    a mixed ZIP is the cherry-pick our own reply bank tells us not to make.
    An improving-speed angle is dropped when the ZIP's own verdict disagrees
    with it.
    """
    e = entries.get(z) or {}
    m = e.get("m") or {}
    spy = m.get("spy")
    if spy is not None and abs(spy) > MC.MAX_PLAUSIBLE_SPY:
        return (f"y/y price move {spy * 100:+.0f}% is past the plausibility "
                f"band (±{MC.MAX_PLAUSIBLE_SPY * 100:.0f}%) — median mix shift, "
                f"not a market move")
    return None


def cand_geo(angles, period, zip_cbsa, cbsa_names, entries=None):
    """Tier 4 (+demotion): the standing-calendar filler. One task per
    build_angles() fact — the digest's own five sentences, reused verbatim
    as headlines because they were written to be pasted. The ZIP is read
    back out of the sentence (every angle leads with label(z), which starts
    with the ZIP); an angle without one is a malformed fact and is skipped
    aloud rather than guessed at."""
    out = []
    for i, sentence in enumerate(angles, 1):
        m = re.search(r"\b(\d{5})\b", sentence)
        if not m:
            print(f"geo: angle {i} carries no ZIP — skipped: {sentence[:60]}…")
            continue
        z = m.group(1)
        drop = publishable(z, entries or {})
        if drop:
            print(f"geo: {z} angle not publishable — {drop}")
            continue
        # An improvement framing on a ZIP the site itself is warning about.
        e = (entries or {}).get(z) or {}
        speed_up = "less to sell" in sentence
        warning = (e.get("l") in ("yellow", "red")) or any(
            r[0] in ("price_falling", "supply_building", "cuts_widespread")
            for r in (e.get("r") or []))
        if speed_up and warning:
            print(f"geo: {z} angle is off-message (homes selling faster while "
                  f"the ZIP reads {e.get('l')}) — skipped")
            continue
        cbsa = zip_cbsa.get(z)
        _geo_long, _geo_short = compose(
            hook=sentence, contrast=None,
            evidence="One of five local facts we pull from this month's data.",
            period=period)
        out.append({
            "key": token("geo", period=period, zip=z), "type": "post",
            "post_type": "zip_spotlight", "tier": 4,
            "zip": z, "metro_cbsa": cbsa,
            "metro_name": cbsa_names.get(cbsa) if cbsa else None,
            "why_headline": sentence,
            "why_detail": "\n".join([
                f"- Angle bank pick {i} of {len(angles)} for "
                f"{pretty_month(period)} (DMV pool first, minimum 15 sales, one "
                f"ZIP per rule — same facts as the Growth Ops digest).",
                f"- Standing-calendar filler: any priority 0–3 card outranks it "
                f"this week."]),
            "caption": _geo_long, "caption_short": _geo_short,
            "render": {"zip": z, "sentence": sentence},
        })
    return out


def label_zip(z, places):
    """"20874 (Boyds, MD)" — the same shape the angle bank uses."""
    c = places.get(z)
    return f"{z} ({c[0]}, {c[1]})" if c else z


def _metro_share_series(hist, cbsa, n=6):
    """[(month, warning share)] for one metro. Same definition research.py uses:
    STRONG is an upside verdict and stays out of the numerator."""
    rows = (hist.get("metros") or {}).get(cbsa) or {}
    out = []
    for m in sorted(rows)[-n:]:
        g, y, r, s = (list(rows[m]) + [0, 0, 0, 0])[:4]
        tot = g + y + r + s
        out.append((m, (100.0 * (y + r) / tot) if tot else None))
    return out


def cand_spotlight(hist, streaks, entries, places, zip_cbsa, cbsa_names,
                   covered, period, want=4, basis_months=None):
    """zip_spotlight (tier 4): one ZIP as a micro-profile.

    PREFERS ZIPs INSIDE METROS ALREADY COVERED THIS MONTH, per the brief: a
    spotlight is most useful as the close-up on a market the slate already
    established, not as a ninth unrelated place.

    The streak is a WARNING run, not a calm one — see SPOTLIGHT_MIN_STREAK.
    """
    warn = (streaks or {}).get("warn") or {}
    if not warn:
        print("zip spotlight: no streak file — rule sits out")
        return []
    ranked = sorted(((z, n) for z, n in warn.items()
                     if n >= MC.SPOTLIGHT_MIN_STREAK and z in entries and z in places),
                    key=lambda t: (zip_cbsa.get(t[0]) not in covered, -t[1], t[0]))
    out, used_metros = [], set()
    for z, months in ranked:
        if len(out) >= want:
            break
        cb = zip_cbsa.get(z)
        if cb in used_metros:
            continue          # one per metro, or the cooldown eats the rest
        e = entries[z]
        m = e.get("m") or {}
        if (m.get("sold") or 0) < MC.SPOTLIGHT_MIN_SOLD:
            continue
        drop = publishable(z, entries)
        if drop:
            print(f"zip spotlight: {z} not publishable — {drop}")
            continue
        cbsa = cb
        used_metros.add(cb)
        where = label_zip(z, places)
        # THE STREAK IS CLAMPED TO THE CONTINUOUS RECORD. streaks.json advances
        # across the whole archive including the reconstructed tracker-v1 months
        # before the seam, so it holds runs of 89 months against a continuous
        # series that is only 73 long — an 89-month run ending June 2026 starts
        # in February 2019, sixteen months on the far side of the seam.
        # research.py's own contract says streak-facing claims never reach
        # across it, and PR3 shipped three posts (11354, 33139, 15222) that did.
        # Claiming the shorter, provable span costs nothing: it is still the
        # longest run we can stand behind.
        capped = bool(basis_months) and months > basis_months
        months = min(months, basis_months) if basis_months else months
        yrs = months // 12
        span = (f"{yrs} year{'s' if yrs != 1 else ''}" if months % 12 == 0 and yrs
                else f"{months} months")
        if capped:
            span = f"every one of the {months} months we have measured"
        tok = token("geo", period=period, zip=z)          # same shape, one namespace
        tok = tok.replace("-geo-", "-spot-")
        hook = (f"{where} has shown at least one housing warning sign for "
                f"{span} straight." if not capped else
                f"{where} has shown at least one housing warning sign in "
                f"{span}.")
        short_hook = (f"{z} ({places[z][0]}) has shown a housing warning sign for "
                      f"{span} straight." if not capped else
                      f"{z} ({places[z][0]}): a housing warning sign in all "
                      f"{months} months we have measured.")
        contrast = (f"Its months of supply sit at {m['mos']:.1f} against a danger line "
                    f"of 4.0 — the level where sellers have historically started "
                    f"losing leverage."
                    if m.get("mos") is not None else
                    f"Its dials are still past at least one danger line — the level "
                    f"where sellers have historically started losing leverage.")
        short_contrast = (f"Its months of supply sit at {m['mos']:.1f}, past the 4.0 "
                          f"danger line where sellers start losing leverage."
                          if m.get("mos") is not None else
                          f"It is past a danger line — where sellers start losing leverage.")
        cap_l, cap_s = compose(hook, contrast,
                               "Nothing about that run is dramatic month to month, "
                               "which is exactly why it is worth naming.", period,
                               short_hook=short_hook, short_contrast=short_contrast)
        out.append({
            "key": tok, "type": "post", "post_type": "zip_spotlight", "tier": 4,
            "zip": z, "metro_cbsa": cbsa,
            "metro_name": cbsa_names.get(cbsa) if cbsa else None,
            "why_headline": hook,
            "why_detail": "\n".join([
                f"- Flagged for {months} consecutive months (research streak file).",
                f"- Chosen because its metro is already on this month's slate."
                if cbsa in covered else
                f"- No metro from this month's slate had a qualifying ZIP.",
            ]),
            "caption": cap_l, "caption_short": cap_s,
            "render": {"card": "spotlight", "zip": z, "where": where,
                       "months": months, "span": span,
                       "mos": m.get("mos"), "period_pretty": pretty_month(period)},
        })
    if not out:
        print("zip spotlight: no ZIP cleared the streak and sales floors")
    return out


def cand_steady(hist, cbsa_names, period):
    """steady_market (tier 5): a market that looks fine AND has been fine.

    The neutrality proof — the post that exists to show the index is not a
    doom account. Both bars must clear, and on 2026-08 real data NONE do: the
    calmest metro swings 25 points over six months. The rule stays honest and
    silent rather than loosening until something qualifies, because a
    manufactured neutrality proof is worth less than none.
    """
    out = []
    for cbsa in (hist.get("metros") or {}):
        series = _metro_share_series(hist, cbsa)
        vals = [v for _, v in series if v is not None]
        if len(vals) < 6:
            continue
        counts = (hist["metros"][cbsa].get(sorted(hist["metros"][cbsa])[-1]) or [])
        if sum(counts) < MC.STEADY_MIN_ZIPS:
            continue
        if vals[-1] > MC.STEADY_MAX_WARN_SHARE or (max(vals) - min(vals)) > MC.STEADY_MAX_RANGE:
            continue
        name = cbsa_names.get(cbsa) or cbsa
        short = short_metro(name)
        hold = 100.0 - vals[-1]
        hook = (f"{short} has not moved much in six months: {hold:.0f}% of the ZIP "
                f"codes we track there still rate HOLD or better.")
        cap_l, cap_s = compose(
            hook,
            f"Its warning share has stayed inside {max(vals) - min(vals):.0f} points "
            f"across that window — no danger lines in sight, and none approaching.",
            "We publish the quiet markets too. A measure that only ever finds "
            "trouble is not a measure.", period)
        out.append({
            "key": token("geo", period=period, zip="0")[:-1].replace("-geo-", "-steady-") + cbsa,
            "type": "post", "post_type": "steady_market", "tier": 5,
            "metro_cbsa": cbsa, "metro_name": name,
            "why_headline": hook,
            "why_detail": f"- Warning share {vals[-1]:.1f}%, six-month range "
                          f"{max(vals) - min(vals):.1f} points.",
            "caption": cap_l, "caption_short": cap_s,
            "render": {"card": "steady", "name": name, "short_name": short,
                       "hold_share": hold, "range": max(vals) - min(vals),
                       "period_pretty": pretty_month(period)},
        })
    if not out:
        print(f"steady market: no metro is both calm (<={MC.STEADY_MAX_WARN_SHARE:.0f}% "
              f"warning) and steady (<={MC.STEADY_MAX_RANGE:.0f}pt range) — rule sits out")
    return out[:2]


def cand_divergence(hist, cbsa_names, period):
    """divergence (tier 3): two metros, same national headlines, opposite signals."""
    moves = []
    for cbsa in (hist.get("metros") or {}):
        series = _metro_share_series(hist, cbsa)
        vals = [v for _, v in series if v is not None]
        if len(vals) < 6:
            continue
        counts = hist["metros"][cbsa].get(sorted(hist["metros"][cbsa])[-1]) or []
        if sum(counts) < MC.DIVERGENCE_MIN_ZIPS:
            continue
        moves.append((cbsa, vals[-1] - vals[0], vals[-1]))
    if not moves:
        return None
    worse = max(moves, key=lambda t: t[1])
    better = min(moves, key=lambda t: t[1])
    if worse[1] < MC.DIVERGENCE_MIN_MOVE or better[1] > -MC.DIVERGENCE_MIN_MOVE:
        print(f"divergence: no opposing pair cleared ±{MC.DIVERGENCE_MIN_MOVE:.0f} "
              f"points — rule sits out")
        return None
    wn = short_metro(cbsa_names.get(worse[0]) or worse[0])
    bn = short_metro(cbsa_names.get(better[0]) or better[0])
    # The metro carrying the SURPRISE is the link target — the improving one,
    # since "somewhere got better" is the half a reader does not expect.
    hook = (f"Two housing markets, six months, opposite directions: {wn} and {bn}.")
    contrast = (f"In {wn} the share of ZIP codes we track showing a warning sign rose "
                f"{worse[1]:.0f} points. In {bn} it fell {abs(better[1]):.0f}. Same "
                f"national headlines over both.")
    cap_l, cap_s = compose(hook, contrast,
                           "Housing is not one market, and a national number is an "
                           "average of places that are not averaging.", period,
                           short_contrast=f"{wn} up {worse[1]:.0f} points, {bn} down "
                                          f"{abs(better[1]):.0f}. Same headlines over both.")
    return {
        "key": token("contrarian", period=period).replace("-contrarian-us", "-diverge-us"),
        "type": "post", "post_type": "divergence", "tier": 3,
        "metro_cbsa": better[0], "metro_name": cbsa_names.get(better[0]),
        "why_headline": hook,
        "why_detail": f"- {wn} {worse[1]:+.1f} pts; {bn} {better[1]:+.1f} pts over six months.\n"
                      f"- Links to {bn}: the improving half is the surprise.",
        "caption": cap_l, "caption_short": cap_s,
        "render": {"card": "divergence", "worse": wn, "better": bn,
                   "worse_move": worse[1], "better_move": better[1],
                   "period_pretty": pretty_month(period)},
    }



def pct1(v):
    """62.233 -> "62.2%". One place, always the sign — the published figure and
    the caption figure must be the same string."""
    return f"{v:.1f}%"


def _count_stable_metro(hist, cbsa_names, period):
    """The metro that scored the SAME number of ZIPs in both months, with the
    largest change in how many showed a warning sign.

    Why insist the denominator match: the national scored set grew by 685 ZIPs
    this month, so nearly every cross-month COUNT comparison is confounded by
    which places were measurable, not by what happened to them. A metro whose
    denominator is identical in both months is the one place a reader can be
    handed two raw counts and trust the difference — no share, no percentage,
    no arithmetic to argue with. Returns None when no metro qualifies.
    """
    prev = prev_period(period)
    best = None
    for cb, months in ((hist or {}).get("metros") or {}).items():
        a, b = months.get(prev), months.get(period)
        if not a or not b:
            continue
        # [green, yellow, red, strong]
        scored_a, scored_b = sum(a), sum(b)
        if scored_a != scored_b or scored_a < MC.RECAP_MIN_METRO_SCORED:
            continue
        warn_a, warn_b = a[1] + a[2], b[1] + b[2]
        move = abs(warn_b - warn_a)
        if move < MC.RECAP_MIN_METRO_MOVE:
            continue
        name = (cbsa_names or {}).get(cb)
        if not name:
            continue
        cand = (move, cb, name, scored_a, warn_a, warn_b)
        if best is None or cand[0] > best[0] or (cand[0] == best[0] and cand[1] < best[1]):
            best = cand
    return best


def cand_recap(rep, hist, cbsa_names, period):
    """recap_thread (tier 3): the month as one X thread — lead, four replies, closer.

    WHY A THREAD AND NOT A LONG POST. The month has five separate things worth
    saying and they argue with each other: the index fell, but it fell from a
    record high; it fell almost everywhere, but two thousand ZIPs still crossed
    the wrong way. Compressed into one caption that becomes mush or spin. Given
    a row each, it reads as an argument that survives its own counter-evidence,
    which is the only reason a stranger trusts a monthly number at all.

    X ONLY. Threading is native there; on Instagram and Facebook a six-part
    thread is six posts nobody scrolls back through.

    EVERY FIGURE IS READ, NEVER RECOMPUTED. run_length in particular has one
    home in research.detect_records() — the card that recomputed it once told
    the world "fifth month in a row" against a truth of three.

    Returns [] rather than a partial thread whenever a figure is missing: a
    recap that silently drops its counter-evidence row is exactly the spin this
    format exists to avoid.
    """
    rec = (rep or {}).get("records") or {}
    wsi, run, direction = rec.get("wsi"), rec.get("run_length"), rec.get("run_direction")
    basis_since, basis_months = rec.get("basis_since"), rec.get("basis_months")
    if wsi is None or not run or not direction or not basis_since:
        print("recap: no records block — rule sits out")
        return []

    series = _wsi_series(n=10_000)
    if len(series) < MC.RECAP_MIN_SERIES:
        print(f"recap: continuous series is only {len(series)} months — rule sits out")
        return []
    peak_m, peak_v = max(series, key=lambda t: t[1])
    floor_m, floor_v = min(series, key=lambda t: t[1])

    moves = (rep or {}).get("state_moves") or []
    fell = sum(1 for r in moves if (r.get("delta") or 0) < 0)
    rose = sum(1 for r in moves if (r.get("delta") or 0) > 0)
    flips = len((rep or {}).get("flips_to_warning") or [])
    scored = (((rep or {}).get("national") or {}).get("scored")) or 0
    stable = _count_stable_metro(hist, cbsa_names, period)
    if not (moves and flips and scored and stable):
        print("recap: missing breadth, flip, scored or count-stable metro — rule sits out")
        return []
    _move, _cb, metro_name, m_scored, m_warn_a, m_warn_b = stable

    verb = "fell" if direction == "down" else "rose"
    opposite = "falling" if direction == "down" else "rising"
    pm, prev_pm = pretty_month(period), pretty_month(prev_period(period))
    # "third month running" — read from run_length, never counted here.
    ordinal = {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth",
               6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth"}.get(run, f"{run}th")

    # The peak line is only worth making when the peak is not this month, and
    # only honest as a comparison when it sits ABOVE where we are now.
    peak_line = (f"Down from {pct1(peak_v)} in {pretty_month(peak_m)}, the highest "
                 f"since we began measuring in {pretty_month(basis_since)}."
                 if direction == "down" and peak_v > wsi and peak_m != period else
                 f"We have published this number every month since "
                 f"{pretty_month(basis_since)}.")

    parts = [
        # 0 — the lead. The only row that carries the link and the attribution.
        (f"{pm}: the share of US ZIP markets showing a housing warning sign "
         f"{verb} for the {ordinal} month running, to {pct1(wsi)}.",
         peak_line),
        # 1 — the counter-evidence, immediately. Falling is not the same as low.
        (f"{opposite.capitalize()} is not the same as low.",
         f"The lowest this measure has read since {pretty_month(basis_since)} is "
         f"{pct1(floor_v)}, back in {pretty_month(floor_m)}. Today it is more than "
         f"double that. A few good months off a high base is still a high base."),
        # 2 — breadth, so nobody reads a national average as one hot market.
        ("The move is broad, not local.",
         f"Warning shares {verb} in {fell} of the {len(moves)} state-level rollups "
         f"we publish this month, and went the other way in {rose}. Most of the map "
         f"moved together."),
        # 3 — the part that did not get better.
        ("It did not get better everywhere.",
         f"{flips:,} individual ZIP markets crossed from healthy into warning "
         f"territory this month. Every one of them is named in the flip list that "
         f"ships free with the release. A national average is not a promise about "
         f"any one street."),
        # 4 — the same-denominator metro: two raw counts, nothing to argue with.
        ("One market shows the shift with no arithmetic to argue about.",
         f"In {metro_name} we scored the same {m_scored} ZIP markets in {prev_pm} "
         f"and in {pm}. In {prev_pm}, {m_warn_a} of them showed a warning sign. "
         f"In {pm}, {m_warn_b} did. Same places, same checks, one month apart."),
        # 5 — the closer: the method, and the promise that makes it worth reading.
        (f"We run the same four checks on about {round(scored, -3):,} ZIP markets "
         f"every month, and publish the answer whichever way it points.",
         f"The record is {basis_months} months long, and the state, metro and ZIP "
         f"files are free to cite. This month the news was better. We would have "
         f"published it either way."),
    ]

    tok = f"mq-{period}-recap-us"
    return [{
        "key": tok, "type": "post", "post_type": "recap_thread", "tier": 3,
        "channel": "x",
        "why_headline": f"{pm} recap thread — {len(parts)} posts",
        "why_detail": (f"The month's five separate stories, in the order they argue: "
                       f"the index {verb} to {pct1(wsi)} for the {ordinal} month, off a "
                       f"{pct1(peak_v)} peak; the floor is {pct1(floor_v)}; {fell} of "
                       f"{len(moves)} states moved with it; {flips:,} ZIPs still crossed "
                       f"the wrong way; {metro_name} moved {m_warn_a}→{m_warn_b} on an "
                       f"unchanged denominator of {m_scored}."),
        "fixed_target": f"/research/{period}/",
        "thread": parts,
    }]

def cand_explainer(period, ws):
    """explainer (tier 5): one concept, evergreen, recycled quarterly.

    No data input by design — it defines the vocabulary the other posts use,
    and links to the methodology page rather than to a market.
    """
    tok = f"mq-{ws.isoformat()}-explain-danger-line"
    hook = "A danger line is not a prediction. It is a level."
    contrast = ("For each of the four signals we track — supply, price trend, time "
                "to sell, price cuts — there is a level past which sellers have "
                "historically started losing leverage. A market past enough of them "
                "reads WATCH or ACT.")
    cap_l, cap_s = compose(
        hook, contrast,
        "The lines are published and do not move to fit a story.", period,
        short_contrast="Past enough of them, a market reads WATCH or ACT. The lines "
                       "are published and do not move.")
    return {
        "key": tok, "type": "post", "post_type": "explainer", "tier": 5,
        "why_headline": "Explainer: what a danger line is.",
        "why_detail": "- Evergreen. Recycle quarterly; links to /methodology.",
        "caption": cap_l, "caption_short": cap_s,
        "fixed_target": "/methodology/",
        "render": {"card": "definition", "period_pretty": pretty_month(period)},
    }


def cand_evergreen(cases, ws, period):
    """Tier 5: fills a horizon week that would otherwise be EMPTY — it never
    displaces a live angle (enforced by only being called for such weeks).
    kind != 'miss' only: the near-miss is methodology-page material, not a
    brag post. Rotation is deterministic in the week date."""
    hits = [c for c in cases if c.get("kind") != "miss"]
    if not hits:
        return None
    c = hits[(ws.toordinal() // 7) % len(hits)]
    pct = round(abs(c["peak_to_trough"]) * 100)
    n = c["lead_months"]
    lead_words = ("a full year" if n == 12 else
                  f"{n // 12} years" if n >= 24 and n % 12 == 0 else
                  f"{n} months")
    tok = token("evergreen", ws=ws.isoformat(), case_id=c["id"])
    _ev_long, _ev_short = compose(
        hook=(f"We flagged {short_metro(c['name'])} {lead_words} before home "
              f"prices there fell {pct}% from their high."),
        contrast=("Every case we publish is re-run with the same danger lines we "
                  "use today — the levels where sellers have historically started "
                  "losing leverage. That includes one market that tripped a line "
                  "and then recovered; we show that one too."),
        evidence=None, period=period,
        short_contrast="Every case is re-run with the lines we use today.")
    return {
        "key": tok, "type": "evergreen", "tier": 5, "week": ws,
        "metro_cbsa": case_cbsa(c["id"]), "metro_name": c["name"],
        "why_headline": f"Evergreen: our signals flagged {c['name']} "
                        f"{c['lead_months']} months before its {pct}% "
                        f"peak-to-trough slide.",
        "why_detail": "\n".join([
            f"- Track-record case {c['id']}: first signal "
            f"{pretty_month(c['first_signal'])}, peak-to-trough "
            f"{c['peak_to_trough'] * 100:.1f}% (chart: pipeline/cases/{c['id']}.png — "
            f"operator-only since 2026-08-19; it plots vendor measurements and "
            f"must not be attached to a public post without clearance).",
            f"- Used because the week of {_mon_day_d(ws)} would otherwise be "
            f"empty — evergreen never displaces a live angle."]),
        # "peak-to-trough" is how an analyst says it. A homeowner asks how far
        # prices fell from the top, and how much warning they would have had.
        "caption": _ev_long, "caption_short": _ev_short,
        "asset_path": f"/assets/mkt/{period}/{tok}.png",
        "render": {"case_id": c["id"], "name": c["name"],
                   "short_name": short_metro(c["name"]),
                   "period_pretty": pretty_month(period),
                   "lead_months": c["lead_months"],
                   "peak_to_trough": c["peak_to_trough"],
                   "first_signal": c["first_signal"]},
    }


def third_business_day(after):
    """docs/RESEARCH.md's pitch timing, as code: the third business day
    after the refresh date."""
    d, n = after, 0
    while n < 3:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n += 1
    return d


def cand_pitches(rep, now_utc, period):
    """Tier 1, channel NULL (a pitch email is not a brand post — null
    channel IS the cap exemption, by the v23 trigger's own rules). One task
    per configured outlet batch; the caption is pitch_draft() verbatim with
    the subject prepended and the bare release link swapped for the tracked
    one, so even a pitch's clicks join the performance loop."""
    batches = list(MC.PRESS_OUTLET_BATCHES)
    if not batches and os.environ.get("PRESS_LIST", "").strip():
        batches = [{"slug": "press", "name": "Press list"}]
    if not rep:
        if batches:
            print("press pitches: no research file this month — none generated")
        return []
    if not batches:
        print("press pitches: no outlet batches configured "
              "(PRESS_OUTLET_BATCHES empty, PRESS_LIST unset) — none generated")
        return []
    subject, body = pitch_draft(rep)
    rel = f"https://shouldisellyet.com/research/{rep['month']}/"
    when = et_to_utc(third_business_day(et_date(now_utc)), "09:00")
    out = []
    for b in batches:
        tok = token("pitch", period=period, batch_slug=b["slug"])
        tracked = body.replace(rel, utm_url("press", tok))
        out.append({
            "key": tok, "type": "press_pitch", "tier": 1,
            "fixed_time": when, "fixed_source": "press",
            "why_headline": f"Press pitch ({b['name']}): {subject}",
            "why_detail": f"Subject: {subject}\n\n{tracked}",
            "caption": f"{subject}\n\n{tracked}",
            "render": {"subject": subject, "batch": b["slug"]},
        })
    return out


# ————— demotion —————

def apply_demotions(cands, demotions):
    """min(5, tier+1) for any candidate whose metro sits in the
    marketing_demotions view, plus the disclosure sentence appended verbatim
    as the final why_detail line. Burst and press pitches are never demoted
    (no metro; not brand posts). Machine refusals can never feed this rule —
    they are not rows, and the view counts only the operator's
    not_newsworthy picklist value."""
    by_cbsa = {d["metro_cbsa"]: d for d in demotions}
    for c in cands:
        d = by_cbsa.get(c.get("metro_cbsa") or "")
        if not d or c.get("fixed_time"):
            continue
        exp = parse_ts(d["expires_at"])
        last = parse_ts(d["last_skip_at"])
        c["tier"] = min(5, c["tier"] + 1)
        c["why_detail"] = (c.get("why_detail") or "") + (
            f"\n- Heads-up: {d['metro_name']} is running one priority tier "
            f"lower until {exp.strftime('%b')} {exp.day}, {exp.year} — skipped "
            f"as not newsworthy twice in the last 60 days (most recently "
            f"{last.strftime('%b')} {last.day}).")
    return cands


# ————— the scheduler —————

class Plan:
    def __init__(self):
        self.placed = []    # (cand, when_utc, channel)
        self.refused = []   # (cand, reason)


def build_slots(windows, now_utc):
    """{week_start_date: [(when_utc, channel, anchor), …]} for the horizon —
    HORIZON_WEEKS Sunday-start ET weeks beginning with the week containing
    now. Instants earlier than now + MIN_LEAD_HOURS are gone (you cannot
    schedule the past); a Monday refresh therefore finds its own week's
    Sunday anchor already behind it and fills Tue/Wed — correct, not a bug.
    Within a week, slots sort anchor-first then chronologically, so the
    first placement in a week naturally takes Sunday 19:30."""
    ws0 = week_start(et_date(now_utc))
    horizon = [ws0 + timedelta(days=7 * k) for k in range(MC.HORIZON_WEEKS)]
    lead = now_utc + timedelta(hours=MC.MIN_LEAD_HOURS)
    out = {}
    for ws in horizon:
        slots = []
        for w in windows:
            when = et_to_utc(ws + timedelta(days=int(w["dow"])), w["at_time"])
            if when >= lead:
                slots.append((when, w["channel"], bool(w.get("anchor"))))
        slots.sort(key=lambda s: (not s[2], s[0], CHANNEL_ORDER.index(s[1])))
        out[ws] = slots
    return out


def plan_schedule(cands, existing, windows, now_utc):
    """Pure function: candidates + existing rows + windows -> Plan. No I/O;
    deterministic given now_utc — this is the unit the tests grip.

    Caps are checked here FIRST, mirroring marketing_slot_conflict R1–R4
    (the trigger is the backstop):
      weekly   MAX_WEEKLY_PER_CHANNEL per (marketing week, channel)
      metro    the same metro within ±METRO_COOLDOWN_DAYS, any channel
      slot     the exact (channel, instant) is taken
    Null-channel candidates (press pitches, bursts) pin fixed_time, occupy
    no slot, and are exempt from all of it — null channel IS the exemption,
    same as the trigger. A candidate that cannot be placed lands in
    plan.refused with a machine-readable reason and is NEVER written:
      refused:weekly_cap:{channel}:{week_start}
      refused:metro_cooldown:{metro}:{days_remaining}d
      refused:no_slot
    Fractional priorities exist only in this sort — the stored value is the
    integer tier (priority_score int in v23)."""
    slots_by_week = build_slots(windows, now_utc)
    weeks = sorted(slots_by_week)

    used_slots = set()          # (channel, when_utc)
    week_counts = {}            # (week_start, channel) -> n
    metro_times = []            # (metro_cbsa, when_utc)
    for r in existing:
        if not r.get("scheduled_for"):
            continue
        when = parse_ts(r["scheduled_for"])
        ch = r.get("channel")
        if ch:
            used_slots.add((ch, when))
            wk = week_start(et_date(when))
            week_counts[(wk, ch)] = week_counts.get((wk, ch), 0) + 1
            if r.get("metro_cbsa"):
                metro_times.append((r["metro_cbsa"], when))

    plan = Plan()
    ordered = sorted(enumerate(cands), key=lambda t: (t[1]["tier"], t[0]))
    for _, c in ordered:
        if c.get("fixed_time"):
            plan.placed.append((c, c["fixed_time"], None))
            continue
        capped_week = None
        cooldown = None
        spot = None
        for ws in weeks:
            if c.get("week") and ws != c["week"]:
                continue
            for when, ch, _anchor in slots_by_week[ws]:
                if c.get("channel") and ch != c["channel"]:
                    continue
                # nextdoor_naomi is Naomi's own local network: only a DMV
                # ZIP fact belongs there, ever (and with the v23 seed the
                # channel has no windows at all, so this line is dormant).
                if ch == "nextdoor_naomi" and not (c.get("zip") and MC.is_dmv(c["zip"])):
                    continue
                if week_counts.get((ws, ch), 0) >= MC.MAX_WEEKLY_PER_CHANNEL:
                    capped_week = capped_week or (ch, ws)
                    continue
                if (ch, when) in used_slots:
                    continue
                m = c.get("metro_cbsa")
                hit = next((t for mm, t in metro_times if mm == m
                            and abs((when - t).total_seconds())
                            <= MC.METRO_COOLDOWN_DAYS * 86400), None) \
                    if m else None
                if hit is not None:
                    days_left = max(0, (hit + timedelta(
                        days=MC.METRO_COOLDOWN_DAYS) - now_utc).days)
                    cooldown = cooldown or (m, days_left)
                    continue
                spot = (when, ch, ws)
                break
            if spot:
                break
        if spot:
            when, ch, ws = spot
            plan.placed.append((c, when, ch))
            used_slots.add((ch, when))
            week_counts[(ws, ch)] = week_counts.get((ws, ch), 0) + 1
            if c.get("metro_cbsa"):
                metro_times.append((c["metro_cbsa"], when))
        elif cooldown:
            # Cooldown outranks the cap in the report: it means a free slot
            # existed and the METRO was the blocker — the actionable truth.
            plan.refused.append(
                (c, f"refused:metro_cooldown:{cooldown[0]}:{cooldown[1]}d"))
        elif capped_week:
            plan.refused.append(
                (c, f"refused:weekly_cap:{capped_week[0]}:{capped_week[1]}"))
        else:
            plan.refused.append((c, "refused:no_slot"))
    return plan


def evergreen_pass(plan, existing, windows, cases, period, now_utc):
    """Second pass, AFTER live candidates have been placed: one evergreen
    per horizon week that ended up with zero channel-bearing placements —
    so evergreen can never displace a live angle."""
    busy = {week_start(et_date(when)) for _, when, ch in plan.placed if ch}
    for r in existing:
        if r.get("channel") and r.get("scheduled_for"):
            busy.add(week_start(et_date(parse_ts(r["scheduled_for"]))))
    pseudo = list(existing) + [
        {"channel": ch, "scheduled_for": iso_z(when),
         "metro_cbsa": c.get("metro_cbsa"), "status": "suggested"}
        for c, when, ch in plan.placed if ch]
    ws0 = week_start(et_date(now_utc))
    for k in range(MC.HORIZON_WEEKS):
        ws = ws0 + timedelta(days=7 * k)
        if ws in busy:
            continue
        c = cand_evergreen(cases, ws, period)
        if not c:
            continue
        sub = plan_schedule([c], pseudo, windows, now_utc)
        for p in sub.placed:
            plan.placed.append(p)
            pseudo.append({"channel": p[2], "scheduled_for": iso_z(p[1]),
                           "metro_cbsa": p[0].get("metro_cbsa"),
                           "status": "suggested"})
        plan.refused.extend(sub.refused)
    return plan


# ————— rows + manifest —————

def hashtags_for(channel, metro_name):
    tags = MC.HASHTAGS.get(channel or "", ())
    if metro_name and channel in ("ig", "x"):
        tags = tags + (metro_tag(metro_name),)
    return " ".join(tags) or None


# Editorial label for the rules that predate the taxonomy. A row without one
# shows as "unclassified" in the mix meter rather than silently counting as
# something it is not.
POST_TYPE_DEFAULT = {"press_pitch": "press_pitch", "burst": "burst",
                     "receipt_quote": "receipt"}


def rows_from_placement(c, when, channel, period):
    """A placement becomes one row, or — for a thread — many.

    THE THREAD IS THE UNIT EVERYWHERE ELSE. It was planned as one candidate,
    consumed one slot, and spent one post of the weekly cap; only here does it
    become six rows, because six is what the operator has to paste. Keeping the
    expansion at the very last step is what stops a thread being counted six
    times by the scheduler, the cap, the mix meter and the calendar.

    ORDER MATTERS AND IS NOT INCIDENTAL. Position 0 is emitted first because
    schema-v31's marketing_thread_guard refuses a reply whose lead is not yet
    in the table. The caller inserts this list in order.

    Each row carries its OWN dedupe_key and utm_campaign: both are uniquely
    indexed, and — worse than a refusal — the generator writes with
    on_conflict=dedupe_key + ignore-duplicates, so rows sharing a key would be
    silently DISCARDED with an HTTP 201 and the thread would arrive truncated
    with every sign of success.
    """
    parts = c.get("thread")
    if not parts:
        return [row_from_placement(c, when, channel, period)]

    out = []
    for i, (hook, body) in enumerate(parts):
        # Only the lead carries the link, the call to action and the
        # attribution; see lint_caption(reply=True) for why.
        if i == 0:
            # A BARE LINK, NO CTA PROSE AND NO HASHTAGS. The lead's whole job is
            # to make someone read the next five posts; "See where your ZIP
            # stands (free):" spends 34 of 280 characters asking for a click
            # the thread has not earned yet, and hashtags on a thread lead read
            # as an advert. The link still resolves to the same /go/ redirect,
            # so attribution is unchanged.
            text = "\n\n".join([hook, body, "{short_url}",
                                 f"ShouldISellYet · {pretty_month(period)}"])
        else:
            text = f"{hook}\n\n{body}"
        sub = dict(c, key=f"{c['key']}-{i}", caption=text, caption_short=text,
                   why_headline=(c["why_headline"] if i == 0
                                 else f"{c['why_headline']} — reply {i}"))
        row = row_from_placement(sub, when, channel, period, reply=(i > 0))
        row["thread_key"] = c["key"]
        row["thread_position"] = i
        out.append(row)
    return out


def row_from_placement(c, when, channel, period, reply=False):
    """One insert-ready dict. status defaults to 'suggested' in the DB; the
    caption's {utm_url} placeholder resolves only now, because the link's
    utm_source is the channel the scheduler just assigned."""
    src = c.get("fixed_source") or channel or "x"   # burst: X is the named channel
    # WHERE THE CLICK LANDS. A post about one metro that opens the homepage has
    # thrown the click away. Resolution: the metro's own page if it has one,
    # else the ZIP's page, else the month's report — never the homepage, which
    # lint_caption() refuses outright.
    # MOST SPECIFIC WINS. A post about 20001 belongs on 20001's page, not on
    # Washington DC's — a geo candidate carries both a ZIP and the metro that
    # contains it, and resolving metro-first sent ZIP posts to the wrong page.
    target = (c.get("fixed_target")
              or (f"/zip/{c['zip']}/" if c.get("zip") else None)
              or metro_slug(c.get("metro_cbsa"))
              or (f"/research/{period}/" if period else "/"))
    url = utm_url(src, c["key"], target)
    # The visible link is a REAL redirect that carries the campaign token, so
    # the link a reader taps and the link the nightly join counts are the same
    # one. post_pack.py --render writes the page; see schema-v25.
    short_path = f"/go/{c['key']}/"
    short_link = f"shouldisellyet.com{short_path}"
    tags = hashtags_for(channel or c.get("fixed_source"), c.get("metro_name"))
    fill = lambda s: (s or "").replace("{short_url}", short_link) \
                              .replace("{utm_url}", url).replace("{tags}", tags or "")
    cap_long = fill(c.get("caption"))
    cap_short = fill(c.get("caption_short"))
    # X without premium posts the short one, so that is what gets linted for X.
    lint = lint_caption(c.get("caption_short") if (channel == "x" and not MC.X_PREMIUM)
                        else c.get("caption"), channel, tags, short_link,
                        None if reply else target, reply=reply)
    return {
        "type": c["type"],
        "post_type": c.get("post_type") or POST_TYPE_DEFAULT.get(c["type"]), "channel": channel,
        "scheduled_for": iso_z(when),
        "priority_score": int(c["tier"]),
        "why_headline": c["why_headline"], "why_detail": c.get("why_detail"),
        "metro_cbsa": c.get("metro_cbsa"), "metro_name": c.get("metro_name"),
        "zip": c.get("zip"),
        "asset_path": c.get("asset_path"),
        "caption": cap_long or None,
        "caption_short": cap_short or None,
        # A REPLY HAS NO LINK, SO IT HAS NO REDIRECT AND NO TRACKED URL.
        # write_redirects() writes a /go/ page for every manifest task that
        # carries a destination; leaving these set would ship five real pages
        # nothing ever links to, and would put five campaign tokens into the
        # perf loop that can never register a click — measured-zero noise in a
        # leaderboard that is careful to distinguish that from unmeasured.
        "short_path": None if reply else short_path,
        "link_target": None if reply else target,
        "lint": lint,
        "hashtags": tags,
        "utm_campaign": c["key"], "utm_url": None if reply else url,
        "period": period, "source_id": c.get("source_id"),
        "dedupe_key": c["key"],
    }


def write_pack_manifest(rows, cands_by_key, period):
    """pipeline/marketing/pack-{period}.json — the deploy-time contract with
    post_pack.py --render: per task the token, the type, the asset path, and
    the PUBLIC scalars its card renders from. Committed by update.yml's
    snapshot step; deterministic bytes (sorted keys, no clock)."""
    # THE MANIFEST ACCUMULATES A PERIOD; IT IS NOT A LOG OF ONE RUN. Rebuilding
    # it from scratch was survivable only while the first run of a period was
    # the only run. It is not: the generator is idempotent, so every later run
    # of the same month skips the rows it already inserted and wrote a manifest
    # containing only what was new — on the second Monday of a month, nothing.
    #
    # That is not merely lost card metadata. web/go/ is gitignored and the
    # /go/ redirect pages are regenerated at deploy from this file alone, so an
    # emptied manifest stops writing the redirect for every post already
    # published: every link in every posted caption 404s while the queue still
    # reads as healthy.
    #
    # Merging by token: this run replaces its namesakes, earlier runs of the
    # same period survive. A token whose row is later deleted keeps a working
    # redirect rather than a dead one — the right way round for a link somebody
    # has already posted.
    p = PACK_DIR / f"pack-{period}.json"
    by_token = {}
    if p.exists():
        try:
            for prior in (json.loads(p.read_text()).get("tasks") or []):
                if prior.get("utm_campaign"):
                    by_token[prior["utm_campaign"]] = prior
        except Exception as exc:
            # Must not take the run down, but must be loud: quietly starting
            # fresh here is how the links die.
            print(f"pack manifest unreadable ({exc}) — rebuilding from this run only")
            by_token = {}
    for r in sorted(rows, key=lambda r: r["dedupe_key"]):
        c = cands_by_key.get(r["dedupe_key"], {})
        # utm_url rides along so post_pack can write the /go/ redirect from
        # the manifest alone — the renderer must stay pure, and rebuilding the
        # tracked URL there would duplicate the channel logic that lives here.
        by_token[r["dedupe_key"]] = {
            "utm_campaign": r["dedupe_key"], "type": r["type"],
            "asset_path": r.get("asset_path"),
            "utm_url": r.get("utm_url"),
            "render": c.get("render", {})}
    tasks = [by_token[k] for k in sorted(by_token)]
    PACK_DIR.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"period": period, "tasks": tasks},
                            separators=(",", ":"), sort_keys=True))
    return p


# ————— burst (called from rate_watch.py, not from the refresh) —————

def insert_burst_task(now_rate, prior_rate, rate_period,
                      now_utc=None, dry_run=False):
    """Called by rate_watch.main() after the >= RATE_BURST_POINTS gate.

    Tier 0, channel NULL — a Friday burst cannot reach any X window inside
    48 hours, so null-channel is the only schedulable shape (exempt from the
    window trigger by construction); the copy names X as the intended
    channel. Pinned to the FIRST 09:00/19:30 ET instant inside
    BURST_WINDOW_HOURS. No asset: a 48h window cannot depend on a deploy
    cycle. dedupe key mq-burst-{rate_period}-{week_start} makes a same-week
    Friday re-run a no-op. NEVER raises past its own prints — the rate email
    must send even when Supabase is down; any failure returns None."""
    now_utc = now_utc or datetime.now(timezone.utc)
    delta = now_rate - prior_rate
    ws = week_start(et_date(now_utc))
    tok = token("burst", rate_period=rate_period, ws=ws.isoformat())
    d0 = et_date(now_utc)
    slot = min(et_to_utc(d0 + timedelta(days=k), t)
               for k in range(3) for t in MC.BURST_SLOT_TIMES_ET
               if et_to_utc(d0 + timedelta(days=k), t) > now_utc)
    closes = now_utc + timedelta(hours=MC.BURST_WINDOW_HOURS)
    direction = "dropped" if delta < 0 else "rose"
    play = ("Rate-drop play: buyers just gained purchasing power — the moment "
            "sellers start asking the question." if delta < 0 else
            "Rates-rose play: the pressure story is live — every point costs "
            "your sellers' buyers real purchasing power.")
    cand = {
        "key": tok, "type": "burst", "tier": 0, "fixed_source": "x",
        "why_headline": f"The 30-year rate {direction} {abs(delta):.2f} points "
                        f"— burst window open for {MC.BURST_WINDOW_HOURS} hours.",
        "why_detail": "\n".join([
            f"- {now_rate:.2f}% now vs {prior_rate:.2f}% at the "
            f"{pretty_month(rate_period)} data refresh ({delta:+.2f} pts; "
            f"threshold {MC.RATE_BURST_POINTS}).",
            f"- {play}",
            f"- Post on X first. Window closes {_fmt_et(closes)}; this card "
            f"outranks everything until then."]),
        "caption": (f"Mortgage rates just moved {delta:+.2f} points in a week "
                    f"({prior_rate:.2f}% → {now_rate:.2f}%). A move that size "
                    f"changes the monthly math for buyers — which changes the "
                    f"market sellers are selling into. Free monthly checkup "
                    f"for any ZIP: {{utm_url}}"),
    }
    tripped = guard(cand)
    if tripped:
        print(f"REFUSED {tok} refused:copy:{','.join(tripped)}")
        return None
    row = row_from_placement(cand, slot, None, rate_period)
    if dry_run:
        print(f"--dry-run: WOULD-INSERT {tok} burst t0 no-channel {iso_z(slot)}")
        return tok
    url, key = sb_env()
    if not (url and key):
        print("burst task: Supabase not configured — not written "
              "(rate email unaffected)")
        return None
    ok, err = post_task_row(url, key, row)
    if not ok:
        print(f"burst task not written ({err}) — rate email unaffected")
        return None
    print(f"burst task written: {tok} scheduled {iso_z(slot)}")
    return tok


# ————— main —————

def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "web" / "data"))
    ap.add_argument("--dry-run", action="store_true",
                    help="plan and print; write nothing, fetch nothing")
    ap.add_argument("--force-period", default="",
                    help="override the data period (testing)")
    ap.add_argument("--now", default="",
                    help="frozen clock, ISO8601 (testing; default: real now)")
    args = ap.parse_args(argv)

    now_utc = parse_ts(args.now) if args.now else datetime.now(timezone.utc)

    meta_p = Path(args.data) / "meta.json"
    if not meta_p.exists():
        print(f"no meta.json under {args.data} — nothing to generate; exiting 0")
        return 0
    period = args.force_period or json.loads(meta_p.read_text()).get("period", "")
    if not period:
        print("no data period in meta.json — nothing to generate; exiting 0")
        return 0

    url, key = sb_env()
    dry = args.dry_run or not (url and key)
    if not (url and key):
        print("DRY RUN (Supabase not configured — SUPABASE_URL / "
              "SUPABASE_SERVICE_KEY unset)")
    elif args.dry_run:
        print("DRY RUN (--dry-run)")
    print(f"marketing tasks — period {period} · now {iso_z(now_utc)}")

    # — inputs (each absence degrades to a printed line, never a crash) —
    rep = load_research(period)
    if not rep:
        print(f"research-{period}.json missing — records/contrarian/pitch "
              f"rules sit out")
    vel = load_velocity_current(args.data)
    vel_prev = load_velocity_prev(period)
    entries = load_current(args.data)
    places = load_places()
    snap = load_snapshot(prev_period(period))
    flips = diff_verdicts(snap or {}, entries) if snap else \
        {"to_watch": [], "to_act": [], "to_hold": [], "to_strong": []}
    angles = build_angles(entries, flips, places, period)
    zip_cbsa, cbsa_names = load_cbsa()
    cases = load_case_index()

    windows, windows_src = load_windows(url, key, dry)
    if dry:
        receipts, demotions = [], []
        print("receipts/demotions not fetched (dry run) — rules sit out")
    else:
        receipts = load_receipts(url, key)
        demotions = load_demotions(url, key)

    # — candidates, in tier order —
    today = et_date(now_utc)
    cands = []
    for c in [cand_record(rep), cand_contrarian(rep, period)]:
        if c:
            cands.append(c)
    cands += cand_pitches(rep, now_utc, period)
    cands += cand_receipts(receipts, today, cbsa_names, places, period)
    cands += cand_flips(vel, vel_prev, period)
    cands += cand_geo(angles, period, zip_cbsa, cbsa_names, entries)

    # The taxonomy rules. A spotlight prefers a metro the slate already covers,
    # so it runs AFTER the metro stories and reads which ones landed.
    covered = {c.get("metro_cbsa") for c in cands if c.get("metro_cbsa")}
    hist = load_history()
    if hist:
        d = cand_divergence(hist, cbsa_names, period)
        if d:
            cands.append(d)
        cands += cand_steady(hist, cbsa_names, period)
        cands += cand_spotlight(hist, load_streaks(), entries, places, zip_cbsa,
                                cbsa_names, covered, period,
                                basis_months=((rep or {}).get("records") or {}).get("basis_months"))
    cands += cand_recap(rep, hist, cbsa_names, period)
    cands.append(cand_explainer(period, week_start(et_date(now_utc))))
    apply_demotions(cands, demotions)

    kept = []
    for c in cands:
        tripped = guard(c)
        if tripped:
            print(f"REFUSED {c['key']} refused:copy:{','.join(tripped)}")
        else:
            kept.append(c)

    # — idempotency: a key that already has a row is not re-planned; its
    # schedule is owned by the first write plus the operator's Reschedule,
    # never by a re-run. on_conflict remains the backstop. —
    if not dry and kept:
        # A THREAD IS STORED UNDER ITS ROW KEYS, NOT ITS CANDIDATE KEY. The
        # candidate is mq-{period}-recap-us; the rows are that plus -0..-n. So
        # probing the candidate key never matched, and the thread was re-planned
        # on every run — taking a slot in the plan, displacing other candidates,
        # and then being silently dropped by on_conflict, which meant the
        # generator's printed schedule disagreed with the database's.
        probe = lambda c: f"{c['key']}-0" if c.get("thread") else c["key"]
        seen = existing_keys(url, key, [probe(c) for c in kept])
        for c in [c for c in kept if probe(c) in seen]:
            print(f"exists {c['key']} — left untouched")
        kept = [c for c in kept if probe(c) not in seen]

    ws0 = week_start(today)
    h_start = et_to_utc(ws0, "00:00")
    h_end = et_to_utc(ws0 + timedelta(days=7 * MC.HORIZON_WEEKS), "00:00")
    existing = [] if dry else load_existing(url, key, h_start, h_end)

    plan = plan_schedule(kept, existing, windows, now_utc)
    plan = evergreen_pass(plan, existing, windows, cases, period, now_utc)

    for c, reason in plan.refused:
        print(f"REFUSED {c['key']} {reason}")

    rows = [r for c, when, ch in plan.placed
            for r in rows_from_placement(c, when, ch, period)]
    inserted = 0
    for row in rows:
        label_line = (f"{row['dedupe_key']} · {row['type']} "
                      f"t{row['priority_score']} · {row['channel'] or 'no-channel'} "
                      f"· {row['scheduled_for']}")
        if dry:
            print(f"WOULD-INSERT {label_line}")
            continue
        ok, err = post_task_row(url, key, row)
        if ok:
            inserted += 1
            print(f"insert {label_line}")
        else:
            # The trigger is the backstop (a concurrent writer, a calendar
            # migration mid-run): its raise arrives here as an HTTP error,
            # is printed as a refusal, and the run continues.
            print(f"REFUSED {row['dedupe_key']} {err}")

    cands_by_key = {c["key"]: c for c, _, _ in plan.placed}
    pack = write_pack_manifest(rows, cands_by_key, period)

    print(f"marketing queue: {len(plan.placed)} placed · "
          f"{len(plan.refused)} refused · "
          f"{inserted if not dry else 0} inserted · period {period} · "
          f"windows {windows_src} · pack {pack.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
