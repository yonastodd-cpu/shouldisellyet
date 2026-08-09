#!/usr/bin/env python3
"""ShouldISellYet — approach velocity: how fast each market is moving toward
(or away from) its danger lines.

    python3 pipeline/velocity.py [--data web/data] [--out pipeline/velocity]

For every scored ZIP and each of the four signals, computes the 3-month rate
of change toward that signal's danger line, expressed as MONTHS-TO-LINE at the
current pace. Aggregates to metro (CBSA) and state, and ranks the "gathering
list": markets still HOLD whose signals are deteriorating fastest — the press
asset ("the warning signs are gathering in {metro}") and the paid report's
"how fast is your market moving?" section.

WHICH SIGNALS CAN RUN, AND WHY ONLY TWO TODAY (2026-08). A velocity needs
history:
  price trend (spy)   — derived from the 36-month price series (h.p) every
                        ZIP already carries: spy_t = p_t / p_{t-12} − 1.
  time to sell (dom)  — same construction from h.d.
  months of supply    — NO history exists anywhere before snapshot v2
  price-cut share       (2026-07+ records metrics; v1 recorded levels only),
                        so these two report `pending` with the month their
                        first velocity becomes possible. The engine treats
                        all four identically — as v2 snapshots accumulate,
                        mos and pd light up with NO code change.

HONESTY RULE (same one the masked preview lives by): a signal without enough
real history yields no number — never an approximation, never a proxy. The
pending state is shown as pending.

PAYWALL SHAPE. Per-ZIP velocity is the PAID product: it is upserted to the
`zip_velocity` table in Supabase (service-role only) and served exclusively
through verify-access. The committed velocity-{month}.json carries ONLY metro
and state aggregates and the gathering list — the public/press layer. Do not
add a per-ZIP section to the committed file: the repo is public, so anything
in it is one raw.githubusercontent URL away from being a free mirror of the
paid feature. (The INPUTS are public data; the paywall sells the computation
and presentation, exactly like the report itself.)

Persistence note: the brief said "persist to the archive"; archive/ is a
gitignored 90-day workflow artifact (see write_snapshot's comment), so these
go to pipeline/velocity/ in-repo instead — same durability reasoning.
"""

import argparse
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).parent))
from growth_digest import snap_level, snap_metrics  # v1/v2 snapshot readers

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = Path(__file__).parent / "snapshots"
OUT_DIR = Path(__file__).parent / "velocity"
CBSA_CSV = Path(__file__).parent / "data" / "zip_cbsa.csv"

# ————— The four signals —————
# line: the published danger line (same numbers as the site's gauges).
# hist: where history comes from — "h" (the 36-month series in web/data) or
#       "snap" (v2 snapshots, accumulating since 2026-07).
# Each signal's series is oriented so that RISING means approaching the line;
# spy is negated for this (falling prices approach the −2% line).
SIGNALS = {
    "spy": {"line": 0.02,  "hist": "h",    "label": "price trend"},        # −spy vs 0.02
    "dom": {"line": 0.40,  "hist": "h",    "label": "time to sell"},       # y/y ratio − 1
    "mos": {"line": 4.0,   "hist": "snap", "label": "months of supply"},
    "pd":  {"line": 0.35,  "hist": "snap", "label": "price cuts"},
}

SMOOTH_N = 3          # rolling-mean window on the input series
RATE_N = 3            # months across which the rate of change is measured
MTL_NEAR = 6.0        # months-to-line at/under this counts as "approaching"
MTL_CAP = 24.0        # beyond this, display as ">24 mo" and don't count it
LOW_VOLUME_SOLD = 12  # fewer monthly sales than this → velocity flagged noisy
MIN_SNAP_MONTHS = SMOOTH_N + RATE_N - 1   # 5 v2 snapshots before mos/pd run

# Gathering-state thresholds (plain-language mapping, adjustable):
#   deteriorating fast — score ≥ 1.5, or any signal ≤ 3 months from its line
#   drifting           — any signal approaching (mtl ≤ 12)
#   improving          — nothing approaching and ≥2 signals moving away
#   stable             — everything else
STATE_FAST_SCORE = 1.5
STATE_FAST_MTL = 3.0
STATE_DRIFT_MTL = 12.0


def rolling_mean(vals, n=SMOOTH_N):
    """Rolling mean, None-aware: a window with any gap yields None."""
    out = []
    for i in range(len(vals)):
        w = vals[max(0, i - n + 1): i + 1]
        out.append(None if (len(w) < n or any(v is None for v in w))
                   else sum(w) / n)
    return out


