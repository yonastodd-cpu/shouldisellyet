#!/usr/bin/env python3
"""ShouldISellYet Research — the Warning-Sign Index (WSI) and its history.

    WSI = ZIPs at WATCH or ACT ÷ all scored ZIPs, as a percentage.

DEFINITION (index v1.0 — see /research/methodology.html for the changelog):

  * Four signals, constant since the series begins: months of supply, price
    trend y/y, time-to-sell y/y, inventory y/y — the site's danger lines,
    identical thresholds, evaluated by the SAME verdict engine the product
    uses. The fifth product signal (price-cuts share) is deliberately NOT in
    the index: it has no pre-2026 history, and an index survives only if
    every month measures the same thing. (Measured impact of the exclusion
    at adoption: 62.2% vs 62.4% — composition shifts, the share barely.)
  * "Scored" = the engine had at least two known signals. Insufficient ZIPs
    are excluded from BOTH sides of the fraction — a market we could not
    assess is not a market we counted as healthy.
  * STRONG counts in the denominator only: it is the opposite of a warning,
    but it is a scored market.

TWO SEGMENTS, ONE DISCLOSED SEAM:

  hub-v2      2019-06 → present. Redfin's Data Center hub file, the same
              source the live site refreshes from, ~29k scored ZIPs. This is
              the CONTINUOUS series: records, deltas, and streaks-facing
              claims are computed here and never reach across the seam.
  tracker-v1  2012-03 → 2019-05. Reconstructed from the frozen legacy
              tracker (~18k ZIPs). Context tail: charted in a lighter
              stroke, labeled as a prior-universe reconstruction, excluded
              from records. The two sources overlap for 84 months; the
              backfill measures their per-ZIP agreement and prints it.

Modes:
  python3 pipeline/research.py                          # monthly, in CI
  python3 pipeline/research.py --backfill \
      --hub PATH_all_zips.csv --tracker PATH_tracker.tsv.gz

MONTHLY recomputes the current month from web/data/zips shards — restated to
the 4-signal definition from each ZIP's published metrics — appends to
pipeline/research/history.json, advances streaks, writes levels-{month}.json
(next month's flip base) and research-{month}.json (everything a release
page needs). BACKFILL is one-time; both source files are frozen or
re-downloadable, so history is reproducible bit-for-bit.
"""

import argparse
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from shard_layout import require_shards
from fetch_data import load_rows, row_to_metrics
from verdict import ZipMetrics, evaluate

HERE = Path(__file__).parent
RESEARCH_DIR = HERE / "research"
CROSSWALK = HERE / "data" / "zip_cbsa.csv"
PLACES = HERE / "data" / "zip_places.csv"

# The seam is DERIVED at backfill time (first month the hub file actually
# covers), never assumed: the hub's history depth is Redfin's call, and a
# hardcoded seam left a 12-month hole the first time it was tried.
SEAM_FALLBACK = "2020-06"
LEVELS = ("green", "yellow", "red", "strong")
WARN = {"yellow", "red"}

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


# ————————————————————————————————————————————————————————————————————————
# PUBLICATION OPTIONALITY — the index's three possible futures, as config
# ————————————————————————————————————————————————————————————————————————
#
# WHY THIS BLOCK EXISTS. Every one of the 173 monthly values in history.json
# is computed from Redfin data, and Redfin ingestion stopped 2026-08-14. What
# may still be PUBLISHED is a question with counsel, and the answer is one of
# three: keep publishing the whole series, publish only the current vendor's
# era, or stop publishing the index while it is reviewed. Building all three
# now makes the answer a flag flip instead of a project — and, more
# importantly, makes the flip reversible, because none of them touch the
# stored history.
#
# WHAT NONE OF THESE MODES DO. They do not modify, truncate, or delete
# pipeline/research/history.json, and they do not remove the Redfin credit
# from anything still being published. LEGAL_HOLD.md is in force: this file
# changes what leaves the building, never what is kept. Stripping attribution
# from data we still publish would be the worse fault, so the credit follows
# the data — while a value is published, its source is named.
#
# READ ONCE, AS A MODULE ATTRIBUTE. Same shape as realtor_crosscheck.SHOW:
# environment at import, module attribute thereafter, so flipping it in
# production is a CI variable change and flipping it in a test is one
# monkeypatch. Callers ask the predicates below rather than comparing the
# strings themselves — a scattered `== "paused"` is how one surface gets
# missed.
#
# THIS IS A STATIC SITE, so a flip is a variable change plus a rebuild, not
# an instant switch. Same caveat realtor_crosscheck carries, said again here
# because somebody will ask "how fast can we turn it off".

