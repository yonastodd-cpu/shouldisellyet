#!/usr/bin/env python3
"""ShouldISellYet — track-record recomputation.

    python3 tools/backtest_cases.py [--config tools/cases.yml]
                                    [--housing URL|PATH] [--drops URL|PATH]
                                    [--out web/data/cases] [--cache DIR]

THE GOVERNING RULE, IN CODE. No case publishes unless it REPRODUCES. Every
date, value and lead time this emits comes from running TODAY'S dial
definitions (pipeline/verdict.py evaluate/_checks) and TODAY'S danger lines
over historical source rows — the same two Redfin hub files the live site
reads each refresh. Nothing here is quoted from memory, press, or a prior
run. A candidate that does not produce a crossing followed by a real decline
is DROPPED, with the reason recorded in the run report. Thresholds are never
relaxed to rescue a story; the only way a case changes is if the source data
or the thresholds change, which is the point.

VERIFIABLE WINDOW: 2019-04 → 2026-06. Both hub files carry monthly history to
2019-04, so all FOUR dials recompute at full fidelity. Nothing earlier is
recomputable at dial level from any source this project has, which is why
cases.yml carries no pre-2019 case (see its comment on 2005-2009).

WHY A SEPARATE TOOL AND NOT pipeline/: this reads ~1GB of source and runs on
demand for a marketing artifact, not on the twice-weekly refresh path. It
writes web/data/cases/*.json (committed, small) which the site renders.

METRO = ITS ZIPs. There is no metro-level Redfin file; every URL is ZIP-level.
A metro's dials are the median across its scored ZIPs and its verdict mix is
the count at each level — which matches how the site actually works (per-ZIP
verdicts), so a metro card says "N of M ZIPs crossed", never a fictional
metro-wide verdict.
"""

import argparse
import csv
import gzip
import io
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))
from verdict import ZipMetrics, evaluate            # today's thresholds, verbatim
# Same verifying-SSL helper the pipeline uses — stock macOS pythons ship no
# CA bundle, and verification is never disabled to work around that.
from fetch_data import _ssl_context

HOUSING_URL = ("https://redfin-public-data.s3.us-west-2.amazonaws.com/"
               "redfin_data_center/housing_market/monthly/all_zips.csv")
DROPS_URL = ("https://redfin-public-data.s3.us-west-2.amazonaws.com/"
             "redfin_data_center/price_drops/monthly/all_zips.csv")
CBSA_CSV = ROOT / "pipeline" / "data" / "zip_cbsa.csv"

FLAGGED = {"yellow", "red"}


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fetch_to_cache(url, cache_dir):
    """Download once, reuse forever. The raw sources are ~1GB combined, and
    this tool must be re-runnable cheaply: the acceptance test tweaks a
    threshold and re-runs to prove the outputs move, and miss metros need a
    second pass for their dials once the data has nominated them."""
    if not str(url).startswith("http"):
        return url
    cache_dir.mkdir(parents=True, exist_ok=True)
    dest = cache_dir / (url.rsplit("/", 3)[1] + "_" + url.rsplit("/", 1)[-1])
    if dest.exists() and dest.stat().st_size > 1_000_000:
        print(f"  cached: {dest.name} ({dest.stat().st_size/1e6:.0f} MB)")
        return dest
    print(f"  downloading {dest.name} …")
    req = urllib.request.Request(url, headers={"User-Agent": "shouldisellyet-trackrecord"})
    with urllib.request.urlopen(req, timeout=900, context=_ssl_context()) as r, open(dest, "wb") as f:
        while True:
            chunk = r.read(1 << 22)
            if not chunk:
                break
            f.write(chunk)
    print(f"  saved {dest.name} ({dest.stat().st_size/1e6:.0f} MB)")
    return dest


def open_source(src):
    """Stream a local path or URL, gz-aware, yielding csv.DictReader rows."""
    if str(src).startswith("http"):
        req = urllib.request.Request(src, headers={"User-Agent": "shouldisellyet-trackrecord"})
        fh = urllib.request.urlopen(req, timeout=600, context=_ssl_context())
    else:
        fh = open(src, "rb")
    if str(src).endswith(".gz"):
        fh = gzip.GzipFile(fileobj=fh)
    return csv.DictReader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))