def months_to_line(series, line):
    """(mtl, direction, rate) from an oriented series and its line.

    series: chronological, RISING = approaching. Uses the last SMOOTH_N+RATE_N
    points: smooths, then rate = (smoothed_now − smoothed_{RATE_N ago})/RATE_N.
      crossed  — current smoothed value is at/past the line (mtl 0)
      toward   — rate > 0: mtl = distance / rate
      away     — rate ≤ 0: mtl None (∞)
    Returns (None, None, None) when history is insufficient.
    """
    sm = rolling_mean(series)
    if len(sm) < RATE_N + 1 or sm[-1] is None or sm[-1 - RATE_N] is None:
        return None, None, None
    cur, rate = sm[-1], (sm[-1] - sm[-1 - RATE_N]) / RATE_N
    if cur >= line:
        return 0.0, "crossed", rate
    if rate <= 0:
        return None, "away", rate
    return (line - cur) / rate, "toward", rate


def spy_series(h):
    """Oriented y/y price-trend series from h.p: −(p_t/p_{t−12} − 1)."""
    p = h.get("p") or []
    return [(-(p[i] / p[i - 12] - 1.0)) if (p[i] and p[i - 12]) else None
            for i in range(12, len(p))]


def dom_series(h):
    """Oriented y/y time-to-sell series from h.d: d_t/d_{t−12} − 1."""
    d = h.get("d") or []
    return [((d[i] / d[i - 12] - 1.0)) if (d[i] and d[i - 12]) else None
            for i in range(12, len(d))]


def snap_series(snaps, zip_, key):
    """Chronological metric series for one ZIP from v2 snapshots (v1 months
    contribute None — they carry no metrics)."""
    return [snap_metrics(s.get(zip_, "")) .get(key) for s in snaps]


def zip_velocity(entry, snaps_by_month):
    """Per-signal velocity for one ZIP entry. Returns (sig_dict, active)."""
    h = entry.get("h") or {}
    out = {}
    for key, cfg in SIGNALS.items():
        if cfg["hist"] == "h":
            series = spy_series(h) if key == "spy" else dom_series(h)
        else:
            series = snap_series(snaps_by_month, entry["_zip"], key)
            if sum(v is not None for v in series) < MIN_SNAP_MONTHS:
                out[key] = {"pending": True}
                continue
        mtl, direction, rate = months_to_line(series, cfg["line"])
        if direction is None:
            out[key] = {"pending": True}
            continue
        row = {"dir": direction, "rate": round(rate, 5)}
        if mtl is not None:
            row["mtl"] = round(min(mtl, MTL_CAP * 4), 1)   # sanity cap only
        out[key] = row
    return out


def gathering(sig):
    """(score, state) from a ZIP's per-signal velocity dict.

    score = Σ over signals with mtl ≤ MTL_NEAR of (1 + proximity), where
    proximity = (MTL_NEAR − mtl)/MTL_NEAR — a crossed signal contributes 2.
    """
    score, near, drifting, away, active = 0.0, 0, 0, 0, 0
    for row in sig.values():
        if row.get("pending"):
            continue
        active += 1
        mtl = row.get("mtl")
        if row["dir"] == "away":
            away += 1
        elif mtl is not None and mtl <= MTL_NEAR:
            near += 1
            score += 1 + (MTL_NEAR - mtl) / MTL_NEAR
        elif mtl is not None and mtl <= STATE_DRIFT_MTL:
            drifting += 1
    if active == 0:
        return 0.0, "unknown"
    if score >= STATE_FAST_SCORE or any(
            (r.get("mtl") is not None and r["mtl"] <= STATE_FAST_MTL)
            for r in sig.values() if not r.get("pending")):
        state = "deteriorating fast"
    elif near or drifting:
        state = "drifting"
    elif away >= 2:
        state = "improving"
    else:
        state = "stable"
    return round(score, 2), state


def load_entries(data_dir):
    out = {}
    for f in sorted(Path(data_dir, "zips").glob("*.json")):
        for z, e in json.loads(f.read_text()).items():
            e["_zip"], e["st"] = z, e.get("st") or f.stem
            out[z] = e
    return out


def load_cbsa():
    zc, names = {}, {}
    if CBSA_CSV.exists():
        for r in csv.DictReader(open(CBSA_CSV, encoding="utf-8")):
            zc[r["zip"]] = r["cbsa"]
            names[r["cbsa"]] = r["title"]
    return zc, names


