#!/usr/bin/env python3
"""ShouldISellYet — Google Search Console API puller.

WHY THIS EXISTS. Phase 1 of the RentCast migration ranks ZIPs by 90-day
organic impressions and spends API money on the top of that list. Phase 4
then lifts `noindex` in tranches in the same order. Nothing else in this
repo can produce that ranking: `public.events` is anonymous first-party
counting that honours DNT/GPC and carries no organic-search signal, and it
says so in its own snapshot file.

READ THIS BEFORE TRUSTING THE OUTPUT. Impressions accrue only for URLs that
can appear in search results, and every ZIP page currently serves
`noindex,follow` (Phase 0). While that holds, this puller will correctly
report approximately nothing for /zip/ pages — that is the data being
honest, not a bug, and the script says so out loud rather than writing a
zero-row ranking somebody then spends $199 against.

The one way a usable pre-pause ranking exists is if the domain property was
verified and collecting BEFORE 2026-08-14. The domain carries a live
google-site-verification TXT record, so it may have been. `--probe` answers
that question in one request:

    python3 pipeline/fetch_gsc.py --probe

Normal run — the Lever 1 ranking:

    python3 pipeline/fetch_gsc.py [--days 90] [--out pipeline/gsc_zip.csv]

Re-parse without spending a request (every response is kept, per Lever 2):

    python3 pipeline/fetch_gsc.py --input archive/gsc/2026-05-21_2026-08-16

AUTH. Three secrets, no new dependency: the OAuth refresh-token flow is a
plain form POST, where a service account would need RSA signing and pull in
a crypto library for one script.

    GSC_CLIENT_ID, GSC_CLIENT_SECRET, GSC_REFRESH_TOKEN

One-time consent to mint the refresh token is a human step (see
docs/migration/SEARCH-CONSOLE.md) — the scope is read-only:
https://www.googleapis.com/auth/webmasters.readonly

QUOTA AND LAG. Search Console returns at most 25,000 rows per request, so
the page pull paginates on `startRow`. Data is final about two days back;
`--lag` (default 3) keeps the window off the incomplete tail, since a
partial last day would understate exactly the pages we are ranking.
"""

import argparse
import csv
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_data import _ssl_context

ROOT = Path(__file__).resolve().parents[1]
SITE = "sc-domain:shouldisellyet.com"
TOKEN_URL = "https://oauth2.googleapis.com/token"
API = "https://searchconsole.googleapis.com/webmasters/v3/sites/{site}/searchAnalytics/query"
ROW_LIMIT = 25000           # the API's hard maximum per request
DEFAULT_RAW = ROOT / "archive" / "gsc"   # gitignored; see .gitignore


# ————— pure parsing: no network, no clock —————

def page_to_zip(url):
    """A ZIP-page URL → its 5-digit ZIP, else None.

    Real Search Console rows arrive as absolute URLs and sometimes carry a
    query string (shared links keep their utm tags). State hubs live at the
    same prefix — /zip/MD/ — and must not be mistaken for a ZIP, which is
    why this checks the shape rather than just taking the last segment.
    """
    if not url:
        return None
    path = urllib.parse.urlsplit(url).path
    parts = [p for p in path.split("/") if p]
    if len(parts) != 2 or parts[0] != "zip":
        return None            # /zip/, /zip/MD/, and every non-ZIP page
    z = parts[1]
    return z if len(z) == 5 and z.isdigit() else None


def rows_to_zip_ranking(rows):
    """Search Console `rows` → per-ZIP ranking, most impressions first.

    Rows are keyed by page URL, one per URL, but a ZIP could in principle
    arrive twice (trailing-slash variants are distinct URLs to Search
    Console). Clicks and impressions add; position is re-weighted by
    impressions, because averaging two averages is wrong whenever the two
    pages have different exposure. CTR is recomputed from the totals rather
    than averaged, for the same reason.
    """
    agg = {}
    for r in rows:
        keys = r.get("keys") or []
        z = page_to_zip(keys[0] if keys else "")
        if not z:
            continue
        clicks = float(r.get("clicks") or 0)
        imps = float(r.get("impressions") or 0)
        pos = float(r.get("position") or 0)
        a = agg.setdefault(z, {"clicks": 0.0, "impressions": 0.0, "pos_wt": 0.0})
        a["clicks"] += clicks
        a["impressions"] += imps
        a["pos_wt"] += pos * imps
    out = []
    for z, a in agg.items():
        imps = a["impressions"]
        out.append({
            "zip": z,
            "clicks": int(round(a["clicks"])),
            "impressions": int(round(imps)),
            "ctr": round(a["clicks"] / imps, 5) if imps else 0.0,
            "position": round(a["pos_wt"] / imps, 2) if imps else 0.0,
        })
    out.sort(key=lambda d: (-d["impressions"], -d["clicks"], d["zip"]))
    return out