def stream_drops(src):
    """{zip: {month: price_drop_share}} — the fourth dial, its own file.

    Held in full because the verdict for ANY zip-month needs it, and the
    false-alarm query scans every metro. ~2.8M values; the compact-by-design
    housing pass below is what keeps total memory sane.
    """
    out = defaultdict(dict)
    for row in open_source(src):
        if row.get("REGION TYPE") != "Zip":
            continue
        z = (row.get("REGION NAME") or "").strip().zfill(5)
        end = (row.get("PERIOD END") or "")[:7]
        # "PRICE DROPS" is a COUNT; the verdict wants the SHARE of active
        # listings with a cut — the same column load_price_drops() reads.
        v = _f(row.get("PERCENT ACTIVE WITH PRICE DROPS (%)"))
        if end and v is not None:
            out[z][end] = v / 100.0                    # true percent → fraction
    return out


def stream_housing(src, drops, case_zips):
    """One pass, two outputs, deliberately asymmetric:

      detail  — FULL dials, only for ZIPs inside a configured case. Small.
      compact — (level, price) for EVERY zip-month, because the false-alarm
                query has to scan the whole country. Verdicts are computed
                inline during the stream rather than stored as dials, which
                is the difference between ~170MB and ~900MB of Python objects.
    """
    detail = defaultdict(dict)
    compact = defaultdict(dict)
    for row in open_source(src):
        if row.get("REGION TYPE") != "Zip":
            continue
        z = (row.get("REGION NAME") or "").strip().zfill(5)
        end = (row.get("PERIOD END") or "")[:7]
        if not end:
            continue
        pct = lambda k: (lambda v: v / 100 if v is not None else None)(_f(row.get(k)))
        d = {
            "mos": _f(row.get("MONTHS OF SUPPLY")),
            "price": _f(row.get("MEDIAN SALE PRICE NSA ($)")),
            "spy": pct("MEDIAN SALE PRICE NSA YOY (%)"),
            "dom": _f(row.get("MEDIAN DAYS ON MARKET (DAYS)")),
            # Labeled "(%)" but holds Δdays × 100, so ÷100 yields absolute
            # DAYS — which is what verdict.py documents and consumes. Do not
            # read this as a fraction (see _V2_MAP's "days" transform).
            "domy": pct("MEDIAN DAYS ON MARKET YOY (%)"),
            "invy": pct("INVENTORY YOY (%)"),          # matches _V2_MAP
            "inv": _f(row.get("INVENTORY")),
            "sold": _f(row.get("HOMES SOLD")),
        }
        lvl, _reasons, insufficient = verdict_for(z, end, d, drops.get(z, {}).get(end))
        compact[z][end] = (None if insufficient else lvl, d["price"])
        if z in case_zips:
            d["pd"] = drops.get(z, {}).get(end)
            d["level"] = None if insufficient else lvl
            detail[z][end] = d
    return detail, compact


def verdict_for(z, month, d, drop_share):
    """Today's verdict logic, on a historical month's dials."""
    m = ZipMetrics(
        zip_code=z, period=month,
        months_of_supply=d.get("mos"),
        median_sale_price_yoy=d.get("spy"),
        price_drop_share=drop_share,
        median_dom=d.get("dom"),
        median_dom_yoy=d.get("domy"),
        inventory_yoy=d.get("invy"),
        inventory=d.get("inv"),
        homes_sold=d.get("sold"),
    )
    v = evaluate(m)
    insufficient = any(r[0] == "insufficient_data" for r in v.reasons)
    return v.level, [r[0] for r in v.reasons], insufficient


def load_cbsa_zips():
    by = defaultdict(set)
    names = {}
    for r in csv.DictReader(open(CBSA_CSV, encoding="utf-8")):
        by[r["cbsa"]].add(r["zip"])
        names[r["cbsa"]] = r["title"]
    return by, names