def aggregate(rows, key_of, names=None, min_zips=5):
    """Metro/state rollup: share deteriorating, median months-to-line."""
    by = defaultdict(list)
    for z, r in rows.items():
        k = key_of(z, r)
        if k:
            by[k].append(r)
    out = {}
    for k, rs in by.items():
        if len(rs) < min_zips:
            continue
        det = [r for r in rs if r["state"] == "deteriorating fast"]
        drift = [r for r in rs if r["state"] == "drifting"]
        mtls = [min(v["mtl"] for v in r["sig"].values()
                    if not v.get("pending") and v.get("mtl") is not None)
                for r in rs
                if any(not v.get("pending") and v.get("mtl") is not None
                       for v in r["sig"].values())]
        # Per-signal texture for the admin "why" lines: how many of the
        # metro's ZIPs have this signal near its line, and the median mtl.
        sig_summary = {}
        for sk in SIGNALS:
            near_mtls = [v["mtl"] for r in rs
                         for v in [r["sig"].get(sk) or {}]
                         if not v.get("pending") and v.get("mtl") is not None
                         and v["mtl"] <= MTL_NEAR]
            if near_mtls:
                sig_summary[sk] = {"near": len(near_mtls),
                                   "median_mtl": round(median(near_mtls), 1)}
        out[k] = {
            "zips": len(rs),
            "deteriorating": len(det),
            "drifting": len(drift),
            "share_det": round(100 * (len(det) + len(drift)) / len(rs), 1),
            "median_mtl": round(median(mtls), 1) if mtls else None,
            "median_score": round(median(r["score"] for r in rs), 2),
            "hold_share": round(100 * sum(1 for r in rs if r["level"] in ("green", "strong")) / len(rs), 1),
            "sig": sig_summary,
        }
        if names:
            out[k]["name"] = names.get(k, k)
    return out


def gathering_list(metros, prev_metros, top=25):
    """Markets still mostly HOLD but deteriorating fastest, ranked by
    month-over-month change in median gathering score (falls back to level
    when no prior month exists)."""
    rows = []
    for cbsa, m in metros.items():
        if m["hold_share"] < 60:          # "still HOLD" — most ZIPs not flagged
            continue
        prev = (prev_metros or {}).get(cbsa) or {}
        delta = (m["median_score"] - prev["median_score"]) if prev.get("median_score") is not None else None
        rows.append(dict(m, cbsa=cbsa, score_delta=(round(delta, 2) if delta is not None else None)))
    rows.sort(key=lambda r: (-(r["score_delta"] if r["score_delta"] is not None else r["median_score"]),
                             -r["share_det"]))
    return rows[:top]


def build(period, entries, snaps_by_month, prev_aggregates=None):
    zc, cbsa_names = load_cbsa()
    zips = {}
    for z, e in entries.items():
        if any(r0[0] == "insufficient_data" for r0 in e.get("r", [])):
            continue
        sig = zip_velocity(e, snaps_by_month)
        score, state = gathering(sig)
        zips[z] = {
            "sig": sig, "score": score, "state": state,
            "level": e["l"], "st": e["st"],
            "low_volume": (e.get("m", {}).get("sold") or 0) < LOW_VOLUME_SOLD,
        }
    metros = aggregate(zips, lambda z, r: zc.get(z), cbsa_names, min_zips=5)
    states = aggregate(zips, lambda z, r: r["st"], min_zips=10)
    glist = gathering_list(metros, (prev_aggregates or {}).get("metros"))

    pending = {k: cfg["label"] for k, cfg in SIGNALS.items()
               if cfg["hist"] == "snap"
               and sum(1 for s in snaps_by_month
                       if any(snap_metrics(v) for v in list(s.values())[:1])) < MIN_SNAP_MONTHS}
    return {
        "period": period,
        "signals": {k: {"label": c["label"], "line": c["line"], "source": c["hist"]}
                    for k, c in SIGNALS.items()},
        "pending_signals": pending,
        "zips": zips,                      # stripped before commit — see main()
        "metros": metros,
        "states": states,
        "gathering": glist,
    }


def prev_period(p, k=1):
    y, m = int(p[:4]), int(p[5:7])
    m -= k
    while m <= 0:
        y, m = y - 1, m + 12
    return f"{y:04d}-{m:02d}"


