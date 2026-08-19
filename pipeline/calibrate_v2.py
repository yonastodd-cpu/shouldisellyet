#!/usr/bin/env python3
"""Calibrate and sanity-check verdict_v2 against a baseline distribution.

    python3 pipeline/calibrate_v2.py                    # committed Redfin data
    python3 pipeline/calibrate_v2.py --archive archive/rentcast   # real data

TWO MODES, AND THEY ANSWER DIFFERENT QUESTIONS.

  proxy mode (default) reads web/data/zips and feeds v2 the three surviving
  metrics as Redfin measured them. Those are not RentCast numbers, but they
  are the same KIND of number — all three surviving checks are year-over-year
  ratios, which is precisely why they survived — so this establishes the
  shape of the reading before a single request is bought. It is how the v2
  bands were set.

  archive mode reads stored RentCast responses and runs the real thing. This
  is the run that retires SPEC["provisional"], and it costs nothing because
  Lever 2 already put the payloads on disk.

WHAT THE COMPARISON IS FOR. The plan's test is "if most of the country flips
category, the thresholds are wrong, not the country." It is a smoke alarm,
not a target. Fitting thresholds until the pre-migration distribution
reappeared would manufacture confidence the data no longer supports — the
engine really did lose two of five danger signals, and a somewhat quieter
engine is the honest result. What must NOT happen is a silent collapse, and
--compare-naive shows exactly that failure for reference.
"""

import argparse
import collections
import glob
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import verdict as v1
import verdict_v2 as v2

ROOT = Path(__file__).resolve().parents[1]
ZIPS = ROOT / "web" / "data" / "zips"
LEVELS = ("green", "yellow", "red", "strong")


def load_entries(zips=ZIPS):
    out = {}
    for f in sorted(Path(zips).glob("*.json")):
        out.update(json.loads(f.read_text()))
    return out


def v1_metrics(z, e, drop_lost=False):
    """v1 inputs. drop_lost simulates the migration: the two signals RentCast
    cannot supply are set to None, leaving v1's own logic otherwise intact."""
    m = e.get("m", {})
    return v1.ZipMetrics(
        zip_code=z,
        months_of_supply=None if drop_lost else m.get("mos"),
        median_sale_price_yoy=m.get("spy"),
        price_drop_share=None if drop_lost else m.get("pd"),
        median_dom=m.get("dom"), median_dom_yoy=m.get("domy"),
        inventory_yoy=m.get("invy"))


def proxy_market(z, e):
    """v2 inputs from committed data. Redfin ships DOM YoY as an absolute
    change in DAYS, so it is converted to the fraction v2 expects — the
    conversion v2 will never need again once RentCast history supplies the
    level for each month directly."""
    m = e.get("m", {})
    dom, domy = m.get("dom"), m.get("domy")
    dom_frac = None
    if dom is not None and domy is not None:
        prior = dom - domy
        if prior > 0:
            dom_frac = domy / prior
    return v2.MarketV2(zip_code=z, list_price_yoy=m.get("spy"),
                       active_dom=dom, active_dom_yoy=dom_frac,
                       listings_yoy=m.get("invy"), total_listings=m.get("inv"))


def archive_markets(raw_dir):
    """Stored RentCast responses → MarketV2, via the same parser the loader
    uses. No network, no quota."""
    from fetch_rentcast import parse_market
    out = []
    for f in sorted(Path(raw_dir).glob("*.json")):
        payload = json.loads(f.read_text())
        parsed = parse_market(payload)
        hist = ((payload or {}).get("saleData") or {}).get("history") or {}
        out.append(v2.from_market_stats(parsed, hist))
    return out


def distribution(verdicts):
    c = collections.Counter(v.level for v in verdicts)
    tot = sum(c.values()) or 1
    return {k: c[k] / tot for k in LEVELS}, c, tot


def show(label, dist, counts, tot, baseline=None):
    print(f"\n{label}  (n={tot:,})")
    for k in LEVELS:
        drift = ""
        if baseline:
            d = (dist[k] - baseline[k]) * 100      # points, not fractions
            drift = f"   {d:+5.1f} pts" if abs(d) >= 0.05 else "       ="
        print(f"  {k:7} {counts[k]:7,}  {dist[k]:6.1%}{drift}")
    print(f"  ACT total (red+strong): {dist['red'] + dist['strong']:.1%}")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Calibrate verdict_v2")
    ap.add_argument("--zips", default=str(ZIPS))
    ap.add_argument("--archive", help="stored RentCast responses (real data mode)")
    ap.add_argument("--compare-naive", action="store_true",
                    help="also show v1's bands with the lost signals removed")
    args = ap.parse_args(argv)

    entries = load_entries(args.zips)
    base_dist, base_counts, base_tot = distribution(
        [v1.evaluate(v1_metrics(z, e)) for z, e in entries.items()])
    show("BASELINE — v1 on Redfin data, all five signals", base_dist, base_counts, base_tot)

    if args.compare_naive:
        d, c, t = distribution(
            [v1.evaluate(v1_metrics(z, e, drop_lost=True)) for z, e in entries.items()])
        show("NAIVE PORT — v1 bands, two signals removed (the failure case)",
             d, c, t, base_dist)
        print("  ^ this is what 'the thresholds are wrong, not the country' "
              "looks like: ACT collapses and no ZIP can reach a strong reading,\n"
              "    because that path needed 3 of 4 signals and only 2 survive.")

    if args.archive:
        markets = archive_markets(args.archive)
        if not markets:
            raise SystemExit(f"No stored responses under {args.archive} — "
                             f"run the acquisition first, or drop --archive "
                             f"to calibrate on the committed proxy data.")
        d, c, t = distribution([v2.evaluate(m) for m in markets])
        show("v2 on REAL RentCast data", d, c, t, base_dist)
        print(f"\n  Coverage note: {t:,} ZIPs, versus {base_tot:,} in the "
              f"baseline. A tier-limited archive is not a national sample, so "
              f"compare shapes rather than levels until every tier has landed.")
    else:
        d, c, t = distribution([v2.evaluate(proxy_market(z, e))
                                for z, e in entries.items()])
        show("v2 (proxy) — v2 engine, Redfin values for the three survivors",
             d, c, t, base_dist)

    print(f"\nspec: {v2.SPEC['version']} · basis {v2.SPEC['basis']} · "
          f"provisional={v2.SPEC['provisional']}")
    if v2.SPEC["provisional"] and not args.archive:
        print("Thresholds remain PROVISIONAL. Retiring that flag requires a "
              "run with --archive against real responses.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