INDEX_MODES = ("full", "truncated", "paused")
INDEX_LICENSES = ("current", "restricted")

# The default is TODAY'S BEHAVIOUR, deliberately. Publication continues
# unchanged until counsel answers; a deploy of this change must be invisible.
INDEX_MODE = (os.environ.get("INDEX_MODE") or "full").strip().lower()
INDEX_LICENSE = (os.environ.get("INDEX_LICENSE") or "current").strip().lower()

# The truncation cutoff: the first month computed on the CURRENT vendor's
# basis. RentCast readings went live with tranche-1 on 2026-08-20
# (pipeline/tranches.json), and July 2026 is the last Redfin-basis index
# value (data_pause.LAST_INGESTED_PERIOD), so the current era starts here.
# Overridable because "the current vendor's era" is counsel's line to draw,
# not ours — if they name a different month, it is a variable, not an edit.
INDEX_CUTOFF = (os.environ.get("INDEX_CUTOFF") or "2026-08").strip()

# A TYPO MUST NOT PUBLISH THE THING WE WERE TOLD TO STOP PUBLISHING. If
# INDEX_MODE is set to "truncate" or "pause", falling back to the default
# would silently republish the full Redfin-basis series after counsel asked
# for less. A build that stops is recoverable in five minutes; a publication
# that should not have happened is not.
if INDEX_MODE not in INDEX_MODES:
    raise SystemExit(
        f"INDEX_MODE={INDEX_MODE!r} is not one of {INDEX_MODES}. "
        f"Refusing to guess: the wrong guess republishes the Warning-Sign "
        f"Index history. See INDEX_OPTIONS.md.")
if INDEX_LICENSE not in INDEX_LICENSES:
    raise SystemExit(
        f"INDEX_LICENSE={INDEX_LICENSE!r} is not one of {INDEX_LICENSES}. "
        f"Refusing to guess: the wrong guess ships the wider grant. "
        f"See INDEX_OPTIONS.md.")

# The series names that appear in the published CSV's `series` column and in
# the chart legend. V1_* are the two segments of the Redfin-basis index that
# already ship; V2 is the new basis and is NEVER merged into either.
SERIES_CONTINUOUS = "continuous"
SERIES_RECONSTRUCTION = "reconstruction"
SERIES_V2 = "v2-active-listings"

# The v2 index: same fraction (share of scored ZIPs past a danger line), new
# basis (verdict_v2 lines over active-listing statistics). It is a DIFFERENT
# INDEX, not a continuation — different signals, different lines, different
# universe — so it gets its own file, its own series name, its own stroke,
# and never an append onto the v1 tail. Absent file means an empty series,
# which is exactly the state today: nothing to publish yet, nothing to hide.
HISTORY_V2 = RESEARCH_DIR / "history-v2.json"
V2_BASIS = "active listings"          # matches data_pause.RELEASED_BASIS
V2_LABEL = "Index v2 · active-listing basis"


def index_mode():
    """The publication mode, read live so a monkeypatch takes effect."""
    return INDEX_MODE


def publishes_index():
    """May any index value be published at all?"""
    return INDEX_MODE != "paused"


def publishes_history_file():
    """May the monthly history CSV be published at its public URL?

    False means the URL must stop serving the file — 410 Gone, not 404: the
    resource existed and is withdrawn, and 410 is the only status that says
    so. The stored history.json is untouched either way; this is about
    distribution, not retention.
    """
    return INDEX_MODE != "paused"


def cutoff_month():
    """The first month that may be published, or None when all may be."""
    return INDEX_CUTOFF if INDEX_MODE == "truncated" else None


def publishes_month(month):
    """May a value for this month be published?"""
    if not publishes_index():
        return False
    cut = cutoff_month()
    return cut is None or month >= cut