def trimmed(entries, k):
    """Entries as they looked k months ago, by slicing each h series. Only the
    h-derived signals see history, so this is exact for spy/dom; snapshot
    signals are excluded from backfilled months (their history IS the
    snapshots, which don't reach back)."""
    out = {}
    for z, e in entries.items():
        h = e.get("h") or {}
        e2 = dict(e)
        e2["h"] = {"s": h.get("s"),
                   "p": (h.get("p") or [])[:-k] or None,
                   "d": (h.get("d") or [])[:-k] or None} if h else {}
        out[z] = e2
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "web" / "data"))
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--backfill", type=int, default=0,
                    help="also compute N prior months by trimming the h series "
                         "(max ~17 — beyond that the y/y+smoothing+rate chain "
                         "runs out of the 36-month window)")
    args = ap.parse_args()

    meta = json.loads(Path(args.data, "meta.json").read_text())
    period = meta.get("period", "")
    entries = load_entries(args.data)

    snaps = []
    for f in sorted(SNAP_DIR.glob("verdicts-*.json")):
        snaps.append(json.loads(f.read_text()))

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    prev_p = out_dir / "velocity-prev-aggregates.json"

    # Backfill oldest→newest so each month's MoM delta sees its predecessor.
    prev = None
    for k in range(args.backfill, 0, -1):
        bp = prev_period(period, k)
        r = build(bp, trimmed(entries, k), [], prev)
        pub = {kk: v for kk, v in r.items() if kk != "zips"}
        (out_dir / f"velocity-{bp}.json").write_text(
            json.dumps(pub, separators=(",", ":"), sort_keys=True))
        prev = {"metros": r["metros"]}
        print(f"  backfilled {bp}: {len(r['zips']):,} ZIPs, {len(r['metros'])} metros")

    if prev is None and prev_p.exists():
        prev = json.loads(prev_p.read_text())

    result = build(period, entries, snaps, prev)

    # Surge flag: a metro entering the gathering top-10 for the first time in
    # 6 months. Judged against this run's own history files, which the
    # backfill seeded 13 months deep.
    recent = set()
    for k in range(1, 7):
        f = out_dir / f"velocity-{prev_period(period, k)}.json"
        if f.exists():
            j = json.loads(f.read_text())
            recent |= {g.get("cbsa") for g in (j.get("gathering") or [])[:10]}
    for i, g in enumerate(result["gathering"]):
        g["surge"] = i < 10 and g["cbsa"] not in recent

    # Committed artifact: aggregates + gathering list ONLY (see header).
    public = {k: v for k, v in result.items() if k != "zips"}
    (out_dir / f"velocity-{period}.json").write_text(
        json.dumps(public, separators=(",", ":"), sort_keys=True))

    # Web-served aggregates for the admin dashboard (web/data commits on every
    # refresh). Same public layer as the research page, plus each gathering
    # metro's member-ZIP list so admin can join activity (zip_check events) to
    # metros client-side. Aggregates only — the per-ZIP paid layer never
    # touches web/.
    zc, _ = load_cbsa()
    members = defaultdict(list)
    for z, r in result["zips"].items():
        c = zc.get(z)
        if c:
            members[c].append(z)
    web_gathering = [dict(g, member_zips=sorted(members.get(g["cbsa"], [])))
                     for g in result["gathering"]]
    (ROOT / "web" / "data" / "velocity-aggregates.json").write_text(json.dumps(
        {"period": period, "pending_signals": result["pending_signals"],
         "signals": result["signals"], "gathering": web_gathering,
         "states": result["states"]},
        separators=(",", ":"), sort_keys=True))
    # Rolling prev-month aggregate cache for MoM deltas.
    prev_p.write_text(json.dumps({"metros": result["metros"]}, separators=(",", ":")))

    # Per-ZIP payloads → stdout consumer (upsert_velocity.py) or file for
    # inspection; NEVER into the committed public JSON.
    (out_dir / "zip-velocity-latest.json").write_text(
        json.dumps({"period": period, "zips": result["zips"]},
                   separators=(",", ":")))

    act = [k for k, c in SIGNALS.items()
           if c["hist"] == "h" or k not in result["pending_signals"]]
    det = sum(1 for r in result["zips"].values() if r["state"] == "deteriorating fast")
    print(f"velocity {period}: {len(result['zips']):,} ZIPs · active signals {act} · "
          f"pending {list(result['pending_signals'])} · deteriorating-fast {det:,} · "
          f"{len(result['metros'])} metros · gathering top {len(result['gathering'])}")


if __name__ == "__main__":
    main()
