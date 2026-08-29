#!/usr/bin/env python3
"""ShouldISellYet — /metro/{slug} pages.

    python3 pipeline/build_metro.py [--web web] [--only 24340] [--min-zips 8]

WHY THIS EXISTS. Every marketing post about a metro used to land on the
homepage, which throws the click away: someone who tapped "76% of the ZIP codes
we track in Grand Rapids are moving toward a danger line" arrives somewhere
that does not mention Grand Rapids. A post's destination has to keep the
post's promise.

Runs on EVERY deploy beside build_pages.py and build_research.py, from
committed data only — no network, no Supabase, no clock. Same inputs, same
bytes.

THE PAYWALL IS NOT CROSSED HERE, and this is the one design constraint worth
reading before editing. Per-ZIP approach VELOCITY — the projected months until
a ZIP reaches a danger line, and its 3-month pace — is the paid product
(velocity.py's header; pipeline/velocity/zip-velocity-latest.json is
gitignored and served only through verify-access for a valid purchase token).
So the ZIP table below shows each ZIP's PUBLIC dial values against their
published danger lines — the gap you can read off the same numbers every
/zip/ page already shows — and never the projection. Metro-level velocity IS
public (velocity-aggregates.json) and appears as one aggregate line.

The 6-month sparkline is drawn from pipeline/research/history.json, which
carries a complete monthly verdict-count series per metro back to 2012. That
completeness is why this chart exists and the metro cards carry none: the
velocity gathering list drops a metro in months it does not qualify, and a
line with holes misrepresents a trend.
"""

import argparse
import csv
import html
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import data_pause as PAUSE
from verdict_copy import COPY as VCOPY

ROOT = Path(__file__).resolve().parents[1]
# A metro needs this many ZIPs with a current reading before its warning
# share is published. Same number as the --min-zips page floor: below it,
# the figure describes the release order, not the market.
MIN_SCORED_FOR_SHARE = 8

SITE = "https://shouldisellyet.com"
UTM = "utm_source=metropage&utm_medium=organic&utm_campaign=metro_seo"
MIN_ZIPS = 8          # the velocity gathering floor: any metro a post can name has a page
SPARK_MONTHS = 6

esc = lambda s: html.escape(str(s), quote=True)

# THE ADVICE DISCLAIMER WAS MISSING HERE ENTIRELY. Every /zip/ page, state hub
# and the markets index carry one (build_pages.FOOTER); ~609 metro pages and
# the metro index carried none, and they are the pages a marketing post lands
# a cold reader on. Wording matches the site footer so the two cannot drift.
DISCLAIMER = ("Readings are computed from licensed market statistics and are "
              "general information only — not financial, legal, tax, or "
              "real-estate advice.")

# NOT A HAND-TYPED MAP ANY MORE. This was the sixth independent copy of the
# level->word table, and a hand-typed table is how the site came to show four
# words on metro pages while web/methodology.html says the vocabulary is three
# ("There is no fourth word"). pipeline/data/verdict_copy.json is canonical —
# resolving the `strong` word to ACT is therefore ONE edit in that file, and
# this renderer follows it without a second decision being made here.
WORD = {lvl: VCOPY[lvl]["word"] for lvl in VCOPY}

# The qualifier renders beside the word whatever the word is. `strong` means a
# market with no danger line crossed and all three strength conditions met —
# a reason to consider selling, not a warning — and nothing in a one-word tag
# conveys that on its own.
QUAL = {"strong": "seller's market"}
TAGCLASS = {"green": "green", "yellow": "amber", "red": "red", "strong": "strong"}
# The four public dials and the published line each is measured against. These
# are the same numbers and the same thresholds every /zip/ page shows.
# The last lambda is the value AS PRINTED, in the line's own units. Colour is
# decided on that, not on the raw float — otherwise 0.354 and 0.349 both print
# "35%" and only one of them is red, on the same page, under a note telling the
# reader that red means past the published line. A reader who can see two
# identical numbers in two different colours has been given a reason to
# distrust every other number on the page.
DIALS = [
    ("mos", "Months of supply", 4.0, "gt", lambda v: f"{v:.1f}", lambda v: round(v, 1)),
    ("spy", "Price vs. last yr", -0.02, "lt", lambda v: f"{v * 100:+.1f}%",
     lambda v: round(v * 100, 1) / 100),
    ("pd", "Listings cutting price", 0.35, "gt", lambda v: f"{v * 100:.0f}%",
     lambda v: round(v * 100) / 100),
]


def short_metro(name):
    """"Grand Rapids-Wyoming-Kentwood, MI" -> "Grand Rapids, MI" — the name a
    person uses. The full CBSA title stays on the page, once, as the subtitle."""
    if not name or "," not in name:
        return name or ""
    city, states = name.rsplit(",", 1)
    return f"{city.split('-')[0].strip()}, {states.strip().split('-')[0]}"


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "-", short_metro(name).lower()).strip("-")