def published_series(series):
    """The v1 series as it may be PUBLISHED — never as it is stored.

    full        every month, unchanged
    truncated   months from the cutoff forward only
    paused      nothing

    Callers must render from this, not from national_series(), everywhere a
    value leaves the building: chart, CSV, prose, JSON-LD, share cards.
    """
    if not publishes_index():
        return []
    cut = cutoff_month()
    if cut is None:
        return list(series)
    return [(m, v) for m, v in series if m >= cut]


def series_break_note(cut=None):
    """The visible note that must travel with a truncated series.

    NO SILENT SPLICE. A chart that simply starts in August 2026 tells a
    reader the index is four weeks old; a chart that starts there and says
    why tells them what actually happened. This sentence is the difference,
    and it ships on the page, in the chart image, in the release folder, and
    in the licence.
    """
    cut = cut or INDEX_CUTOFF
    return (f"History before {pretty(cut)} was computed from a prior "
            f"vendor's data and is no longer distributed; the series "
            f"restarts on the current basis.")


# Reader-facing, for the paused mode. Says what is true — the index is under
# review — without speculating about the outcome or naming the vendor whose
# licence is being reviewed. Matches the register of data_pause.NOTICE_BODY.
PAUSED_NOTICE = ("The Warning-Sign Index is under review and is not being "
                 "published this month. The aggregates on this page are "
                 "unaffected.")
PAUSED_FILE_NOTICE = ("The Warning-Sign Index history file is not currently "
                      "published.")


def load_history_v2(path=None):
    """The v2 index history, or an empty shell when it does not exist yet.

    Same shape as history.json — {"months": [...], "national": {m: [g,y,r,s]}}
    — so wsi_of()/unpack() work unchanged over it. SCAFFOLD: nothing writes
    this file yet. It reads as empty today, which keeps every mode's default
    output identical to what already ships.
    """
    p = Path(path or HISTORY_V2)
    if p.exists():
        try:
            return json.loads(p.read_text())
        except ValueError:
            # A malformed v2 file must not take the research build down and
            # must not fall back to "pretend it is v1" either. Empty is the
            # honest reading: we have no v2 series to show.
            print(f"research: {p.name} is unreadable — v2 series omitted")
    return {"version": "2.0", "basis": V2_BASIS, "months": [], "national": {}}


def v2_series(h2=None):
    """[(month, wsi)] for the v2 index, ascending. [] until the file exists."""
    h2 = load_history_v2() if h2 is None else h2
    out = []
    for m in sorted(h2.get("months") or []):
        packed = (h2.get("national") or {}).get(m)
        if not packed:
            continue
        v = wsi_of(unpack(packed))
        if v is not None:
            out.append((m, v))
    return out


def published_v2_series(series=None, upto=None):
    """The v2 series as it may be published, optionally capped at a month.

    Paused withholds it like everything else: the review is of the index,
    not of one vendor's contribution to it. Truncation does not need to
    filter it — every v2 month is by definition on the current basis — but
    the cutoff is applied anyway so the two series can never overlap in a
    way that reads as continuous.
    """
    s = v2_series() if series is None else list(series)
    if not publishes_index():
        return []
    cut = cutoff_month()
    if cut is not None:
        s = [(m, v) for m, v in s if m >= cut]
    if upto is not None:
        s = [(m, v) for m, v in s if m <= upto]
    return s


def pretty(month):
    return f"{MONTH_NAMES[int(month[5:7]) - 1]} {month[:4]}"


def prev_month(m):
    y, mm = int(m[:4]), int(m[5:7])
    return f"{y - 1}-12" if mm == 1 else f"{y}-{mm - 1:02d}"


# ————— shared loads —————

def load_crosswalk():
    out = {}
    if CROSSWALK.exists():
        for r in csv.DictReader(CROSSWALK.open(encoding="utf-8")):
            out[r["zip"]] = (r["cbsa"], r["title"], r["is_metro"] == "1")
    return out


def load_places():
    out = {}
    if PLACES.exists():
        for r in csv.DictReader(PLACES.open(encoding="utf-8")):
            out[r["zip"]] = (r["city"], r["state"])
    return out


def index_level(m: ZipMetrics):
    """The index's 4-signal restatement: same engine, price-cuts withheld.
    Returns a level, or None when unscored on the index definition."""
    m.price_drop_share = None
    v = evaluate(m)
    if any(c == "insufficient_data" for c, _, _ in v.reasons):
        return None
    return v.level


