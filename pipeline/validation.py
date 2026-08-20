#!/usr/bin/env python3
"""ShouldISellYet — forward validation: measured accuracy, not promises.

    python3 pipeline/validation.py [--data web/data]

Monthly job. Scores the verdicts we published N months ago against what
prices actually did since — the number the methodology page can cite as
MEASURED. Metrics per run (thresholds are constants below):

  recall       of ZIPs whose 12-mo price change came in at or below −5%,
               the share that carried WATCH/ACT in the snapshot 12 months
               prior (the flag therefore led the decline by ≥12 months —
               comfortably clearing the ≥3-month lead the claim needs)
  precision    of ZIPs flagged 12 months ago, the share whose price change
               since was at or below −2%
  false_quiet  ZIPs that declined ≥5% while flagged HOLD 12 months ago
  lead_days    median (first-flag date → first negative y/y print) — needs a
               run of consecutive monthly snapshots and is reported only when
               ≥6 exist; absent until then, never approximated
  (6-month variants of recall/precision ride along where a 6-mo-old
  snapshot exists)

HISTORY GATE. Verdict snapshots begin 2026-05, so the first 12-month
validation is possible in 2027-05. Until then this job writes the honest
state — {"collecting": true, "first_validation": "2027-05"} — and every
renderer shows "collecting" rather than partial numbers.

Outputs: pipeline/validation/validation-{month}.json (committed history)
and web/data/validation.json (the latest, for the admin Accuracy card and
the methodology page's public block).
"""

import argparse
import json
import sys
from pathlib import Path
from statistics import median

sys.path.insert(0, str(Path(__file__).parent))
from shard_layout import require_shards
from growth_digest import snap_level

ROOT = Path(__file__).resolve().parents[1]
SNAP_DIR = Path(__file__).parent / "snapshots"
OUT_DIR = Path(__file__).parent / "validation"

DECLINE_MAJOR = -0.05      # "a real decline" — recall's bar
DECLINE_PRECISION = -0.02  # "the flag was right" — precision's bar
FLAGGED = {"yellow", "red"}
QUIET = {"green", "strong"}
MIN_LEAD_SNAPS = 6         # consecutive snapshots before lead-time is reported


def month_shift(period, k):
    """period minus k months; negative k shifts forward (and must normalize
    upward too — the first version returned '2026-17' for k=-12)."""
    y, m = int(period[:4]), int(period[5:7])
    m -= k
    while m <= 0:
        y, m = y - 1, m + 12
    while m > 12:
        y, m = y + 1, m - 12
    return f"{y:04d}-{m:02d}"


def price_change(h, months):
    """Realized price change over the trailing `months` from the h series."""
    p = (h or {}).get("p") or []
    if len(p) < months + 1 or p[-1] is None or p[-1 - months] is None:
        return None
    return p[-1] / p[-1 - months] - 1


def score(snapshot, entries, months):
    """Verdicts from `snapshot` (taken `months` ago) vs realized price change."""
    n_scored = n_declined = n_caught = n_flagged = n_flagged_right = n_false_quiet = 0
    for z, e in entries.items():
        was = snap_level(snapshot.get(z))
        if was is None:
            continue
        chg = price_change(e.get("h"), months)
        if chg is None:
            continue
        n_scored += 1
        declined = chg <= DECLINE_MAJOR
        flagged = was in FLAGGED
        if declined:
            n_declined += 1
            if flagged:
                n_caught += 1
            elif was in QUIET:
                n_false_quiet += 1
        if flagged:
            n_flagged += 1
            if chg <= DECLINE_PRECISION:
                n_flagged_right += 1
    return {
        "months": months,
        "zips_scored": n_scored,
        "declined": n_declined,
        "recall": round(n_caught / n_declined, 3) if n_declined else None,
        "precision": round(n_flagged_right / n_flagged, 3) if n_flagged else None,
        "flagged": n_flagged,
        "false_quiet": n_false_quiet,
    }


def lead_times(snaps_by_month, entries):
    """Median months between a ZIP's FIRST flag and its first negative y/y
    print at or after it. Only run with ≥MIN_LEAD_SNAPS consecutive months."""
    months = sorted(snaps_by_month)
    if len(months) < MIN_LEAD_SNAPS:
        return None
    leads = []
    for z, e in entries.items():
        first_flag = next((i for i, mn in enumerate(months)
                           if snap_level(snaps_by_month[mn].get(z)) in FLAGGED), None)
        if first_flag is None or first_flag == 0:
            continue   # unflagged, or already flagged at history start (left-censored)
        p = (e.get("h") or {}).get("p") or []
        # y/y series aligned to snapshot months: last len(months) entries
        yy = [(p[i] / p[i - 12] - 1) if (i >= 12 and p[i] and p[i - 12]) else None
              for i in range(len(p))]
        tail = yy[-len(months):] if len(yy) >= len(months) else []
        first_neg = next((i for i, v in enumerate(tail)
                          if i >= first_flag and v is not None and v < 0), None)
        if first_neg is not None:
            leads.append((first_neg - first_flag) * 30)   # months → ~days
    return round(median(leads)) if leads else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "web" / "data"))
    args = ap.parse_args()

    meta = json.loads(Path(args.data, "meta.json").read_text())
    period = meta.get("period", "")

    snaps = {f.stem.replace("verdicts-", ""): json.loads(f.read_text())
             for f in sorted(SNAP_DIR.glob("verdicts-*.json"))}
    first_snap = min(snaps) if snaps else None

    out = {"period": period,
           "thresholds": {"decline_major": DECLINE_MAJOR,
                          "decline_precision": DECLINE_PRECISION},
           "snapshot_months": len(snaps), "first_snapshot": first_snap}

    want12, want6 = month_shift(period, 12), month_shift(period, 6)
    if want12 not in snaps:
        # The honest state, rendered as such everywhere downstream.
        out["collecting"] = True
        out["first_validation"] = month_shift(first_snap, -12) if first_snap else None
        print(f"validation {period}: collecting — first 12-mo validation "
              f"{out['first_validation']} (snapshots since {first_snap})")
    else:
        entries = {}
        require_shards(Path(args.data, "zips"), "validation",
                       "the withdrawn per-ZIP metric block it scores against")
        for f in sorted(Path(args.data, "zips").glob("*.json")):
            entries.update(json.loads(f.read_text()))
        out["v12"] = score(snaps[want12], entries, 12)
        if want6 in snaps:
            out["v6"] = score(snaps[want6], entries, 6)
        out["lead_days_median"] = lead_times(snaps, entries)
        v = out["v12"]
        print(f"validation {period}: 12-mo recall {v['recall']} · precision "
              f"{v['precision']} · false-quiet {v['false_quiet']} of {v['declined']} decliners")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"validation-{period}.json").write_text(
        json.dumps(out, separators=(",", ":"), sort_keys=True))
    (ROOT / "web" / "data" / "validation.json").write_text(
        json.dumps(out, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