def load_places():
    p = Path(__file__).parent / "data" / "zip_places.csv"
    if not p.exists():
        return {}
    return {r["zip"]: (r["city"], r["state"])
            for r in csv.DictReader(open(p, encoding="utf-8"))}


def load_zip_cbsa():
    p = Path(__file__).parent / "data" / "zip_cbsa.csv"
    if not p.exists():
        return {}
    return {r["zip"]: r["cbsa"] for r in csv.DictReader(open(p, encoding="utf-8"))}


def load_entries(data_dir):
    """The ZIPs this site publishes a page for — which is the manifest.

    This used to keep only records carrying a usable verdict, matching the
    completeness test build_pages applied. That test is gone: the URL set is
    now pipeline/data/page_manifest.csv and per-ZIP records are provisioned,
    so an unreleased ZIP's record is {"st": ST} with no level at all. Left
    alone, this returned an EMPTY dict, by_metro was empty, every metro fell
    under --min-zips, and the deploy emitted ZERO of the 609 live /metro/
    pages — deleting all of them, since web/metro/ is gitignored and rebuilt
    each deploy. Measured before this change: 609 directories became 1.

    Membership is geography, not data: a ZIP belongs to its metro whether or
    not we currently publish a reading for it.
    """
    from build_manifest import read_manifest
    # One file per ZIP since 2026-08-20. This read was left pointing at the
    # removed per-state layout, and the bug hid because the fallback two lines
    # below — {"st": st} — is byte-identical to what a blanked record looks
    # like today. It would have surfaced at Tranche 1: with records always
    # empty, the insufficient_data filter can never fire, so a released ZIP
    # with too little data to score would still be counted into its metro.
    # The PRIVATE record set, not web/data/z. The public files carry only a
    # state code now — repointing build_pages and forgetting this one blanked
    # every rating on all 608 metro pages, which is what a build reading the
    # wrong side of that split looks like.
    records = {}
    for f in sorted((ROOT / ".build" / "readings").glob("*.json")):
        records[f.stem] = json.loads(f.read_text())
    out = {}
    # pages_only=False: metro membership is the wider SCORED set, not the
    # standing-page set. Using the narrow one drops 92 metros below the
    # 8-ZIP floor.
    for z, st in read_manifest(pages_only=False):
        e = records.get(z) or {"st": st}
        if any(r[0] == "insufficient_data" for r in (e.get("r") or [])):
            continue
        out[z] = e
    return out


MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def pretty_period(period):
    """'2026-08' -> 'August 2026'. Anything else comes back untouched, so a
    malformed value degrades to something readable rather than raising."""
    p = str(period or "")
    if len(p) == 7 and p[4] == "-" and p[:4].isdigit() and p[5:7].isdigit():
        try:
            return f"{MONTHS[int(p[5:7]) - 1]} {p[:4]}"
        except IndexError:
            return p
    return p


def live_period(entries, zips=None):
    """The as-of month of the readings THIS page actually shows, or "".

    A date stamp has to come from the readings under it, never from a global.
    web/data/meta.json's `period` is the last Redfin data build — frozen at
    2026-06 and not moving again — while the released v2 readings carry their
    own as-of month in `p` (2026-08 today). Stamping the global on a page
    showing August readings dated all 609 metro pages two months early, and
    dated the 555 pages with no reading at all to a month whose data they are
    not showing.

    So: the newest as-of month among the readings the page may display, and
    "" when it may display none. Every caller must render nothing at all for
    "" rather than a placeholder — a page with no reading gets no date.
    """
    pool = entries if zips is None else zips
    months = {(entries.get(z) or {}).get("p") for z in pool
              if PAUSE.shows_data(z, (entries.get(z) or {}).get("b", PAUSE.LEGACY_BASIS))}
    months.discard(None)
    months.discard("")
    return max(months) if months else ""


def spark_caption(series):
    """What the line IS, said plainly, because it is not the hero's measure.

    The hero counts this page's own ratings. This line is our national
    warning-sign index restricted to this metro: a different signal set and a
    different scored list, which is why its level can differ from the figure
    above. It is drawn without numbers precisely so it reads as a direction and
    never as a second, competing percentage.

    The honest options were to delete a real trend or to label it for what it
    is. Leaving it captioned "warning-sign share" beside a hero computed a
    different way was the third option, and the wrong one.
    """
    vals = [v for _, v in series if v is not None]
    if len(vals) < 4:
        return ""
    move = ("rising" if vals[-1] - vals[0] > 0.5 else
            "falling" if vals[0] - vals[-1] > 0.5 else "roughly flat")
    return (f"The direction of our national warning-sign index for this metro over "
            f"the last {len(vals)} months — {move}. That index uses a different "
            f"signal set from the ratings above, so its level differs.")