def load_shard_levels(data_dir):
    """(levels, states) for the current month, restated from each ZIP's
    published metrics — NOT from the shard's 5-signal verdict."""
    levels, states = {}, {}
    require_shards(Path(data_dir, "zips"), "research.load_shard_levels",
                   "the withdrawn per-ZIP metrics (mos, spy, dom, domy, invy)")
    for f in sorted(Path(data_dir, "zips").glob("*.json")):
        for z, e in json.loads(f.read_text()).items():
            mm = e.get("m", {})
            lv = index_level(ZipMetrics(
                z, e.get("st") or f.stem, "",
                months_of_supply=mm.get("mos"),
                median_sale_price_yoy=mm.get("spy"),
                median_dom=mm.get("dom"),
                median_dom_yoy=mm.get("domy"),
                inventory_yoy=mm.get("invy")))
            if lv:
                levels[z] = lv
                states[z] = e.get("st") or f.stem
    return levels, states


# ————— aggregation —————

def counts_of(levels):
    c = dict.fromkeys(LEVELS, 0)
    for lv in levels.values():
        if lv in c:
            c[lv] += 1
    return c


def wsi_of(c):
    scored = sum(c.values())
    return (100.0 * (c["yellow"] + c["red"]) / scored) if scored else None


region_share = wsi_of   # same fraction at any altitude


def aggregate(levels, states, crosswalk):
    nat = dict.fromkeys(LEVELS, 0)
    st_c = defaultdict(lambda: dict.fromkeys(LEVELS, 0))
    cb_c = defaultdict(lambda: dict.fromkeys(LEVELS, 0))
    for z, lv in levels.items():
        if lv not in nat:
            continue
        nat[lv] += 1
        st = states.get(z, "")
        if len(st) == 2:
            st_c[st][lv] += 1
        hit = crosswalk.get(z)
        if hit:
            cb_c[hit[0]][lv] += 1
    return nat, dict(st_c), dict(cb_c)


# ————— records (computed ONLY on a same-source series) —————

def detect_records(series):
    """series: [(month, wsi)] ascending, all one source segment, current
    last.

    "highest since {m}" names the last month AT OR ABOVE the current value —
    inclusive on purpose: claiming a superlative the archive contradicts is
    how an index dies, so a tie blocks the bigger claim. "record" means no
    prior month in THIS segment reached it; the caller phrases that as
    "highest in the continuous series", never "highest ever", because the
    context tail before the seam is a different universe.
    """
    if not series:
        return {}
    months = [m for m, _ in series]
    vals = [v for _, v in series]
    cur = vals[-1]
    out = {"month": months[-1], "wsi": round(cur, 1), "basis_since": months[0],
           "basis_months": len(series)}

    if len(vals) >= 2:
        out["prev_wsi"] = round(vals[-2], 1)
        out["delta"] = round(cur - vals[-2], 1)

    prior = list(zip(months[:-1], vals[:-1]))
    at_or_above = [m for m, v in prior if v >= cur]
    at_or_below = [m for m, v in prior if v <= cur]
    out["highest_since"] = at_or_above[-1] if at_or_above else "record"
    out["lowest_since"] = at_or_below[-1] if at_or_below else "record"

    streak = 0
    direction = 0
    for i in range(len(vals) - 1, 0, -1):
        d = vals[i] - vals[i - 1]
        step = 1 if d > 0 else (-1 if d < 0 else 0)
        if step == 0:
            break
        if direction == 0:
            direction = step
        if step != direction:
            break
        streak += 1
    out["run_length"] = streak
    out["run_direction"] = "up" if direction > 0 else ("down" if direction < 0 else "flat")
    return out


def advance_streaks(prev_streaks, levels):
    """Consecutive months at WATCH or ACT, ending at the current month."""
    out = {}
    for z, lv in levels.items():
        if lv in WARN:
            out[z] = prev_streaks.get(z, 0) + 1
    return out


# ————— history persistence —————

def load_history():
    p = RESEARCH_DIR / "history.json"
    if p.exists():
        return json.loads(p.read_text())
    return {"version": "1.0", "seam": SEAM_FALLBACK, "months": [], "sources": {},
            "national": {}, "states": {}, "metros": {}, "metro_names": {}}


