"""
ShouldISellYet — data pipeline.

Downloads Redfin's ZIP-level housing data (the Data Center "Download Hub"
files — plus its price-drops dataset), computes a verdict for every ZIP
with sufficient data, and writes:

  web/data/index.json          — 3-digit ZIP prefix → state (for routing)
  web/data/zips/{STATE}.json   — per-state verdict maps
  web/data/meta.json           — generation date, data period, attribution

Run monthly (locally or via GitHub Actions):
  python pipeline/fetch_data.py [--states MD,VA,DC] [--input path.csv]

Both Redfin schemas are read (auto-detected): the current data-center hub
CSVs, and the pre-2026-06 market-tracker TSVs for archived copies — see
load_rows() for the differences and docs/DATA.md for the migration story.

NOTE ON LICENSING: Redfin makes this data available for use with proper
citation ("Data provided by Redfin, a national real estate brokerage",
linked to redfin.com on first reference — see docs/ATTRIBUTION.md). A
written-confirmation request went to press@redfin.com in 2026-08; no reply
yet — the citation terms on their site remain the operative permission.
Zillow research data is NOT used here — its terms restrict commercial use.
"""

import argparse
import csv
import gzip
import io
import json
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from verdict import ZipMetrics, evaluate, to_compact

# Redfin rebuilt the Data Center as a "Download Hub" in mid-2026. The old
# redfin_market_tracker/*.tsv000.gz files froze on 2026-06-02 (every file's
# Last-Modified stamps within one five-minute batch window) while the page
# kept advertising monthly updates — the data had MOVED, not stopped. The
# hub's own Download button fetches these static files from the same public
# bucket and filters them client-side, so pulling them directly is exactly
# what the official download does. Verified current on 2026-08-03
# (Last-Modified 2026-07-30, rows through period end 2026-06-30).
REDFIN_ZIP_TRACKER = (
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/"
    "redfin_data_center/housing_market/monthly/all_zips.csv"
)
# Price drops moved into their own dataset in the new layout. The old
# tracker's price_drops column shipped empty for years — this file finally
# lights up the "price cuts widespread" signal (see verdict.py).
REDFIN_PRICE_DROPS = (
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/"
    "redfin_data_center/price_drops/monthly/all_zips.csv"
)
# The pre-2026-06 tracker URL, kept for --input against archived copies.
REDFIN_ZIP_TRACKER_LEGACY = (
    "https://redfin-public-data.s3.us-west-2.amazonaws.com/"
    "redfin_market_tracker/zip_code_market_tracker.tsv000.gz"
)