def non_zip_summary(rows):
    """Everything that is not a ZIP page, as {path: impressions}, biggest
    first. During the pause this is the only part of the report with numbers
    in it, so it is printed rather than discarded — it is how you tell "the
    property has no data" apart from "the property has data and the ZIP
    pages are correctly deindexed"."""
    agg = {}
    for r in rows:
        keys = r.get("keys") or []
        url = keys[0] if keys else ""
        if page_to_zip(url):
            continue
        path = urllib.parse.urlsplit(url).path or url
        agg[path] = agg.get(path, 0) + float(r.get("impressions") or 0)
    return sorted(((p, int(round(v))) for p, v in agg.items()),
                  key=lambda t: -t[1])


def data_span(rows):
    """Date-dimension rows → (earliest, latest) days that actually carry
    impressions, or (None, None). The probe's whole answer."""
    days = sorted(r["keys"][0] for r in rows
                  if (r.get("keys") and float(r.get("impressions") or 0) > 0))
    return (days[0], days[-1]) if days else (None, None)


def window(days, lag, today=None):
    """(start, end) as YYYY-MM-DD, ending `lag` days back so the incomplete
    tail never lands in a ranking. `today` is injectable so tests do not
    depend on the calendar."""
    end = (today or date.today()) - timedelta(days=lag)
    return (end - timedelta(days=days - 1)).isoformat(), end.isoformat()


# ————— network —————