def save_history(h):
    RESEARCH_DIR.mkdir(parents=True, exist_ok=True)
    (RESEARCH_DIR / "history.json").write_text(
        json.dumps(h, separators=(",", ":"), sort_keys=True))


def put_month(h, month, nat, st_c, cb_c, source, crosswalk):
    if month not in h["months"]:
        h["months"].append(month)
        h["months"].sort()
    h["sources"][month] = source
    pack = lambda c: [c["green"], c["yellow"], c["red"], c["strong"]]
    h["national"][month] = pack(nat)
    for st, c in st_c.items():
        h["states"].setdefault(st, {})[month] = pack(c)
    for cb, c in cb_c.items():
        h["metros"].setdefault(cb, {})[month] = pack(c)
    names = h["metro_names"]
    if cb_c:
        for z, (cb, title, is_metro) in crosswalk.items():
            if cb in cb_c and cb not in names:
                names[cb] = [title, 1 if is_metro else 0]


def unpack(a):
    return {"green": a[0], "yellow": a[1], "red": a[2], "strong": a[3]}


def national_series(h, segment=None):
    """[(month, wsi)]; segment="continuous" keeps months from the seam on."""
    out = []
    for m in h["months"]:
        if segment == "continuous" and m < h.get("seam", SEAM_FALLBACK):
            continue
        v = wsi_of(unpack(h["national"][m]))
        if v is not None:
            out.append((m, v))
    return out


# ————— per-zip level files (flip/streak base for the NEXT month) —————

def levels_path(month):
    return RESEARCH_DIR / f"levels-{month}.json"


def save_levels(month, levels):
    levels_path(month).write_text(
        json.dumps(levels, separators=(",", ":"), sort_keys=True))


def load_levels(month):
    p = levels_path(month)
    return json.loads(p.read_text()) if p.exists() else None


# ————— the per-month research file —————

MIN_METRO_SCORED = 15


def build_month_report(h, month, levels, states, crosswalk, places, streaks):
    prev = prev_month(month)
    rec = detect_records(national_series(h, segment="continuous"))
    nat = unpack(h["national"][month])

    def moves(space, names=None):
        rows = []
        for key, per_m in space.items():
            if month not in per_m or prev not in per_m:
                continue
            cur_s = region_share(unpack(per_m[month]))
            prev_s = region_share(unpack(per_m[prev]))
            if cur_s is None or prev_s is None:
                continue
            row = {"key": key, "share": round(cur_s, 1),
                   "delta": round(cur_s - prev_s, 1),
                   "scored": sum(unpack(per_m[month]).values())}
            if names is not None:
                nm = names.get(key)
                if not nm:
                    continue
                row["name"], row["is_metro"] = nm[0], bool(nm[1])
            rows.append(row)
        return rows

    state_moves = sorted(moves(h["states"]), key=lambda r: r["delta"])
    metro_moves = [r for r in moves(h["metros"], h["metro_names"])
                   if r["is_metro"] and r["scored"] >= MIN_METRO_SCORED]
    improving = sorted(metro_moves, key=lambda r: r["delta"])[:10]
    deteriorating = sorted(metro_moves, key=lambda r: -r["delta"])[:10]

    flips = []
    prev_levels = load_levels(prev)
    if prev_levels:
        for z, lv in levels.items():
            was = prev_levels.get(z)
            if was in ("green", "strong") and lv in WARN:
                city, st = places.get(z, ("", ""))
                flips.append({"zip": z, "city": city,
                              "state": states.get(z, st), "from": was, "to": lv})
        flips.sort(key=lambda r: (r["state"], r["zip"]))

    top_streaks = sorted(
        ({"zip": z, "months": n, "level": levels.get(z, ""),
          "city": places.get(z, ("", ""))[0], "state": states.get(z, "")}
         for z, n in streaks.items() if z in levels),
        key=lambda r: -r["months"])[:25]

    per_state = {}
    for st, per_m in sorted(h["states"].items()):
        if month not in per_m:
            continue
        c = unpack(per_m[month])
        entry = {"counts": c, "scored": sum(c.values()),
                 "share": round(region_share(c) or 0.0, 1)}
        if prev in per_m:
            entry["delta"] = round((region_share(c) or 0) -
                                   (region_share(unpack(per_m[prev])) or 0), 1)
        entry["flips_in"] = sum(1 for f in flips if f["state"] == st)
        per_state[st] = entry

    return {
        "month": month,
        "pretty_month": pretty(month),
        "index_version": h.get("version", "1.0"),
        "source": h["sources"].get(month, ""),
        "seam": h.get("seam", SEAM_FALLBACK),
        "national": {"counts": nat, "scored": sum(nat.values()),
                     "wsi": rec.get("wsi")},
        "records": rec,
        "state_moves": state_moves,
        "metros_deteriorating": deteriorating,
        "metros_improving": improving,
        "flips_to_warning": flips,
        "top_streaks": top_streaks,
        "states": per_state,
    }