def months_between(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + (int(b[5:7]) - int(a[5:7]))


def build_case(case, housing, drops, zips, months):
    """Recompute one case. Returns the case dict, or a drop reason."""
    win_a, win_b = case["window"]
    out_a, out_b = case["outcome"]
    scan = [m for m in months if win_a <= m <= win_b]
    span = [m for m in months if out_a <= m <= out_b]
    if not scan:
        return None, "no source months inside the analysis window"

    # Per-month metro rollup: verdict mix, median dials, median price.
    series = []
    for mo in span:
        levels, dials, prices = [], defaultdict(list), []
        for z in zips:
            d = housing.get(z, {}).get(mo)
            if not d:
                continue
            lvl, _, insufficient = verdict_for(z, mo, d, drops.get(z, {}).get(mo))
            if insufficient:
                continue
            levels.append(lvl)
            for k in ("mos", "spy", "dom", "domy", "pd"):
                v = drops.get(z, {}).get(mo) if k == "pd" else d.get(k)
                if v is not None:
                    dials[k].append(v)
            # The dial the verdict actually tests for time-to-sell.
            if d.get("dom") is not None and d.get("domy") is not None:
                prior = d["dom"] - d["domy"]
                if prior > 0:
                    dials["dom_stretch"].append(d["domy"] / prior)
            if d.get("price"):
                prices.append(d["price"])
        if not levels:
            continue
        series.append({
            "month": mo,
            "scored": len(levels),
            "flagged": sum(1 for l in levels if l in FLAGGED),
            "act": sum(1 for l in levels if l == "red"),
            "share_flagged": round(100 * sum(1 for l in levels if l in FLAGGED) / len(levels), 1),
            "share_act": round(100 * sum(1 for l in levels if l == "red") / len(levels), 1),
            "dials": {k: round(median(v), 4) for k, v in dials.items() if v},
            "price": round(median(prices)) if prices else None,
        })
    if len(series) < 12:
        return None, f"only {len(series)} scored months in the outcome window"

    by_month = {s["month"]: s for s in series}

    # First crossing per dial: the first scanned month where the MEDIAN ZIP in
    # the metro is past that dial's published danger line. Median, not any-ZIP:
    # one outlier ZIP is not a market turning.
    # Danger lines, in the SAME units verdict.py compares. "dom_stretch" is
    # the derived fraction domy/(dom−domy) — comparing raw Δdays to 0.40
    # would call a 1.5-day move a crossing, which is how an early bogus
    # Austin "crossing" first appeared.
    lines = {"mos": (4.0, "gt"), "spy": (-0.02, "lt"),
             "dom_stretch": (0.40, "gt"), "pd": (0.35, "gt")}
    # A CROSSING MUST PERSIST — 3 consecutive months past the line, dated to
    # the first of them. This is not a softened threshold (the line values are
    # untouched); it rejects one-month prints that are noise. Austin proved
    # why: its time-to-sell dial popped to +0.47 for exactly one month in
    # 2021-05 against a COVID-lockdown year-ago base, then reverted for a
    # year. Dating the case there would have claimed a 20-month lead the
    # signals did not actually give. The site's own velocity layer smooths
    # over 3 months for the same reason.
    PERSIST = 3
    crossings = {}
    for k, (line, op) in lines.items():
        run = []
        for mo in scan:
            s = by_month.get(mo)
            v = s["dials"].get(k) if s else None
            past = v is not None and ((v > line) if op == "gt" else (v < line))
            run = run + [(mo, v)] if past else []
            if len(run) >= PERSIST:
                crossings[k] = {"month": run[0][0], "value": run[0][1],
                                "line": line, "persisted": PERSIST}
                break

    # First month a MAJORITY of scored ZIPs carried WATCH-or-worse, and the
    # first where ≥25% carried ACT — the metro-scale analogue of one ZIP's
    # WATCH/ACT, stated as counts so nothing fictional is implied.
    # Same discipline for the metro-wide states: a majority for one month is
    # a print, not a turn.
    def _sustained(pred):
        run = 0
        for s in series:
            if s["month"] not in scan:
                continue
            run = run + 1 if pred(s) else 0
            if run >= PERSIST:
                return series[series.index(s) - PERSIST + 1]["month"]
        return None

    first_watch = _sustained(lambda s: s["share_flagged"] >= 50)
    # ACT-equivalent for a metro: a quarter of its scored ZIPs at red. The
    # placeholder that first stood here was nonsense arithmetic that could
    # never be true — caught before any case was published from it.
    first_act = _sustained(lambda s: s["share_act"] >= 25)

    # Price path after the first signal of any kind.
    first_signal = min([c["month"] for c in crossings.values()] +
                       ([first_watch] if first_watch else []), default=None)
    if not first_signal:
        return None, "no dial crossed its danger line inside the window"

    prices = [(s["month"], s["price"]) for s in series if s["price"]]
    if not prices:
        return None, "no median price series"
    # Peak = the window's highest median price; trough = the lowest AFTER it.
    # The first version measured the peak BEFORE the first signal, which for a
    # market that kept climbing after the crossing reported a 0.0% decline for
    # Austin against an actual −25.6%.
    peak_month, peak = max(prices, key=lambda t: t[1])
    after = [(m, p) for m, p in prices if m >= peak_month]
    trough_month, trough = min(after, key=lambda t: t[1]) if after else (None, None)
    ptt = (trough / peak - 1) if (peak and trough) else None

    # Lead time: first crossing → first negative y/y print for the metro.
    first_neg = next((s["month"] for s in series
                      if s["month"] >= first_signal
                      and s["dials"].get("spy") is not None
                      and s["dials"]["spy"] < 0), None)
    lead = months_between(first_signal, first_neg) if first_neg else None

    return {
        "id": case["id"], "name": case["name"], "story": case.get("story", ""),
        "cbsa": case.get("cbsa"), "zips_in_metro": len(zips),
        "window": case["window"], "outcome": case["outcome"],
        "crossings": crossings,
        "first_signal": first_signal,
        "first_watch_majority": first_watch,
        "first_act_quarter": first_act,
        "first_negative_yoy": first_neg,
        "lead_months": lead,
        "peak_price": peak, "peak_month": peak_month,
        "trough_price": trough, "trough_month": trough_month,
        "peak_to_trough": round(ptt, 4) if ptt is not None else None,
        "series": series,
        "computed_from": "pipeline/verdict.py evaluate() — today's danger lines",
    }, None


def nominate_false_alarms(cfg, compact, months, cbsa_zips, cbsa_names, exclude):
    """Let the DATA pick the misses: metros that crossed into WATCH majority in
    the given year and then never declined meaningfully. Hand-picking the miss
    would defeat the purpose of showing one."""
    year = str(cfg["crossed_in_year"])
    max_decline, recover_within = cfg["max_decline"], cfg["recover_within"]
    horizon, want = cfg["outcome_months"], cfg["nominate"]
    scan = [m for m in months if m.startswith(year)]
    cands = []
    for cbsa, zips in cbsa_zips.items():
        if cbsa in exclude or len(zips) < 15:
            continue
        rows = []
        for mo in months:
            levels, prices = [], []
            for z in zips:
                cell = compact.get(z, {}).get(mo)
                if not cell:
                    continue
                lvl, price = cell
                if lvl is None:          # insufficient data that month
                    continue
                levels.append(lvl)
                if price:
                    prices.append(price)
            if levels:
                rows.append((mo, 100 * sum(1 for l in levels if l in FLAGGED) / len(levels),
                             median(prices) if prices else None, len(levels)))
        if len(rows) < 24:
            continue
        cross = next((r for r in rows if r[0] in scan and r[1] >= 50), None)
        if not cross:
            continue
        idx = rows.index(cross)
        after = [r for r in rows[idx:idx + horizon] if r[2]]
        if len(after) < 12:
            continue
        base = cross[2]
        if not base:
            continue
        worst = min((r[2] / base - 1) for r in after)
        last = after[-1][2] / base - 1
        if worst > max_decline and last > recover_within:
            cands.append({"cbsa": cbsa, "name": cbsa_names.get(cbsa, cbsa),
                          "crossed": cross[0], "zips": cross[3],
                          "worst_drawdown": round(worst, 4),
                          "recovered_to": round(last, 4)})
    # Deepest scare that still didn't materialise makes the most honest miss.
    cands.sort(key=lambda c: c["worst_drawdown"])
    return cands[:want]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "tools" / "cases.yml"))
    ap.add_argument("--housing", default=HOUSING_URL)
    ap.add_argument("--drops", default=DROPS_URL)
    ap.add_argument("--out", default=str(ROOT / "web" / "data" / "cases"))
    ap.add_argument("--cache", default="", help="dir to cache parsed sources (dev)")
    ap.add_argument("--threshold-probe", action="store_true",
                    help="print the dial medians around each crossing so a "
                         "threshold change can be seen to move the output")
    args = ap.parse_args()

    import yaml
    cfg = yaml.safe_load(open(args.config))
    cbsa_zips, cbsa_names = load_cbsa_zips()

    case_cbsas = [c["cbsa"] for c in cfg["cases"] if c.get("cbsa")]
    case_zips = set()
    for c in cfg["cases"]:
        case_zips |= cbsa_zips.get(c.get("cbsa"), set()) | set(c.get("zips", []))
    # The false-alarm query scans every metro, so the housing pass must see
    # every ZIP — but it only KEEPS full dials for case ZIPs (see stream_housing).
    cache = Path(args.cache) if args.cache else ROOT / ".cache" / "trackrecord"
    print("sources:")
    housing_src = fetch_to_cache(args.housing, cache)
    drops_src = fetch_to_cache(args.drops, cache)

    print("streaming price drops (the fourth dial)…")
    drops = stream_drops(drops_src)
    print(f"  drops:   {len(drops):,} ZIPs")
    print("streaming housing market (verdicts computed inline)…")
    housing, compact = stream_housing(housing_src, drops, case_zips)
    print(f"  housing: {len(compact):,} ZIPs · full dials kept for {len(housing):,} case ZIPs")

    months = sorted({m for z in compact.values() for m in z})
    print(f"  window:  {months[0]} → {months[-1]} ({len(months)} months)\n")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    report = {"window": [months[0], months[-1]], "published": [], "dropped": []}

    for case in cfg["cases"]:
        zips = cbsa_zips.get(case.get("cbsa"), set()) or set(case.get("zips", []))
        if not zips:
            report["dropped"].append({"id": case["id"], "reason": "no ZIPs resolved for geo"})
            print(f"DROPPED {case['id']}: no ZIPs resolved")
            continue
        built, why = build_case(case, housing, drops, zips, months)
        if built is None:
            report["dropped"].append({"id": case["id"], "reason": why})
            print(f"DROPPED {case['id']}: {why}")
            continue
        built["kind"] = "hit"
        (out_dir / f"{case['id']}.json").write_text(
            json.dumps(built, separators=(",", ":"), sort_keys=True))
        report["published"].append({
            "id": case["id"], "name": case["name"],
            "first_signal": built["first_signal"],
            "lead_months": built["lead_months"],
            "peak_to_trough": built["peak_to_trough"]})
        ptt = built["peak_to_trough"]
        print(f"OK      {case['id']}: first signal {built['first_signal']}"
              f" · lead {built['lead_months']} mo"
              f" · peak→trough {ptt:.1%}" if ptt is not None else
              f"OK      {case['id']}: first signal {built['first_signal']}"
              f" · lead {built['lead_months']} mo · no decline measured")

    fa = cfg.get("false_alarm_query")
    if fa:
        print("\nnominating false alarms from the data…")
        misses = nominate_false_alarms(fa, compact, months, cbsa_zips,
                                       cbsa_names, set(case_cbsas))
        if misses:
            # Second pass for the nominated metros only — the data picked them,
            # so their ZIPs weren't known when the first pass ran.
            miss_zips = set()
            for mc in misses:
                miss_zips |= cbsa_zips[mc["cbsa"]]
            print(f"  re-streaming dials for {len(miss_zips)} ZIPs in {len(misses)} nominated metros…")
            miss_detail, _ = stream_housing(housing_src, drops, miss_zips)
            housing.update(miss_detail)
        for i, mcase in enumerate(misses):
            case = {"id": f"miss-{mcase['cbsa']}", "name": mcase["name"],
                    "cbsa": mcase["cbsa"],
                    "window": [f"{fa['crossed_in_year']}-01", f"{fa['crossed_in_year']}-12"],
                    "outcome": [mcase["crossed"], months[-1]],
                    "story": "Crossed a danger line — and recovered."}
            built, why = build_case(case, housing, drops, cbsa_zips[mcase["cbsa"]], months)
            if built is None:
                print(f"  skip {mcase['name']}: {why}")
                continue
            built["kind"] = "miss"
            built["worst_drawdown"] = mcase["worst_drawdown"]
            built["recovered_to"] = mcase["recovered_to"]
            (out_dir / f"{case['id']}.json").write_text(
                json.dumps(built, separators=(",", ":"), sort_keys=True))
            report["published"].append({"id": case["id"], "name": case["name"],
                                        "kind": "miss",
                                        "first_signal": built["first_signal"],
                                        "worst_drawdown": mcase["worst_drawdown"]})
            print(f"  MISS  {mcase['name']}: crossed {mcase['crossed']}, "
                  f"worst {mcase['worst_drawdown']:.1%}, now {mcase['recovered_to']:+.1%}")

    # Prune stale outputs. Without this, a case that STOPS reproducing keeps
    # publishing from its last successful run — the exact failure the
    # governing rule exists to prevent. The run's own output is the whole
    # truth; anything else in the directory is a leftover.
    keep = {f"{p['id']}.json" for p in report["published"]} | {"index.json"}
    for f in out_dir.glob("*.json"):
        if f.name not in keep:
            f.unlink()
            report.setdefault("pruned", []).append(f.name)
            print(f"pruned stale {f.name}")

    (out_dir / "index.json").write_text(json.dumps(report, indent=1, sort_keys=True))
    print(f"\npublished {len(report['published'])} · dropped {len(report['dropped'])}"
          f" → {out_dir}")


if __name__ == "__main__":
    main()