def access_token():
    """Refresh token → access token. Fails loudly and specifically: this is
    the step that breaks first when a secret is missing or consent was
    revoked, and a generic 400 sends people looking in the wrong place."""
    cid = os.environ.get("GSC_CLIENT_ID", "")
    secret = os.environ.get("GSC_CLIENT_SECRET", "")
    refresh = os.environ.get("GSC_REFRESH_TOKEN", "")
    missing = [n for n, v in (("GSC_CLIENT_ID", cid),
                              ("GSC_CLIENT_SECRET", secret),
                              ("GSC_REFRESH_TOKEN", refresh)) if not v]
    if missing:
        raise SystemExit(
            "Search Console credentials missing: " + ", ".join(missing) +
            "\nSee docs/migration/SEARCH-CONSOLE.md for the one-time consent "
            "flow that mints the refresh token.")
    body = urllib.parse.urlencode({
        "client_id": cid, "client_secret": secret,
        "refresh_token": refresh, "grant_type": "refresh_token",
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, headers={
        "Content-Type": "application/x-www-form-urlencoded"})
    try:
        raw = urllib.request.urlopen(req, timeout=60, context=_ssl_context()).read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        raise SystemExit(
            f"Token exchange failed ({e.code}). Google said: {detail}\n"
            "invalid_grant usually means the refresh token was revoked or the "
            "consent screen is still in Testing mode (those tokens expire "
            "after 7 days) — re-run the consent flow.")
    return json.loads(raw)["access_token"]


def query(token, site, start, end, dimensions, start_row=0):
    """One searchAnalytics/query request. Returns the parsed response."""
    url = API.format(site=urllib.parse.quote(site, safe=""))
    payload = json.dumps({
        "startDate": start, "endDate": end,
        "dimensions": dimensions, "type": "web",
        "rowLimit": ROW_LIMIT, "startRow": start_row,
    }).encode()
    req = urllib.request.Request(url, data=payload, headers={
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"})
    try:
        raw = urllib.request.urlopen(req, timeout=120, context=_ssl_context()).read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:400]
        if e.code == 403:
            raise SystemExit(
                f"403 from Search Console for {site}. Google said: {detail}\n"
                "The authorising Google account is not a verified owner or "
                "user of this property. Check the property exists at "
                "search.google.com/search-console and that this account is on "
                "it — the DNS TXT record alone does not grant API access to a "
                "different account.")
        raise SystemExit(f"Search Console query failed ({e.code}): {detail}")
    return json.loads(raw)


def fetch_all(token, site, start, end, dimensions, raw_dir=None):
    """Every page of results, with each raw response kept.

    Storing the responses is Lever 2 of the migration plan applied to the
    free source as well as the paid one: re-parsing costs nothing, and the
    quota here is a real daily limit even though there is no invoice.
    """
    rows, start_row, pages = [], 0, 0
    while True:
        resp = query(token, site, start, end, dimensions, start_row)
        batch = resp.get("rows") or []
        if raw_dir:
            d = Path(raw_dir) / f"{start}_{end}"
            d.mkdir(parents=True, exist_ok=True)
            (d / f"{'-'.join(dimensions)}-{pages:03d}.json").write_text(
                json.dumps(resp, indent=1), encoding="utf-8")
        rows += batch
        pages += 1
        if len(batch) < ROW_LIMIT:
            return rows, pages
        start_row += ROW_LIMIT


def load_saved(path):
    """Re-read stored responses — a file, or a window directory of them."""
    p = Path(path)
    files = sorted(p.glob("*.json")) if p.is_dir() else [p]
    if not files:
        raise SystemExit(f"No stored responses under {p}")
    rows = []
    for f in files:
        rows += json.loads(f.read_text()).get("rows") or []
    return rows, len(files)


# ————— output —————

FIELDS = ["zip", "clicks", "impressions", "ctr", "position"]


def write_ranking(path, ranking):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(ranking)


def report(ranking, others, start, end):
    """What the run actually found, said plainly."""
    total = sum(r["impressions"] for r in ranking)
    print(f"window: {start} → {end}")
    print(f"ZIP pages with impressions: {len(ranking):,} · {total:,} impressions")
    if ranking:
        head = ranking[:10]
        width = max(len(str(r["impressions"])) for r in head)
        for r in head:
            print(f"  {r['zip']}  {r['impressions']:>{width},} imp · "
                  f"{r['clicks']} clicks · pos {r['position']}")
        top = ranking[:1000]
        share = sum(r["impressions"] for r in top) / total if total else 0
        print(f"top 1,000 ZIPs carry {share:.1%} of ZIP impressions "
              f"— that ratio is what Tier A vs Tier B is buying")
    if others:
        print("non-ZIP pages:", ", ".join(f"{p} {v:,}" for p, v in others[:6]))
    if not ranking:
        print()
        print("NO ZIP-PAGE IMPRESSIONS IN THIS WINDOW.")
        print("Expected while Phase 0 holds: every /zip/ page serves "
              "noindex,follow, so none of them can appear in results, so none "
              "of them can accrue impressions. This is not a ranking and must "
              "not be used as one — see correction 1 in "
              "docs/migration/PHASE1-PLUS.md. Run --probe to find out whether "
              "the property holds pre-pause history instead.")


def main(argv=None):
    ap = argparse.ArgumentParser(description="Search Console → per-ZIP impression ranking")
    ap.add_argument("--site", default=SITE)
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--lag", type=int, default=3,
                    help="end the window this many days back (data is final ~2 days)")
    ap.add_argument("--start"), ap.add_argument("--end")
    ap.add_argument("--out", default=str(Path(__file__).parent / "gsc_zip.csv"))
    ap.add_argument("--raw", default=str(DEFAULT_RAW),
                    help="keep every raw response here ('' to skip)")
    ap.add_argument("--input", help="parse stored responses instead of calling the API")
    ap.add_argument("--probe", action="store_true",
                    help="ask how far back this property holds data, in one request")
    ap.add_argument("--allow-empty", action="store_true",
                    help="permit overwriting a populated ranking with an empty one")
    args = ap.parse_args(argv)

    if args.probe:
        start, end = args.start, args.end
        if not (start and end):
            start, end = window(480, args.lag)   # 16 months, the API's own limit
        rows, pages = fetch_all(access_token(), args.site, start, end,
                                ["date"], args.raw or None)
        first, last = data_span(rows)
        print(f"probe window: {start} → {end} ({pages} request(s))")
        if not first:
            print("No data anywhere in 16 months. Either the property was "
                  "verified recently, or it was removed and re-added — the "
                  "DNS TXT record outliving a deleted property looks exactly "
                  "like this. There is no pre-pause ranking to recover.")
            return 0
        print(f"data runs {first} → {last}")
        print("PRE-PAUSE HISTORY EXISTS." if first < "2026-08-14" else
              "All data is post-pause; no pre-pause ranking to recover.")
        return 0

    if args.input:
        rows, pages = load_saved(args.input)
        start, end = args.start or "?", args.end or "?"
        print(f"parsed {len(rows):,} stored rows from {pages} file(s)")
    else:
        start, end = (args.start, args.end) if (args.start and args.end) \
            else window(args.days, args.lag)
        rows, pages = fetch_all(access_token(), args.site, start, end,
                                ["page"], args.raw or None)
        print(f"fetched {len(rows):,} page rows in {pages} request(s)")

    ranking = rows_to_zip_ranking(rows)
    report(ranking, non_zip_summary(rows), start, end)

    out = Path(args.out)
    if not ranking and out.exists() and out.stat().st_size > 40 and not args.allow_empty:
        print(f"\nREFUSING to overwrite {out} with an empty ranking. "
              f"Pass --allow-empty if that is genuinely what you mean.")
        return 1
    write_ranking(out, ranking)
    print(f"wrote {out} ({len(ranking):,} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