# ————— source streaming (backfill) —————

def levels_by_month(source, label):
    """{month: {zip: level}}, {zip: ST} — the live engine over a source file,
    on the index's 4-signal definition. Row filters match the backtest."""
    months = defaultdict(dict)
    states = {}
    n = 0
    for row in load_rows(source):
        if (row.get("is_seasonally_adjusted") or "").strip().lower() == "true":
            continue
        pt = (row.get("property_type") or "").strip().lower()
        if pt and "all residential" not in pt:
            continue
        region = row.get("region", "")
        z = region.split(":")[-1].strip() if ":" in region else region.strip()
        if not (z.isdigit() and len(z) == 5):
            continue
        period = (row.get("period_end") or "")[:7]
        if len(period) != 7:
            continue
        st = (row.get("state_code") or "").strip().upper()[:2]
        lv = index_level(row_to_metrics(z, period, st, row))
        if lv is None:
            continue
        months[period][z] = lv
        states[z] = st
        n += 1
        if n % 500_000 == 0:
            print(f"  …{label}: {n:,} scored zip-months")
    return months, states


def cmd_backfill(args):
    crosswalk = load_crosswalk()
    places = load_places()

    print("streaming the hub file (v2, the continuous series)…")
    hub_m, hub_st = levels_by_month(args.hub, "hub")
    hub_months = sorted(hub_m)
    print(f"  hub: {len(hub_months)} months, {hub_months[0]} → {hub_months[-1]}")

    print("streaming the legacy tracker (v1, the context tail)…")
    trk_m, trk_st = levels_by_month(args.tracker, "tracker")
    trk_months = sorted(trk_m)
    print(f"  tracker: {len(trk_months)} months, {trk_months[0]} → {trk_months[-1]}")

    # Source agreement across the 84-month overlap — the number that says the
    # two segments may share one chart.
    overlap = [m for m in trk_months if m in hub_m]
    if overlap:
        tot = agr = 0
        for m in overlap:
            shared = trk_m[m].keys() & hub_m[m].keys()
            tot += len(shared)
            agr += sum(1 for z in shared if trk_m[m][z] == hub_m[m][z])
        print(f"  overlap: {len(overlap)} months, {tot:,} shared zip-months, "
              f"{100.0 * agr / tot:.2f}% level agreement")

    # Assemble: the seam is the first month the hub actually covers; the
    # tracker fills everything before it. Derived, not assumed — see SEAM_FALLBACK.
    seam = hub_months[0]
    h = {"version": "1.0", "seam": seam, "months": [], "sources": {},
         "national": {}, "states": {}, "metros": {}, "metro_names": {}}
    states = {**trk_st, **hub_st}

    # The CURRENT month comes from the site's own shards when they carry the
    # same period: the hub file is republished daily with revisions, so a
    # fresh download is not byte-identical to the one the last refresh used —
    # and the index must agree with the ZIP pages a reader can check.
    data_dir = Path(args.data)
    current_levels = None
    if (data_dir / "meta.json").exists():
        meta = json.loads((data_dir / "meta.json").read_text())
        if meta.get("period") == hub_months[-1]:
            current_levels, sh_states = load_shard_levels(data_dir)
            states.update(sh_states)
            a, b = counts_of(current_levels), counts_of(hub_m[hub_months[-1]])
            print(f"  current month {hub_months[-1]} from SHARDS "
                  f"(site truth) {a}; today's hub file reads {b} — "
                  f"drift is Redfin's daily republication, expected")

    streaks = {}
    all_months = sorted(set(m for m in trk_months if m < seam) |
                        set(m for m in hub_months if m >= seam))
    for m in all_months:
        if m == all_months[-1] and current_levels is not None:
            levels = current_levels
        else:
            levels = hub_m[m] if m >= seam else trk_m[m]
        source = "hub-v2" if m >= seam else "tracker-v1"
        nat, st_c, cb_c = aggregate(levels, states, crosswalk)
        put_month(h, m, nat, st_c, cb_c, source, crosswalk)
        streaks = advance_streaks(streaks, levels)

    current = all_months[-1]
    final_levels = current_levels if current_levels is not None else hub_m[current]
    save_history(h)
    save_levels(prev_month(current), hub_m.get(prev_month(current), {}))
    save_levels(current, final_levels)
    (RESEARCH_DIR / "streaks.json").write_text(
        json.dumps({"month": current, "warn": streaks},
                   separators=(",", ":"), sort_keys=True))

    report = build_month_report(h, current, final_levels, states,
                                crosswalk, places, streaks)
    (RESEARCH_DIR / f"research-{current}.json").write_text(
        json.dumps(report, indent=1, sort_keys=True))

    rec = report["records"]
    print(f"\nbackfill complete: {len(all_months)} months "
          f"({all_months[0]} → {current}); continuous series since {SEAM} "
          f"({rec.get('basis_months')} months)")
    print(f"  WSI {rec.get('wsi')}%  Δ {rec.get('delta')}  "
          f"highest_since {rec.get('highest_since')}  run {rec.get('run_length')} {rec.get('run_direction')}")