RDC_ZIP_URL = (
    "https://econdata.s3-us-west-2.amazonaws.com/"
    "Reports/Core/RDC_Inventory_Core_Metrics_Zip.csv"
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "data"


def _f(row, key):
    """Parse a float field; Redfin uses empty strings for missing."""
    v = row.get(key, "")
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _open_stream(source: str):
    """Binary stream for a local path or URL, transparently gunzipping by
    MAGIC BYTES, not filename — the legacy tracker is gzipped, the new hub
    CSVs are plain, and a URL tells you nothing either way."""
    if source.startswith("http"):
        req = urllib.request.Request(source, headers={"User-Agent": "shouldisellyet-pipeline"})
        raw = urllib.request.urlopen(req, timeout=600, context=_ssl_context())
    else:
        raw = open(source, "rb")
    buf = io.BufferedReader(raw)
    if buf.peek(2)[:2] == b"\x1f\x8b":
        return gzip.GzipFile(fileobj=buf)
    return buf


def load_rows(source: str):
    """Stream rows from either Redfin schema, presented as the LEGACY shape.

    Two generations of the same dataset:
      v1 — market tracker: gzipped TSV, lowercase-able headers
           (period_end, region "Zip Code: 20874", state_code,
           property_type, yoy columns as fractions / DOM in days).
      v2 — data-center hub: plain CSV, headers like
           "MEDIAN SALE PRICE NSA YOY (%)", region name is the bare ZIP,
           NO state column, NO property_type (all-residential only),
           "NA" for missing.

    Detected by header; v2 rows are translated to v1 key names so the rest
    of the pipeline has exactly one schema to think about.
    """
    stream = _open_stream(source)
    text = io.TextIOWrapper(stream, encoding="utf-8", errors="replace")
    first = text.readline()
    delim = "\t" if "\t" in first else ","
    from itertools import chain
    reader = csv.DictReader(chain([first], text), delimiter=delim)
    # Redfin ships UPPERCASE headers; normalize so lookups are case-proof.
    reader.fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
    if "region name" in reader.fieldnames:
        return _adapt_v2(reader)
    return reader


# v2 header → legacy key. Values are (legacy_key, transform).
#   pct   — the column is a true percent (verified against the national file:
#           price +2.22% actual → column 2.22); legacy wants a fraction, ÷100.
#   days  — the DOM YoY column claims "(%)" but actually holds Δdays × 100
#           (national file: +1 day actual → column 100.0, +3 days → 300.0 —
#           a percent would have read 2.08 / 6.52). ÷100 restores the
#           absolute-days semantics the legacy column had and verdict.py
#           documents. The ZIP's own history recomputes this downstream
#           wherever a year-ago month exists, so this value is only the
#           fallback — but keep the ÷100 right regardless.
_V2_MAP = {
    "period begin": ("period_begin", None),
    "period end": ("period_end", None),
    "homes sold": ("homes_sold", None),
    "median sale price nsa ($)": ("median_sale_price", None),
    "median sale price nsa yoy (%)": ("median_sale_price_yoy", "pct"),
    "median days on market (days)": ("median_dom", None),
    "median days on market yoy (%)": ("median_dom_yoy", "days"),
    "inventory": ("inventory", None),
    "inventory yoy (%)": ("inventory_yoy", "pct"),
    "months of supply": ("months_of_supply", None),
}


def _v2_value(v, kind):
    v = (v or "").strip()
    if v in ("", "NA"):
        return ""
    if kind in ("pct", "days"):
        try:
            return str(float(v) / 100.0)
        except ValueError:
            return ""
    return v


def _adapt_v2(reader):
    import re
    zip_states = load_zip_states()
    metro_st = re.compile(r", ([A-Z]{2}) metro area$")
    for row in reader:
        if (row.get("region type") or "").strip().lower() != "zip":
            continue
        z = (row.get("region name") or "").strip()
        st = zip_states.get(z, "")
        if not st:
            # Whole metros exist in v2 that v1 never covered (Albuquerque —
            # every 871xx ZIP), so the committed map and its prefix fallback
            # can both come up empty. The metro name's own state is the last
            # resort. It is deliberately LAST: metros straddle state lines
            # (07002 is NJ inside the "New York, NY" metro), so this is only
            # trusted where we know nothing else — for a v1-era coverage gap
            # the metro is almost always single-state.
            m = metro_st.search((row.get("metro") or "").strip())
            if m:
                st = m.group(1)
        out = {"region": z, "property_type": "", "is_seasonally_adjusted": "",
               "state_code": st, "_schema": "2"}
        for src, (dst, kind) in _V2_MAP.items():
            out[dst] = _v2_value(row.get(src), kind)
        yield out


def load_zip_states(base=None):
    """pipeline/zip_states.csv → {zip: STATE}, with a 3-digit-prefix majority
    fallback for ZIPs the file has never seen.

    The v2 feed dropped the state column (only a metro name, and metros
    straddle state lines — 07002 sits in the "New York, NY metro area" but is
    New Jersey), while the whole site routes by state. This mapping was
    extracted once from the last v1-derived site data and is committed; ZIP
    assignments to states are effectively permanent, so a static file is the
    right shape, not a per-run lookup.
    """
    global _ZIP_STATES
    if _ZIP_STATES is not None:
        return _ZIP_STATES
    path = Path(base or Path(__file__).parent) / "zip_states.csv"
    exact, prefix_votes = {}, defaultdict(lambda: defaultdict(int))
    if path.exists():
        for line in path.read_text().splitlines()[1:]:
            z, _, st = line.partition(",")
            if len(z) == 5 and st:
                exact[z] = st
                prefix_votes[z[:3]][st] += 1
    prefix = {p: max(v, key=v.get) for p, v in prefix_votes.items()}

    class _Lookup(dict):
        def get(self, z, default=""):
            return super().get(z) or prefix.get(z[:3], default)

    _ZIP_STATES = _Lookup(exact)
    if not exact:
        print("WARNING: pipeline/zip_states.csv missing — v2 rows will have no state")
    return _ZIP_STATES


_ZIP_STATES = None


def load_price_drops(source: str):
    """price_drops/monthly/all_zips.csv → {zip: (YYYY-MM, share_fraction)}.

    Newest period per ZIP. "PERCENT ACTIVE WITH PRICE DROPS (%)" is a true
    percent; the verdict wants the fraction the legacy price_drops column
    was documented to carry. Any failure returns {} — the price-cuts signal
    just stays unavailable, exactly as it was while the legacy column
    shipped empty.

    SISY_SKIP_PD=1 skips it (unit tests — the default arg is a 337MB URL,
    and an end-to-end test that quietly downloads it would work but take
    minutes; same pattern as SISY_SKIP_RDC / SISY_SKIP_MORTGAGE).
    """
    import os
    if os.environ.get("SISY_SKIP_PD"):
        print("price-drops fetch skipped (SISY_SKIP_PD)")
        return {}
    try:
        stream = _open_stream(source)
        text = io.TextIOWrapper(stream, encoding="utf-8", errors="replace")
        reader = csv.DictReader(text)
        reader.fieldnames = [f.strip().lower() for f in (reader.fieldnames or [])]
        col = "percent active with price drops (%)"
        out = {}
        for row in reader:
            if (row.get("region type") or "").strip().lower() != "zip":
                continue
            z = (row.get("region name") or "").strip()
            period = (row.get("period end") or "")[:7]
            v = (row.get(col) or "").strip()
            if not (len(z) == 5 and period) or v in ("", "NA"):
                continue
            if z not in out or period > out[z][0]:
                try:
                    out[z] = (period, float(v) / 100.0)
                except ValueError:
                    continue
        print(f"price drops: {len(out)} ZIPs")
        return out
    except Exception as e:
        print("price-drops fetch failed — signal stays unavailable:", e)
        return {}


def latest_by_zip(rows, states=None, months_back=36):
    """Newest 'All Residential' row per ZIP + monthly history. Prints diagnostics."""
    best = {}
    hist = {}  # zip -> {"YYYY-MM": (price, dom)}
    skipped = {"property_type": 0, "bad_zip": 0, "state_filter": 0}
    first_row_shown = False
    seen_ptypes = {}
    for row in rows:
        if not first_row_shown:
            print("COLUMNS:", list(row.keys()))
            print("SAMPLE ROW:", {k: row[k] for k in list(row)[:14]})
            first_row_shown = True
        if (row.get("is_seasonally_adjusted") or "").strip().lower() == "true":
            continue
        pt = (row.get("property_type") or "").strip().lower()
        seen_ptypes[pt] = seen_ptypes.get(pt, 0) + 1
        if pt and "all residential" not in pt:
            skipped["property_type"] += 1
            continue
        region = row.get("region", "")           # "Zip Code: 20874"
        zip_code = region.split(":")[-1].strip() if ":" in region else region.strip()
        if not (zip_code.isdigit() and len(zip_code) == 5):
            skipped["bad_zip"] += 1
            continue
        state = (row.get("state_code") or row.get("state") or "").strip().upper()
        if len(state) > 2:  # full state name → keep last resort mapping simple
            state = state[:2].upper()
        if states and state not in states:
            skipped["state_filter"] += 1
            continue
        period = row.get("period_end", "")
        if zip_code not in best or period > best[zip_code][0]:
            best[zip_code] = (period, state, row)
        # history: one point per calendar month
        month = period[:7]
        if month:
            price = row.get("median_sale_price", "")
            dom = row.get("median_dom", "")
            try:
                p = int(float(price)) if price else None
            except ValueError:
                p = None
            try:
                dd = int(float(dom)) if dom else None
            except ValueError:
                dd = None
            hist.setdefault(zip_code, {})[month] = (p, dd)
    print("skipped:", skipped)
    print("property_type values seen:",
          dict(sorted(seen_ptypes.items(), key=lambda x: -x[1])[:8]))
    return best, hist


def month_seq(end_month, n):
    """Last n calendar months ending at end_month, as YYYY-MM strings."""
    y, m = int(end_month[:4]), int(end_month[5:7])
    out = []
    for _ in range(n):
        out.append(f"{y:04d}-{m:02d}")
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return list(reversed(out))


def build_history(hmap, end_month, n=36):
    """Compact {s: start_month, p: [...], d: [...]} with nulls for gaps."""
    if not hmap or not end_month:
        return None
    months = month_seq(end_month, n)
    p = [hmap.get(mo, (None, None))[0] for mo in months]
    d = [hmap.get(mo, (None, None))[1] for mo in months]
    if sum(x is not None for x in p) < 6:
        return None  # too sparse to chart honestly
    return {"s": months[0], "p": p, "d": d}


def row_to_metrics(zip_code, period, state, row) -> ZipMetrics:
    inv = _f(row, "inventory")
    sold = _f(row, "homes_sold")
    mos = _f(row, "months_of_supply")
    if mos is None and inv and sold:
        mos = inv / sold  # proxy: inventory ÷ monthly sales
    return ZipMetrics(
        zip_code=zip_code,
        state=state,
        period=period[:7],
        months_of_supply=mos,
        median_sale_price_yoy=_f(row, "median_sale_price_yoy"),
        price_drop_share=_f(row, "price_drops"),
        median_dom=_f(row, "median_dom"),
        median_dom_yoy=_f(row, "median_dom_yoy"),
        inventory_yoy=_f(row, "inventory_yoy"),
        inventory=inv,
        homes_sold=sold,
    )


def _ssl_context():
    """A verifying SSL context that also works on machines whose python has
    no default CA bundle (stock macOS installs): certifi when importable,
    else the system bundle at /etc/ssl/cert.pem. Verification is never
    disabled — no bundle just means the default context and its error."""
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs() and Path("/etc/ssl/cert.pem").exists():
        ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ctx


def _http_get(url, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": "shouldisellyet-pipeline"})
    return urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()).read().decode("utf-8", "replace")


def _rates_from_weekly(vals):
    """{now, year_ago, asof} from [(date, rate), ...] weekly points, oldest
    first. None when the series is too short to trust."""
    if len(vals) < 40:
        return None
    ya = vals[-52] if len(vals) > 52 else vals[0]
    return {"now": vals[-1][1], "year_ago": ya[1], "asof": vals[-1][0]}


def parse_fred_csv(text):
    """FRED fredgraph.csv → weekly points. Rows are 'YYYY-MM-DD,6.72' with
    '.' for missing observations."""
    rows = [r.split(",") for r in text.strip().splitlines()[1:] if "," in r]
    return [(r[0], float(r[1])) for r in rows if len(r) >= 2 and r[1].strip() not in (".", "")]


def parse_pmms_csv(text, keep=80):
    """Freddie Mac PMMS_history.csv → weekly (date, 30yr-rate) points.

    The file is the full multi-decade history; the header names shift
    case/order occasionally, so find the date and 30-year-rate columns by
    name. Only the trailing `keep` rows matter here."""
    reader = csv.DictReader(io.StringIO(text))
    fields = {(f or "").strip().lower(): f for f in (reader.fieldnames or [])}
    date_col = next((fields[k] for k in fields if k in ("date", "week")), None)
    rate_col = next((fields[k] for k in fields if k.replace(" ", "") in ("pmms30", "us30yr", "frm30", "30yrfrm")), None)
    if not date_col or not rate_col:
        return []
    vals = []
    for row in reader:
        d = (row.get(date_col) or "").strip()
        v = (row.get(rate_col) or "").strip().rstrip("%")
        if not d or not v:
            continue
        try:
            rate = float(v)
        except ValueError:
            continue
        # normalize PMMS's M/D/YYYY to ISO so meta.json dates read the same
        # regardless of which source produced them
        if "/" in d:
            try:
                mth, day, yr = d.split("/")
                d = f"{int(yr):04d}-{int(mth):02d}-{int(day):02d}"
            except ValueError:
                pass
        vals.append((d, rate))
    return vals[-keep:]


def load_rdc(source):
    """Realtor.com residential listings database — current-month ZIP file.

    Returns {zip: {p, dom, domy, inv, invy, pd, pdn}}. This feed enriches
    entries for DISPLAY and cross-checking only; it never feeds the verdict
    engine. Two hard reasons:
      - Definitions differ (RDC price_reduced_share does not even reconcile
        with price_reduced_count / active_listing_count in the published
        file, so it is clearly measured against a denominator we can't see;
        RDC *_yy fields are fractions while Redfin's median_dom_yoy is
        absolute days). Our danger thresholds are validated against Redfin's
        definitions only.
      - Silently switching a verdict input's source would flip verdicts and
        fire subscriber alert emails on a data-source change, not a market
        change.

    quality_flag=1 rows (about half the file — mostly thin ZIPs) keep their
    current-month counts but DROP the year-over-year fields and gain q:1:
    the flag marks unreliable comparability, not unreliable counts, so the
    cross-check still lists properties while withholding the comparisons
    and the direction verdict. Any fetch/parse failure returns {} — the
    site simply renders without the cross-check.
    """
    import os
    if os.environ.get("SISY_SKIP_RDC"):
        print("RDC fetch skipped (SISY_SKIP_RDC)")
        return {}
    try:
        if source.startswith("http"):
            text = _http_get(source, timeout=120)
        else:
            text = open(source, encoding="utf-8", errors="replace").read()
    except Exception as e:
        print("RDC fetch failed — cross-check skipped:", e)
        return {}
    out = {}
    period = ""
    for row in csv.DictReader(io.StringIO(text)):
        z = (row.get("postal_code") or "").strip()
        if z.isdigit() and len(z) < 5:
            z = z.zfill(5)  # leading zeros (New England ZIPs) drop in the CSV
        if not (z.isdigit() and len(z) == 5):
            continue
        flagged = (row.get("quality_flag") or "0").strip() not in ("", "0", "0.0")
        month = (row.get("month_date_yyyymm") or "").strip()
        p = f"{month[:4]}-{month[4:6]}" if len(month) == 6 and month.isdigit() else ""
        def g(col):
            v = (row.get(col) or "").strip()
            try:
                return float(v)
            except ValueError:
                return None
        e = {"p": p}
        cols = [
            ("dom",  "median_days_on_market",     True),
            ("inv",  "active_listing_count",      True),
            ("pd",   "price_reduced_share",       False),
            ("pdn",  "price_reduced_count",       True),
        ]
        if not flagged:  # yy comparisons only where the feed itself trusts them
            cols += [("domy", "median_days_on_market_yy", False),   # fraction, not days
                     ("invy", "active_listing_count_yy",  False)]
        for k, col, as_int in cols:
            v = g(col)
            if v is not None:
                e[k] = int(v) if as_int else round(v, 3)
        if flagged:
            e["q"] = 1
        if len(e) > (2 if flagged else 1):
            out[z] = e
            period = max(period, p)
    print(f"RDC: {len(out)} ZIPs, period {period}")
    return out


def load_fhfa_compact(base=None):
    """pipeline/fhfa_zip.csv (written annually by fetch_fhfa.py) →
    {zip: {"y": thru_year, "a1": latest_annual_change_pct, "a3": 3yr_avg}}.
    Absent file just means no FHFA benchmark on the report."""
    path = Path(base or Path(__file__).parent) / "fhfa_zip.csv"
    if not path.exists():
        return {}
    out = {}
    for r in csv.DictReader(open(path)):
        try:
            out[r["zip"]] = {"y": int(r["thru"]), "a1": float(r["a1"]), "a3": float(r["a3"])}
        except (KeyError, ValueError):
            continue
    print(f"FHFA benchmark: {len(out)} ZIPs")
    return out


def load_backtest(base=None):
    """pipeline/backtest_results.json (written by backtest_thresholds.py) →
    the compact topline meta.json ships to the report, or None."""
    path = Path(base or Path(__file__).parent) / "backtest_results.json"
    if not path.exists():
        return None
    try:
        r = json.loads(path.read_text())
        sig = {}
        for k, v in (r.get("signals") or {}).items():
            if v.get("crossed") and v.get("clear"):
                sig[k] = {"x": v["crossed"]["decline_pct"], "c": v["clear"]["decline_pct"],
                          "n": v["crossed"]["n"]}
        return {"y0": r["redfin_years"][0], "y1": r["redfin_years"][1],
                "fhfa": r["fhfa_thru"], "n": r["n_pairs"], "sig": sig}
    except (KeyError, ValueError, json.JSONDecodeError) as e:
        print("backtest results unreadable, skipping:", e)
        return None


def fetch_mortgage_rates():
    """Current + year-ago 30y fixed rate. Returns None only if every source fails.

    Two independent sources for the same Freddie Mac PMMS series, publisher
    first: freddiemac.com answers quickly, while FRED's fredgraph.csv graph
    endpoint has timed out from both CI (2026-07-26 run) and local testing —
    it stays as the fallback with a short timeout.

    SISY_SKIP_MORTGAGE=1 skips the network entirely (unit tests).
    """
    import os
    if os.environ.get("SISY_SKIP_MORTGAGE"):
        print("mortgage fetch skipped (SISY_SKIP_MORTGAGE)")
        return None
    from datetime import timedelta
    start = (date.today() - timedelta(days=430)).isoformat()
    sources = [
        ("Freddie Mac PMMS", "https://www.freddiemac.com/pmms/docs/PMMS_history.csv",
         parse_pmms_csv, 60),
        ("FRED", "https://fred.stlouisfed.org/graph/fredgraph.csv?id=MORTGAGE30US&cosd=" + start,
         parse_fred_csv, 30),
    ]
    for name, url, parse, timeout in sources:
        for attempt in range(2):
            try:
                rates = _rates_from_weekly(parse(_http_get(url, timeout)))
                if rates:
                    print(f"mortgage rates via {name}: {rates}")
                    return rates
                print(f"mortgage fetch via {name}: series too short, skipping source")
                break
            except Exception as e:
                print(f"mortgage fetch via {name} attempt {attempt+1} failed:", e)
    print("mortgage fetch skipped — all sources failed")
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default=REDFIN_ZIP_TRACKER,
                    help="Local CSV/TSV(.gz) path or URL (default: Redfin ZIP file, "
                         "data-center hub layout; the legacy tracker schema is "
                         "auto-detected for archived copies)")
    ap.add_argument("--price-drops", default=REDFIN_PRICE_DROPS,
                    help="Redfin price-drops ZIP csv path or URL ('' to disable)")
    ap.add_argument("--states", default="",
                    help="Comma-separated state codes to limit output (e.g. MD,VA,DC)")
    ap.add_argument("--rdc", default=RDC_ZIP_URL,
                    help="Realtor.com RDC ZIP csv path or URL ('' to disable)")
    args = ap.parse_args()
    states = set(s.strip().upper() for s in args.states.split(",") if s.strip()) or None

    print(f"Loading {args.input} …")
    best, hist = latest_by_zip(load_rows(args.input), states)
    print(f"{len(best)} ZIPs with data")
    if len(best) < 100 and args.input.startswith("http"):
        sys.exit(
            f"FATAL: only {len(best)} ZIPs parsed — refusing to publish. "
            "Check the COLUMNS/SAMPLE ROW diagnostics above for a schema mismatch."
        )

    # v2 feeds price drops from its own file (the legacy column shipped empty).
    pd_map = load_price_drops(args.price_drops) if args.price_drops else {}

    rdc = load_rdc(args.rdc) if args.rdc else {}
    fhfa = load_fhfa_compact()

    by_state = defaultdict(dict)
    prefix_state = {}
    period_seen = ""
    spys = []
    for zip_code, (period, state, row) in best.items():
        if row.get("_schema") == "2":
            # Price-drop join, same month only — these files publish together,
            # and a stale share is worse than an absent one.
            pdv = pd_map.get(zip_code)
            if pdv and pdv[0] == period[:7]:
                row["price_drops"] = str(pdv[1])
            # DOM year-over-year, recomputed from OUR month history when the
            # year-ago month exists. The v2 column's ÷100 mapping was verified
            # empirically (see _V2_MAP), but Redfin could silently fix that
            # column to true percent someday, and days-vs-fraction is not
            # distinguishable per-row. Self-computed Δdays is immune; the
            # mapped column stays as fallback for ZIPs with a history gap.
            hm = hist.get(zip_code) or {}
            mo = period[:7]
            ago = f"{int(mo[:4]) - 1:04d}-{mo[5:7]}"
            now_d = hm.get(mo, (None, None))[1]
            ago_d = hm.get(ago, (None, None))[1]
            if now_d is not None and ago_d is not None:
                row["median_dom_yoy"] = str(now_d - ago_d)
        m = row_to_metrics(zip_code, period, state, row)
        v = evaluate(m)
        entry = to_compact(v, m)
        h = build_history(hist.get(zip_code), period[:7])
        if h:
            entry["h"] = h
        # Independent listing-feed cross-check — display only, post-verdict,
        # so adding/refreshing this source can never flip a verdict.
        x = rdc.get(zip_code)
        if x:
            entry["x"] = x
        # FHFA official annual index — benchmark, not a signal
        fb = fhfa.get(zip_code)
        if fb:
            entry["f"] = fb
        by_state[state or "XX"][zip_code] = entry
        prefix_state[zip_code[:3]] = state or "XX"
        period_seen = max(period_seen, period)
        if m.median_sale_price_yoy is not None:
            spys.append(m.median_sale_price_yoy)

    OUT.joinpath("zips").mkdir(parents=True, exist_ok=True)
    for state, zips in by_state.items():
        (OUT / "zips" / f"{state}.json").write_text(json.dumps(zips, separators=(",", ":")))
    (OUT / "index.json").write_text(json.dumps(prefix_state, separators=(",", ":")))
    # national context: price-trend deciles + verdict counts + mortgage rates
    spys.sort()
    deciles = [round(spys[int(len(spys) * q / 10) - (1 if q == 10 else 0)], 4)
               for q in range(11)] if len(spys) >= 100 else []
    counts0 = {"green": 0, "yellow": 0, "red": 0, "strong": 0}
    for zips in by_state.values():
        for z in zips.values():
            counts0[z["l"]] += 1
    mortgage = fetch_mortgage_rates()
    backtest = load_backtest()
    (OUT / "meta.json").write_text(json.dumps({
        "generated": date.today().isoformat(),
        "period": period_seen[:7],
        # Exact citation string required by Redfin's Data Center terms. Plain
        # text on purpose — render sites add the redfin.com link (see
        # docs/ATTRIBUTION.md before changing a single word of this).
        "attribution": "Data provided by Redfin, a national real estate brokerage"
                       + (" · Listing data from Realtor.com® Economic Research" if rdc else ""),
        "national": {"spy_deciles": deciles, "counts": counts0,
                     **({"mortgage": mortgage} if mortgage else {}),
                     **({"backtest": backtest} if backtest else {})},
    }))

    counts = defaultdict(int)
    for zips in by_state.values():
        for z in zips.values():
            counts[z["l"]] += 1
    print(f"Done. green={counts['green']} yellow={counts['yellow']} "
          f"red={counts['red']} strong={counts['strong']}")
    print(f"Wrote {len(by_state)} state files to {OUT}")


if __name__ == "__main__":
    main()