def spark(series, w=560, h=90):
    """Inline SVG, not a PNG: it stays crisp at any zoom, costs no Pillow call,
    and needs no separate file to deploy. Returns "" below four points — a line
    drawn from three is not a trend."""
    pts = [v for _, v in series if v is not None]
    if len(pts) < 4:
        return ""
    lo, hi = min(pts), max(pts)
    span = (hi - lo) or 1.0
    step = w / (len(pts) - 1)
    xy = [(i * step, h - (v - lo) / span * (h - 14) - 7) for i, v in enumerate(pts)]
    d = " ".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(xy))
    lx, ly = xy[-1]
    return (f'<svg class="spark" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            # The alt text carries the same caveat the visible caption does. A
            # screen reader hearing "warning-sign share" would get exactly the
            # misreading the caption exists to prevent — that this line is the
            # hero's measure over time. It is not.
            f'role="img" aria-label="Direction of our national warning-sign index '
            f'for this metro over the last {len(pts)} months. Different signal set '
            f'from the ratings on this page.">'
            f'<path d="{d}" fill="none" stroke="#1f3a5f" stroke-width="3" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
            f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="5.5" fill="#1f3a5f"/></svg>')


def metro_series(hist, cbsa, n=SPARK_MONTHS):
    """[(month, warning share)] — the share of a metro's scored ZIPs rating
    WATCH or ACT. Counts are [green, yellow, red, strong]; STRONG is an upside
    verdict and stays out of the numerator, matching research.wsi_of()."""
    rows = (hist.get("metros") or {}).get(cbsa) or {}
    out = []
    for m in sorted(rows)[-n:]:
        g, y, r, s = (list(rows[m]) + [0, 0, 0, 0])[:4]
        tot = g + y + r + s
        out.append((m, (100.0 * (y + r) / tot) if tot else None))
    return out


def read_line(share, prev):
    """One plain sentence. No adjective does any work here — the direction and
    the number are the whole read."""
    if prev is None:
        return (f"{share:.0f}% of the ZIP codes we track here are showing at least one "
                f"warning sign today.")
    d = share - prev
    if abs(d) < 0.5:
        return (f"{share:.0f}% of the ZIP codes we track here are showing at least one "
                f"warning sign — about the same as last month.")
    return (f"{share:.0f}% of the ZIP codes we track here are showing at least one "
            f"warning sign, {'up' if d > 0 else 'down'} from {prev:.0f}% last month.")


def zip_row(z, e, places):
    city = places.get(z, ("", ""))[0]
    # These pages list every ZIP in the metro with its rating and dial values.
    # They were never pause-gated, so they kept publishing both for the whole
    # withdrawal — 88 rating words and a column of price changes on the Austin
    # page alone, verified live. A released ZIP still shows its reading.
    if not PAUSE.shows_data(z, e.get("b", PAUSE.LEGACY_BASIS)):
        lvl, m = None, {}
    else:
        lvl = e.get("l")
        m = e.get("m") or {}
    # NO PER-ZIP FIGURES IN THIS TABLE. It used to carry a dial column per ZIP,
    # which made one fetch of a metro page a download of many ZIPs' vendor
    # measurements: 211 of them on /metro/new-york-ny/, and 4,699 distinct ZIPs
    # — 94% of everything released — harvestable in 608 requests against 22,874
    # for the per-ZIP files. Denser than the artifact we removed, and it did not
    # look like a data file, which is why it survived every earlier pass.
    #
    # The rating stays: it is our own derived output, one word, and it is what
    # the table is for. A reader who wants the figures behind it opens that
    # ZIP's page, which is the page-display model the licence question turns on.
    # (Two of the three columns had rendered as em-dashes since the migration
    # anyway — months of supply and price-cut share are v1 signals the engine
    # no longer computes.)
    cells = []
    qual = QUAL.get(lvl, "")
    return (f'<tr><td class="mono"><a href="/zip/{esc(z)}/">{esc(z)}</a></td>'
            f'<td>{esc(city)}</td>'
            f'<td><span class="tag {TAGCLASS.get(lvl, "")}">{esc(WORD.get(lvl, "—"))}</span>'
            + (f'<span class="qual">{esc(qual)}</span>' if qual else "")
            + "</td>" + "".join(cells) + "</tr>")


def page(cbsa, name, zips, entries, places, hist, vel_row, og):
    short = short_metro(name)
    series = metro_series(hist, cbsa)
    # NO `period` PARAMETER ANY MORE. It used to arrive from web/data/meta.json
    # and every date on the page came from it; that value is the last data
    # build's month and has been frozen at 2026-06 since the vendor migration,
    # so all 609 pages were stamped two months behind the readings they show.
    # The date now comes from the readings on THIS page, and is absent when
    # there are none. meta.json's period survives in main() under the name it
    # is still true about — the OG asset folder.
    period = live_period(entries, zips)
    pperiod = pretty_period(period)
    through = f" · data through {esc(pperiod)}" if pperiod else ""
    # Count only ZIPs whose reading may be shown. The hero, the share and the
    # "N of M rate HOLD or better" line are all counted from the rows below
    # them — so when those rows are blanked, counting the underlying records
    # anyway publishes a number the page contradicts. It did: every paused
    # metro read "0 of 83 rate HOLD or better today" above a table of dashes,
    # and the hero claimed a 100% warning share. Not 0 and not 100 — unknown.
    live = [z for z in zips
            if PAUSE.shows_data(z, (entries[z] or {}).get("b", PAUSE.LEGACY_BASIS))]
    scored = len(live)
    total = len(zips)
    # A seller's-market reading (`strong`) crosses no danger line, so it is
    # not a warning — that is why it sits with HOLD here and stays out of the
    # numerator, matching research.wsi_of(). Its ROW now carries a visible
    # "seller's market" qualifier (see QUAL), and the sentences under the
    # table and in the receipt name it as the exception to "count every row
    # tagged WATCH or ACT" — which they have to, because the moment
    # verdict_copy.json resolves this level's word to ACT (the outstanding
    # taxonomy fix; web/methodology.html already publishes it that way) the
    # count and the tag stop agreeing without it.
    holds = sum(1 for z in live if entries[z].get("l") in ("green", "strong"))
    warn = scored - holds

    # THE HERO IS COUNTED FROM THE ROWS BELOW IT, NOT FROM history.json.
    # It used to read the research index, which is a different measure over a
    # different universe: four signals rather than the site's five, and its own
    # scored set. Across 915 metros the two disagreed by 13.4 points on average
    # and by more than 2 points in 722 of them — Grand Rapids shipped "30% rate
    # WATCH or ACT" directly above a table in which 28 of 76 rows were tagged
    # WATCH or ACT. Both numbers were honestly computed; only one of them is
    # about the thing the caption says, and only one can be checked by counting
    # the page. So the hero is now that one, and holds + warn == scored by
    # construction rather than by luck.
    # A SHARE NEEDS ENOUGH ROWS TO BE A SHARE. The guard above covers a fully
    # paused metro (scored == 0). It does not cover a PARTLY released one,
    # which is what a first tranche produces and what nothing had exercised
    # until 2026-08-20: Ann Arbor rendered "100%" in 3.6rem type off two
    # readings, above a table of twelve rows where ten were dashes, and Albany
    # rendered "0%" off one reading among a hundred and two. 108 of the 608
    # pages published an absolute 0% or 100% from fewer than eight readings.
    # The caption said "of the 2" honestly enough, and nobody reads a caption
    # under a number that size. A metro needs MIN_SCORED_FOR_SHARE readings
    # before its warning share is a fact about the metro rather than about
    # which ZIPs happened to be released first — the same floor the page
    # already uses to decide it is worth publishing at all.
    share = (100.0 * warn / scored) if scored >= MIN_SCORED_FOR_SHARE else None
    prev = None
    url = f"{SITE}/metro/{slugify(name)}/"
    title = (f"{short} housing market: is it time to sell?"
             + (f" ({pperiod})" if pperiod else ""))
    desc = (f"{share:.0f}% of the {scored} ZIP codes we track in {short} are showing a "
            f"housing warning sign"
            + (f" as of {pperiod}" if pperiod else "")
            + ". Free per-ZIP readings, updated monthly."
            if share is not None else
            (f"Per-ZIP housing readings for {short} — live for {scored} of {total} "
             f"ZIP codes; the rest are not scored yet."
             if scored else
             f"Per-ZIP housing readings for {short} — {total} ZIP codes tracked. "
             f"{PAUSE.NOTICE_TITLE}."))

    rows = "".join(zip_row(z, entries[z], places)
                   for z in sorted(zips, key=lambda z: (entries[z].get("l") != "red",
                                                        entries[z].get("l") != "yellow", z)))

    # Metro-level velocity is public (velocity-aggregates.json). Per-ZIP
    # velocity is the paid product and appears nowhere on this page.
    # The second figure is the one a marketing post leads with, so it belongs
    # beside the first rather than in a footnote: a reader who tapped "76% are
    # moving toward a danger line" must see 76% here, not hunt for it.
    det = (vel_row or {}).get("share_det")
    det_block, vel = "", ""
    if det is not None:
        # TWO BIG NUMBERS SIDE BY SIDE INVITE ADDING THEM, and these two cannot
        # be added: they measure the same ZIPs two different ways and overlap.
        # A footnote saying so was the tell that the layout was fighting the
        # reader. The trajectory is now a sentence under the hero — subordinate
        # in type, and phrased so the overlap is the point rather than an
        # exception. Only 25 of 608 metros have this figure at all, so the page
        # must read correctly without it, which a sentence does and an empty
        # second column did not.
        det_block = ""
        vel = (f'<p class="trend">But look at where they are heading: '
               f'<b>{det:.0f}% of these same ZIP codes are drifting toward a danger '
               f'line</b> — the level where sellers have historically started losing '
               f'leverage. That includes many that rate HOLD today, and some already '
               f'past a line. It is the same ZIP codes counted a second way, so it '
               f'does not add to the figure above.</p>')

    # The structured dates follow the same rule as the visible stamp: they come
    # from the readings on the page, and a page with no reading asserts no
    # coverage and no publication date rather than inheriting a stale global.
    dataset = {"@type": "Dataset",
               "name": f"{short} per-ZIP housing signals"
                       + (f", {pperiod}" if pperiod else ""),
               "description": desc, "url": url,
               "creator": {"@type": "Organization", "name": "ShouldISellYet",
                           "url": SITE + "/"},
               "isAccessibleForFree": True,
               "license": SITE + "/research/methodology.html"}
    article = {"@type": "Article", "headline": title,
               "mainEntityOfPage": url,
               "author": {"@type": "Organization", "name": "ShouldISellYet Research"},
               "publisher": {"@type": "Organization", "name": "ShouldISellYet",
                             "logo": {"@type": "ImageObject",
                                      "url": SITE + "/apple-touch-icon.png"}}}
    if period:
        dataset["temporalCoverage"] = period
        article["datePublished"] = f"{period}-01"
    jsonld = json.dumps({"@context": "https://schema.org",
                         "@graph": [dataset, article]}, separators=(",", ":"))

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{PAUSE.robots_meta()}
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{url}">
<meta property="og:image" content="{og}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{og}">
<link rel="stylesheet" href="/zip/zip.css">
<link rel="icon" href="/favicon.svg">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#faf8f4">
<!-- Anonymous counting, same as every other page. Five of the fifteen posts in
     the marketing queue land here, and without this their campaign token was
     destroyed on arrival: the post could never be credited with the click it
     caused, and the leaderboard read them as zero rather than as unmeasured.
     track.js honours DNT/GPC and sets no cookie — see its header. -->
<script src="/track.js" defer></script>
<style>
.trend{{margin:14px 0 0;font-size:.95rem;line-height:1.62;color:#5c6673;max-width:70ch}}
.trend b{{color:#1c2430}}
.receipt{{margin:18px 0 0;border:1px solid #e7e2d8;border-radius:10px;background:#fff}}
.receipt summary{{cursor:pointer;padding:13px 16px;font-weight:600;font-size:.92rem}}
.receipt summary::marker{{color:#8a7a55}}
.receipt-body{{padding:0 16px 4px}}
.receipt-body p{{margin:0 0 13px;font-size:.9rem;line-height:1.62;color:#5c6673}}
.receipt-body b{{color:#1c2430}}
</style>
<style>
.spark{{display:block;margin:10px 0 4px;max-width:100%;height:auto}}
.mfigs{{display:flex;gap:34px;flex-wrap:wrap;margin:14px 0 0}}
.mfig{{min-width:150px}}
.mlabel{{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:.625rem;
  letter-spacing:.1em;text-transform:uppercase;color:var(--muted)}}
.mcap{{font-size:.8125rem;color:var(--muted);max-width:190px;line-height:1.35}}
.mhero{{font-family:Georgia,'Newsreader',serif;font-size:clamp(2.4rem,8vw,3.6rem);
  line-height:1;margin:2px 0 2px;color:var(--navy)}}
.msub{{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:.8125rem;
  color:var(--faint-ink);letter-spacing:.04em}}
table.zips{{width:100%;border-collapse:collapse;font-size:.9375rem;margin-top:6px}}
table.zips th{{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:.6875rem;
  letter-spacing:.08em;text-transform:uppercase;color:var(--muted);text-align:left;
  padding:8px 8px;border-bottom:1px solid var(--hairline)}}
table.zips td{{padding:9px 8px;border-bottom:1px solid var(--hairline2)}}
table.zips td.num{{text-align:right;font-variant-numeric:tabular-nums}}
table.zips td.past{{color:#a33;font-weight:600}}
.tag{{display:inline-block;font-family:'IBM Plex Mono',ui-monospace,monospace;
  font-size:.6875rem;letter-spacing:.06em;padding:2px 7px;border-radius:20px;
  border:1px solid var(--hairline)}}
.tag.green{{background:#e9f4ee;border-color:#bcdcc9;color:#1e6b3f}}
.tag.amber{{background:#faf1dd;border-color:#e8d5a8;color:#8a6414}}
.tag.red{{background:#fbe9e9;border-color:#ecc3c3;color:#a33}}
.tag.strong{{background:#e8eef7;border-color:#c3d2e8;color:#1f3a5f}}
/* The seller's-market qualifier. It has to sit BESIDE the word, not behind a
   title attribute: an ACT that means "conditions favour you" and an ACT that
   means "sellers are losing pricing power" cannot be told apart by colour
   alone, and colour is the first thing a screen reader drops. */
.qual{{display:inline-block;margin-left:7px;font-family:'IBM Plex Mono',ui-monospace,monospace;
  font-size:.625rem;letter-spacing:.04em;color:#1f3a5f;white-space:nowrap}}
</style>
<script type="application/ld+json">{jsonld}</script>
</head><body>
<nav class="top">
  <a class="logo" href="/"><img src="/logo-mark.svg" alt="" width="40" height="40" style="display:block"><span class="logo-text"><span class="logo-word">Should I sell yet?</span><span class="logo-tag">LOCAL HOUSING MARKET SIGNALS</span></span></a>
  <a href="/#check" style="font-size:.875rem">Check any ZIP free →</a>
</nav>
<div class="wrap">
  <div class="crumb"><a href="/">Home</a> › <a href="/research/">Research</a> › {esc(short)}</div>

  <!-- The check module sits ABOVE the data: a reader who arrived from a post
       about this metro wants their own ZIP, and making them scroll past a
       table of other people's ZIP codes to find the box is a tax on the one
       action this page exists to produce. -->
  <div class="answer" style="margin:14px 0 18px">
    <b>Check your own ZIP code, free.</b>
    <form action="/" method="get" style="display:flex;gap:8px;margin-top:8px;flex-wrap:wrap">
      <input name="zip" inputmode="numeric" maxlength="5" pattern="\\d{{5}}"
             placeholder="ZIP code" aria-label="ZIP code"
             style="flex:1;min-width:140px;font-family:'IBM Plex Mono',monospace;
                    font-size:1rem;padding:11px 14px;border:1.5px solid #d7d0c2;
                    border-radius:8px;background:#fff">
      <button class="btn btn-primary" type="submit">Check my ZIP — free</button>
    </form>
  </div>

  <h1 style="margin:0">{esc(short)}</h1>
  <div class="msub">{esc(name)}{through}</div>
  <div class="mfigs">
    <div class="mfig">
      <div class="mlabel">Where they stand today</div>
      <div class="mhero">{f"{share:.0f}%" if share is not None else "—"}</div>
      <div class="mcap">{f"of the {scored} ZIP codes we track here rate WATCH or ACT" if share is not None else (f"of the {total} ZIP codes we track here, {scored} {'has' if scored == 1 else 'have'} a live reading — too few to give the metro a share yet" if scored else f"readings for the {total} ZIP codes we track here are not live yet")}</div>
    </div>
    {det_block}
  </div>
  <p style="margin:10px 0 0">{esc(read_line(share, prev)) if share is not None else ""}</p>
  {vel}
  {spark(series)}
  <div class="msub">{esc(spark_caption(series))}</div>

  <h2>Every ZIP code we track here</h2>
  <p class="note">{f"{holds} of {scored} rate HOLD or better today." if share is not None else (f"{holds} of the {scored} ZIP codes with a live reading rate HOLD or better; the rest are not scored yet." if scored else PAUSE.NOTICE_BODY)} A row marked
  <i>seller's market</i> crosses no danger line — conditions there favour a
  seller rather than turning against one. Tap a ZIP for its full reading.</p>
  <div style="overflow-x:auto">
  <table class="zips"><thead><tr><th>ZIP</th><th>City</th><th>Rating</th>
  </tr></thead><tbody>{rows}</tbody></table></div>

  <details class="receipt">
    <summary>Behind this number</summary>
    <div class="receipt-body">
      <p><b>What goes in.</b> Every ZIP code we track in this metro — {total} of
      them, {scored} with a live reading. A ZIP shows a reading when its licensed
      active-listing statistics are complete enough to score; the rest carry a
      note that the reading is not live yet, rather than a guess.</p>
      <p><b>The maths.</b> {f"{warn} of those {scored} ZIP codes show at least one signal past its danger line, which is {share:.0f}%. You can count them in the table above: every row tagged WATCH or ACT. A row marked seller's market crosses no line and is not among them." if share is not None else (f"{scored} of the {total} ZIP codes here have a live reading, of which {warn} show at least one signal past its danger line. That is too few to state a share for the metro — the rest are not scored yet." if scored else PAUSE.NOTICE_BODY)}</p>
      <p><b>Why there is a line at all.</b> Each danger line is the level at which,
      in past downturns, that signal began leading price declines rather than
      following them. The lines are fixed, published, and identical for every ZIP
      code in the country — we do not tune them per market.</p>
      <p><b>Where it comes from.</b> Licensed market statistics, refreshed when a
      new release publishes{f"; this page is data through {esc(pperiod)}" if pperiod else ""}. Full derivation on
      the <a href="/methodology">methodology page</a>.</p>
    </div>
  </details>

  <p class="note" style="margin-top:14px">Readings and danger lines are defined on the
  <a href="/methodology">methodology page</a>.{f" Data through {esc(pperiod)}." if pperiod else ""} Refreshed
  when a new release publishes.</p>
</div>
<footer class="stamp">ShouldISellYet Research{through} ·
<a href="/research/">monthly national report</a><br>{DISCLAIMER}</footer>
</body></html>"""


def redirect_page(dest, note):
    """A static redirect. GitHub Pages has no server, so every "route" that is
    not a real directory is one of these — the same shim /s/{zip} uses."""
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="robots" content="noindex,nofollow">'
            f'<title>ShouldISellYet</title>'
            f'<link rel="canonical" href="{dest}">'
            # THE QUERY AND THE FRAGMENT BOTH HAVE TO SURVIVE.
            #
            # The fragment, because /methodology#backtest is only useful if the
            # hash reaches the real page, and this is the route every receipt
            # and social post uses.
            #
            # The query, because it carries the campaign. A /go/ link resolves
            # to /methodology/?utm_source=fb&utm_campaign=... and this shim then
            # threw the parameters away, so track.js on the destination saw a
            # bare visit: the post could never be credited with the click it
            # caused. That is a silent failure — the link works, the reader
            # arrives, and only the leaderboard is wrong.
            #
            # Merged rather than concatenated so a destination that already has
            # its own query cannot produce two "?" — /s/{zip} uses this same
            # shim and may grow one.
            f'<script>(function(d){{try{{var u=new URL(d);'
            f'new URLSearchParams(location.search).forEach(function(v,k){{'
            f'u.searchParams.set(k,v)}});u.hash=location.hash;'
            f'location.replace(u.toString())}}catch(e){{location.replace(d)}}}})'
            f'({json.dumps(dest)});</script>'
            # No-JS fallback: cannot carry a runtime value, so it lands on the
            # destination without the campaign. Correct page, uncredited visit.
            f'<meta http-equiv="refresh" content="0;url={dest}">'
            f'<style>body{{font-family:system-ui,-apple-system,sans-serif;'
            f'background:#faf8f4;color:#5c6673;padding:40px 20px;text-align:center}}'
            f'a{{color:#1f3a5f}}</style></head><body>'
            f'<p>{esc(note)} <a href="{dest}">continue</a></p></body></html>')


def hub_page(index, names, period):
    """/metro/ — every metro page, so they are reachable and crawlable rather
    than only linkable from a post.

    `period` is the as-of month of the readings behind these pages (see
    live_period), and is "" when none of them is showing one — in which case
    the hub carries no date rather than a stale one.
    """
    pperiod = pretty_period(period)
    through = f" · data through {esc(pperiod)}" if pperiod else ""
    items = "".join(
        f'<li><a href="/metro/{esc(s)}/">{esc(short_metro(names[c]))}</a></li>'
        for s, c in sorted(index.items(), key=lambda kv: short_metro(names[kv[1]])))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
{PAUSE.robots_meta()}
<title>Housing market by metro area — ShouldISellYet</title>
<meta name="description" content="Per-ZIP housing readings for {len(index)} U.S. metro areas, updated monthly.">
<link rel="canonical" href="{SITE}/metro/">
<link rel="stylesheet" href="/zip/zip.css">
<link rel="icon" href="/favicon.svg">
<script src="/track.js" defer></script>
<style>.hubgrid{{columns:3;column-gap:26px}}@media(max-width:700px){{.hubgrid{{columns:2}}}}
.hubgrid li{{break-inside:avoid;list-style:none;padding:3px 0;font-size:.9375rem}}</style>
</head><body>
<nav class="top">
  <a class="logo" href="/"><img src="/logo-mark.svg" alt="" width="40" height="40" style="display:block"><span class="logo-text"><span class="logo-word">Should I sell yet?</span><span class="logo-tag">LOCAL HOUSING MARKET SIGNALS</span></span></a>
  <a href="/#check" style="font-size:.875rem">Check any ZIP free →</a>
</nav>
<div class="wrap">
  <div class="crumb"><a href="/">Home</a> › Metro areas</div>
  <h1>Housing market by metro area</h1>
  <p>Per-ZIP readings for {len(index)} metro areas{f", data through {esc(pperiod)}" if pperiod else ""}.</p>
  <ul class="hubgrid">{items}</ul>
</div>
<footer class="stamp">ShouldISellYet Research{through}<br>{DISCLAIMER}</footer>
</body></html>"""


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default=str(ROOT / "web"))
    ap.add_argument("--only", default="", help="comma-separated CBSA codes (smoke tests)")
    ap.add_argument("--min-zips", type=int, default=MIN_ZIPS)
    args = ap.parse_args(argv)
    web = Path(args.web)

    meta_p = web / "data" / "meta.json"
    if not meta_p.exists():
        print("build_metro: no web/data/meta.json — nothing to build")
        return 0
    # meta.json's `period` is the last DATA BUILD's month, frozen at the final
    # Redfin run. It still keys the pre-rendered OG asset folders under
    # web/assets/mkt/{period}/, which is the only thing it is still true about
    # — so it is named for that job and never reaches a reader. Reader-facing
    # dates come from live_period(), off the readings themselves.
    asset_period = json.loads(meta_p.read_text()).get("period", "")

    hist_p = ROOT / "pipeline" / "research" / "history.json"
    if not hist_p.exists():
        print("build_metro: no research history — metro pages need the trend; skipped")
        return 0
    hist = json.loads(hist_p.read_text())
    names = {c: v[0] for c, v in (hist.get("metro_names") or {}).items()}

    entries = load_entries(web / "data")
    places, zip_cbsa = load_places(), load_zip_cbsa()
    vel = {}
    vp = web / "data" / "velocity-aggregates.json"
    if vp.exists():
        vel = {g["cbsa"]: g for g in (json.loads(vp.read_text()).get("gathering") or [])}

    by_metro = {}
    for z in entries:
        c = zip_cbsa.get(z)
        if c and c in names:
            by_metro.setdefault(c, []).append(z)

    only = {c.strip() for c in args.only.split(",") if c.strip()}
    stage = web / ".metro-build"
    if stage.exists():
        import shutil
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    index, n = {}, 0
    for cbsa, zips in sorted(by_metro.items()):
        if only and cbsa not in only:
            continue
        if len(zips) < args.min_zips:
            continue
        name = names[cbsa]
        s = slugify(name)
        if s in index:                      # verified zero today; refuse to guess
            print(f"build_metro: slug collision {s!r} ({index[s]} vs {cbsa}) — skipped")
            continue
        og = f"{SITE}/assets/mkt/{asset_period}/mq-{asset_period}-flip-{cbsa}.png"
        if not (web / "assets" / "mkt" / asset_period /
                f"mq-{asset_period}-flip-{cbsa}.png").exists():
            og = f"{SITE}/og/default.png"
        d = stage / s
        d.mkdir(parents=True)
        (d / "index.html").write_text(
            page(cbsa, name, zips, entries, places, hist, vel.get(cbsa), og),
            encoding="utf-8")
        index[s] = cbsa
        n += 1

    # slug -> cbsa, committed so the generator can resolve a link target without
    # rebuilding the site, and so the lint can prove a destination exists.
    (ROOT / "pipeline" / "data" / "metro_slugs.json").write_text(
        json.dumps(index, separators=(",", ":"), sort_keys=True))

    # The hub is dated from every reading it points at, not from the data build.
    hub_period = live_period(entries)
    (stage / "index.html").write_text(hub_page(index, names, hub_period),
                                      encoding="utf-8")

    final = web / "metro"
    if final.exists():
        import shutil
        shutil.rmtree(final)
    stage.rename(final)
    # /methodology is the path every definition links to. It used to redirect
    # to /research/methodology.html — but that document describes the
    # Warning-Sign Index, a deliberately FROZEN four-signal series kept
    # comparable month to month, not how a current ZIP reading is computed.
    # Every "see our methodology" link on the site therefore delivered a reader
    # to a paper about a different metric. It now points at the site's own
    # methodology page, which states the sources, the active-listing basis, the
    # three signals and their lines, and the refresh cadence.
    meth = web / "methodology"
    meth.mkdir(parents=True, exist_ok=True)
    (meth / "index.html").write_text(
        redirect_page(f"{SITE}/methodology.html",
                      "Taking you to the methodology…"), encoding="utf-8")

    print(f"build_metro: {n} metro page(s) + hub + /methodology · "
          f"min {args.min_zips} ZIPs · readings as of {hub_period or 'none'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