# ————— monthly (CI) —————

def cmd_monthly(args):
    crosswalk = load_crosswalk()
    places = load_places()
    data_dir = Path(args.data)
    meta = json.loads((data_dir / "meta.json").read_text())
    month = meta["period"]

    h = load_history()
    if not h["months"]:
        raise SystemExit("no history.json — run the one-time backfill first "
                         "(see docs/RESEARCH.md)")

    levels, states = load_shard_levels(data_dir)
    nat, st_c, cb_c = aggregate(levels, states, crosswalk)
    put_month(h, month, nat, st_c, cb_c, "hub-v2", crosswalk)

    sp = RESEARCH_DIR / "streaks.json"
    prev_s = json.loads(sp.read_text()) if sp.exists() else {"month": "", "warn": {}}
    if prev_s.get("month") == month:
        # Same-month rerun (manual dispatch): the streaks file ALREADY
        # advanced for this month — reuse it untouched. Advancing again
        # would double-count, and any attempt to "rebuild" from a bare
        # level map floors every long-running streak at one month: the
        # first version of this branch did exactly that, and a dispatch
        # would have silently rewritten an 89-month streak as 2 in the
        # committed artifacts. Idempotence here means KEEP, not recompute.
        streaks = prev_s.get("warn", {})
    else:
        streaks = advance_streaks(prev_s.get("warn", {}), levels)

    save_history(h)
    save_levels(month, levels)
    sp.write_text(json.dumps({"month": month, "warn": streaks},
                             separators=(",", ":"), sort_keys=True))

    report = build_month_report(h, month, levels, states, crosswalk, places, streaks)
    out = RESEARCH_DIR / f"research-{month}.json"
    out.write_text(json.dumps(report, indent=1, sort_keys=True))
    r = report["records"]
    print(f"research {month}: WSI {r.get('wsi')}% (Δ {r.get('delta', '—')}) "
          f"· flips {len(report['flips_to_warning'])} · wrote {out.name}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(HERE.parent / "web" / "data"))
    ap.add_argument("--backfill", action="store_true")
    ap.add_argument("--hub", help="hub all_zips.csv (v2) for --backfill")
    ap.add_argument("--tracker", help="legacy tracker tsv(.gz) for --backfill")
    args = ap.parse_args()
    if args.backfill:
        if not (args.hub and args.tracker):
            raise SystemExit("--backfill needs --hub PATH and --tracker PATH")
        cmd_backfill(args)
    else:
        cmd_monthly(args)


if __name__ == "__main__":
    main()
