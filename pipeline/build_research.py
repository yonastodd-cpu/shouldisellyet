#!/usr/bin/env python3
"""ShouldISellYet Research — static release pages, charts, and CSVs.

    python3 pipeline/build_research.py [--web web]

Builds, from committed research JSONs only (no network — this runs on every
deploy exactly like build_pages.py, so a site-only push can never delete the
research section):

  web/research/index.html            hub: current WSI, chart, release list
  web/research/{yyyy-mm}/index.html  one release, seven-part structure
  web/research/{yyyy-mm}/*.png       WSI chart + state map, 1200×675,
                                     attribution and data-through baked in
  web/research/{yyyy-mm}/*.csv       state/metro aggregates, flip list,
                                     national WSI history
  web/research/{yyyy-mm}/LICENSE.txt free with citation

The CSVs carry ONLY derived fields — verdict counts, warning shares, deltas,
flips. No upstream Redfin/Realtor metric columns ship here: the verdict layer
is ours to give away; their raw data is not ours to redistribute.
"""

import argparse
import csv
import html as _html
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from research import (RESEARCH_DIR, national_series, load_history, pretty,
                      prev_month, region_share, unpack)

ROOT = Path(__file__).resolve().parents[1]
FONTS = Path(__file__).parent / "fonts"
SITE = "https://shouldisellyet.com"

esc = lambda s: _html.escape(str(s), quote=True)

# Site palette (mirrors og_card.py)
BG = (250, 248, 244)
INK = (28, 36, 48)
MUTED = (92, 102, 115)
FAINT = (138, 133, 120)
HAIRLINE = (231, 226, 216)
NAVY = (31, 58, 95)
GREEN = (46, 158, 91)
AMBER = (200, 137, 31)
RED = (214, 69, 69)

CITE = ('Data provided by <a href="https://www.redfin.com" target="_blank" '
        'rel="noopener">Redfin</a>, a national real estate brokerage · '
        'Listing data from Realtor.com&reg; Economic Research · Place names '
        'from <a href="https://www.geonames.org" target="_blank" '
        'rel="noopener">GeoNames</a> (CC BY 4.0)')

STATE_NAMES = {
    "AL":"Alabama","AK":"Alaska","AZ":"Arizona","AR":"Arkansas","CA":"California","CO":"Colorado",
    "CT":"Connecticut","DE":"Delaware","DC":"District of Columbia","FL":"Florida","GA":"Georgia",
    "HI":"Hawaii","ID":"Idaho","IL":"Illinois","IN":"Indiana","IA":"Iowa","KS":"Kansas","KY":"Kentucky",
    "LA":"Louisiana","ME":"Maine","MD":"Maryland","MA":"Massachusetts","MI":"Michigan","MN":"Minnesota",
    "MS":"Mississippi","MO":"Missouri","MT":"Montana","NE":"Nebraska","NV":"Nevada","NH":"New Hampshire",
    "NJ":"New Jersey","NM":"New Mexico","NY":"New York","NC":"North Carolina","ND":"North Dakota",
    "OH":"Ohio","OK":"Oklahoma","OR":"Oregon","PA":"Pennsylvania","RI":"Rhode Island","SC":"South Carolina",
    "SD":"South Dakota","TN":"Tennessee","TX":"Texas","UT":"Utah","VT":"Vermont","VA":"Virginia",
    "WA":"Washington","WV":"West Virginia","WI":"Wisconsin","WY":"Wyoming","PR":"Puerto Rico",
}

# Tile-grid map coordinates (col, row) — the newsroom-standard arrangement,
# chosen over a projected choropleth on purpose: every state gets equal,
# labelable area (a real map makes RI invisible and MT enormous), and it
# renders deterministically in Pillow with no geo dependencies.
TILE = {
    "AK":(0,0), "ME":(11,0),
    "VT":(10,1), "NH":(11,1),
    "WA":(1,2), "ID":(2,2), "MT":(3,2), "ND":(4,2), "MN":(5,2), "IL":(6,2),
    "WI":(7,2), "MI":(8,2), "NY":(9,2), "RI":(10,2), "CT":(11,2),
    "OR":(1,3), "NV":(2,3), "WY":(3,3), "SD":(4,3), "IA":(5,3), "IN":(6,3),
    "OH":(7,3), "PA":(8,3), "NJ":(9,3), "MA":(10,3),
    "CA":(1,4), "UT":(2,4), "CO":(3,4), "NE":(4,4), "MO":(5,4), "KY":(6,4),
    "WV":(7,4), "VA":(8,4), "MD":(9,4), "DE":(10,4),
    "AZ":(2,5), "NM":(3,5), "KS":(4,5), "AR":(5,5), "TN":(6,5), "NC":(7,5),
    "SC":(8,5), "DC":(9,5),
    "OK":(4,6), "LA":(5,6), "MS":(6,6), "AL":(7,6), "GA":(8,6),
    "HI":(0,7), "TX":(4,7), "FL":(9,7),
}

_fc = {}
def font(name, size):
    from PIL import ImageFont
    if (name, size) not in _fc:
        _fc[(name, size)] = ImageFont.truetype(str(FONTS / name), size)
    return _fc[(name, size)]

BOLD, REG = "IBMPlexMono-Bold.ttf", "IBMPlexMono-Regular.ttf"


def ramp(share):
    """0→green, 50→amber, 100→red, linear between."""
    if share is None:
        return HAIRLINE
    t = max(0.0, min(100.0, share))
    a, b, f = (GREEN, AMBER, t / 50.0) if t <= 50 else (AMBER, RED, (t - 50) / 50.0)
    return tuple(round(a[i] + (b[i] - a[i]) * f) for i in range(3))


def _attrib(d, w, h, month, extra=""):
    line = f"ShouldISellYet Research · data through {pretty(month)} · {SITE}/research/"
    if extra:
        line = extra + " · " + line
    f = font(REG, 17)
    d.text((w // 2 - d.textlength(line, font=f) // 2, h - 34), line, font=f, fill=FAINT)


# ————— chart 1: the WSI time series —————

def wsi_chart(series, records, changelog, out, w=1200, h=675, seam=None):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    cur_m, cur_v = series[-1]

    d.text((60, 44), "WARNING-SIGN INDEX", font=font(BOLD, 30), fill=INK)
    d.text((60, 84), "Share of scored U.S. ZIP markets at WATCH or ACT",
           font=font(REG, 19), fill=MUTED)
    big = f"{cur_v:.1f}%"
    fb = font(BOLD, 64)
    d.text((w - 60 - d.textlength(big, font=fb), 36), big, fill=NAVY, font=fb)
    delta = records.get("delta")
    if delta is not None:
        dtxt = f"{'+' if delta >= 0 else '−'}{abs(delta):.1f} pts vs prior month"
        fd = font(REG, 18)
        d.text((w - 60 - d.textlength(dtxt, font=fd), 106), dtxt,
               fill=(RED if delta > 0 else GREEN) if delta else MUTED, font=fd)

    # plot area
    x0, y0, x1, y1 = 60, 160, w - 60, h - 90
    vals = [v for _, v in series]
    vmax = max(60.0, max(vals) + 4)
    vmin = max(0.0, min(vals) - 4)

    def X(i):
        return x0 + (x1 - x0) * (i / max(1, len(series) - 1))

    def Y(v):
        return y1 - (y1 - y0) * ((v - vmin) / (vmax - vmin))

    for gv in range(0, 101, 10):
        if vmin <= gv <= vmax:
            d.line([(x0, Y(gv)), (x1, Y(gv))], fill=HAIRLINE, width=1)
            d.text((x0 - 12 - d.textlength(f"{gv}", font=font(REG, 15)), Y(gv) - 9),
                   f"{gv}", font=font(REG, 15), fill=FAINT)
    years = sorted({m[:4] for m, _ in series})
    for yr in years:
        idx = next(i for i, (m, _) in enumerate(series) if m.startswith(yr))
        if idx:
            d.line([(X(idx), y0), (X(idx), y1)], fill=HAIRLINE, width=1)
        if int(yr) % 2 == 0 or len(years) <= 8:
            d.text((X(idx) + 4, y1 + 8), yr, font=font(REG, 15), fill=FAINT)

    # methodology-version annotations (T5 changelog): a tick + label at the
    # month a definition changed, so no reader mistakes a redefinition for news
    for entry in changelog:
        if entry.get("annotate") is False:
            continue
        m = entry.get("month")
        idx = next((i for i, (mm, _) in enumerate(series) if mm == m), None)
        if idx is not None:
            d.line([(X(idx), y0), (X(idx), y1)], fill=AMBER, width=2)
            d.text((X(idx) + 5, y0 + 2), f"v{entry['version']}",
                   font=font(BOLD, 14), fill=AMBER)

    # Two strokes, one chart: the pre-seam reconstruction (smaller legacy
    # universe) draws lighter so nobody reads a superlative across it; the
    # continuous series — where records live — is the full-weight line.
    pts = [(X(i), Y(v)) for i, (_, v) in enumerate(series)]
    cut = next((i for i, (m, _) in enumerate(series) if seam and m >= seam), 0)
    if seam and 0 < cut < len(series):
        # Deliberately NOT connected across the seam: the two segments are
        # different source vintages, and a connecting stroke would draw a
        # cliff that reads as a market move. The gap plus the label is the
        # honest rendering.
        d.line(pts[:cut], fill=(167, 178, 196), width=3, joint="curve")
        d.line([(X(cut), y0), (X(cut), y1)], fill=FAINT, width=1)
        lbl = "continuous series begins"
        d.text((X(cut) + 6, y1 - 24), lbl, font=font(REG, 14), fill=FAINT)
        d.line(pts[cut:], fill=NAVY, width=4, joint="curve")
    else:
        d.line(pts, fill=NAVY, width=4, joint="curve")
    cx, cy = pts[-1]
    d.ellipse([cx - 7, cy - 7, cx + 7, cy + 7], fill=NAVY, outline=BG, width=3)

    _attrib(d, w, h, cur_m)
    img.save(out, "PNG", optimize=True)


# ————— chart 2: the state tile map —————

def state_map(per_state, month, out, w=1200, h=675):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    d.text((60, 40), "WARNING SIGNS BY STATE", font=font(BOLD, 30), fill=INK)
    d.text((60, 80), "Share of each state's scored ZIP markets at WATCH or ACT",
           font=font(REG, 19), fill=MUTED)

    # Sized so all 8 tile rows land inside 675px WITH the attribution clear:
    # 8 × (58+5) = 504 from oy 108 → bottom 612; attribution baseline ~641.
    # The first cut used 76px cells and pushed Texas and Florida off the
    # canvas — measured, not assumed, hence the arithmetic in this comment.
    # No separate legend: every tile carries its own percentage, so a colour
    # bar would restate what the labels already say.
    cols = 12
    cell, gap = 58, 5
    gw = cols * cell + (cols - 1) * gap
    ox = (w - gw) // 2
    oy = 108
    for st, (c, r) in TILE.items():
        e = per_state.get(st)
        share = e.get("share") if e else None
        x, y = ox + c * (cell + gap), oy + r * (cell + gap)
        col = ramp(share)
        d.rounded_rectangle([x, y, x + cell, y + cell], radius=8, fill=col)
        lum = 0.2126 * col[0] + 0.7152 * col[1] + 0.0722 * col[2]
        ink = (255, 255, 255) if lum < 150 else INK
        d.text((x + 8, y + 7), st, font=font(BOLD, 16), fill=ink)
        label = "—" if share is None else f"{share:.0f}%"
        d.text((x + 8, y + cell - 24), label, font=font(REG, 14), fill=ink)

    _attrib(d, w, h, month)
    img.save(out, "PNG", optimize=True)


# ————— OG stat card + social set (T4) —————

def og_card(rep, out, w=1200, h=630):
    """The release URL's share image: the headline stat, nothing else. A
    chart thumbnail dies at feed size; one enormous number does not."""
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), (20, 26, 20))
    d = ImageDraw.Draw(img)
    CREAM = (242, 241, 236)
    GOLD = (217, 154, 43)
    rec = rep["records"]
    d.text((70, 64), "WARNING-SIGN INDEX", font=font(BOLD, 34), fill=GOLD)
    big = f"{rec['wsi']:.1f}%"
    d.text((62, 130), big, font=font(BOLD, 230), fill=CREAM)
    sub = "of scored U.S. ZIP housing markets"
    d.text((70, 400), sub, font=font(REG, 34), fill=CREAM)
    d.text((70, 444), "show warning signs", font=font(REG, 34), fill=CREAM)
    delta = rec.get("delta")
    if delta is not None:
        # The triangle is DRAWN, not typed: IBM Plex Mono has no ▲/▼ glyphs
        # and the fallback tofu box shipped in the first render of this card.
        arrowc = (212, 130, 120) if delta > 0 else (140, 190, 150)
        ax, ay, s2 = 70, 514, 22
        if delta > 0:
            d.polygon([(ax, ay + s2), (ax + s2, ay + s2), (ax + s2 // 2, ay)], fill=arrowc)
        else:
            d.polygon([(ax, ay), (ax + s2, ay), (ax + s2 // 2, ay + s2)], fill=arrowc)
        d.text((ax + s2 + 14, 508), f"{abs(delta):.1f} pts vs prior month",
               font=font(BOLD, 28), fill=arrowc)
    line = f"{rep['pretty_month']} · ShouldISellYet Research"
    d.text((70, h - 60), line, font=font(REG, 24), fill=(154, 160, 150))
    img.save(out, "PNG", optimize=True)


def _social_frame(title_lines, month, w=1080, h=1350):
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)
    y = 64
    for i, t in enumerate(title_lines):
        d.text((64, y), t, font=font(BOLD, 46 if i == 0 else 30),
               fill=INK if i == 0 else MUTED)
        y += 62 if i == 0 else 44
    f = font(REG, 22)
    line = f"ShouldISellYet Research · {pretty(month)} · {SITE}/research/"
    d.text((64, h - 70), line, font=f, fill=FAINT)
    return img, d


def social_set(rep, series, outdir):
    """Four 1080×1350 images matching the social pillars, dropped beside the
    release so the week's posting is a pick-and-post, not a design task."""
    from PIL import Image
    month = rep["month"]
    rec = rep["records"]
    sdir = outdir / "social"
    sdir.mkdir(exist_ok=True)

    # 1 — the WSI number + trend (crop the landscape chart into the frame)
    img, d = _social_frame(
        [f"Warning signs: {rec['wsi']:.1f}% of U.S. ZIP markets",
         "The Warning-Sign Index, monthly since 2020 (context to 2012)"], month)
    chart = Image.open(outdir / "wsi-chart.png")
    cw = 1080 - 128
    ch = round(chart.height * cw / chart.width)
    img.paste(chart.resize((cw, ch)), (64, 240))
    img.save(sdir / "1-wsi.png", "PNG", optimize=True)

    # 2 — the state map
    img, d = _social_frame(
        ["Warning signs, state by state",
         "Share of each state's scored ZIP markets at WATCH or ACT"], month)
    m = Image.open(outdir / "state-map.png")
    mw = 1080 - 96
    mh = round(m.height * mw / m.width)
    img.paste(m.resize((mw, mh)), (48, 300))
    img.save(sdir / "2-map.png", "PNG", optimize=True)

    # 3 — the deteriorating-metros table
    img, d = _social_frame(
        ["Metros deteriorating fastest",
         "Change in warning share vs last month, pts"], month)
    y = 260
    for i, r in enumerate(rep["metros_deteriorating"][:8], 1):
        name = r["name"].split(",")[0][:26]
        st = r["name"].split(",")[-1].strip()[:6]
        d.text((64, y), f"{i}.", font=font(BOLD, 34), fill=FAINT)
        d.text((128, y), f"{name}, {st}", font=font(BOLD, 34), fill=INK)
        val = f"+{r['delta']:.1f}"
        d.text((1080 - 64 - d.textlength(val, font=font(BOLD, 34)), y), val,
               font=font(BOLD, 34), fill=RED)
        d.text((128, y + 44), f"warning share {r['share']:.1f}%",
               font=font(REG, 24), fill=MUTED)
        y += 100
    img.save(sdir / "3-metros.png", "PNG", optimize=True)

    # 4 — the local spotlight: longest current warning streak
    img, d = _social_frame(["Local spotlight", ""], month)
    ts = rep["top_streaks"][:1]
    if ts:
        s = ts[0]
        place = f"{s['city']}, {s['state']}" if s["city"] else s["state"]
        d.text((64, 240), s["zip"], font=font(BOLD, 150), fill=NAVY)
        d.text((64, 420), place[:30], font=font(BOLD, 44), fill=INK)
        d.text((64, 500), f"{s['months']} consecutive months", font=font(BOLD, 60), fill=RED)
        d.text((64, 580), "showing market warning signs", font=font(REG, 34), fill=MUTED)
        d.text((64, 660), "The longest current streak of any", font=font(REG, 30), fill=MUTED)
        d.text((64, 700), "scored U.S. ZIP market.", font=font(REG, 30), fill=MUTED)
    img.save(sdir / "4-spotlight.png", "PNG", optimize=True)



# ————— methodology page (T5) —————

def methodology_page(h, changelog, outdir):
    seam = h.get("seam", "")
    entries = "".join(
        f'<tr><td class="mono">v{esc(e["version"])}</td>'
        f'<td class="mono">{esc(pretty(e["month"]))}</td>'
        f'<td>{esc(e["note"])}</td></tr>'
        for e in sorted(changelog, key=lambda e: e["month"], reverse=True))
    backtest = ""
    meta_p = ROOT / "web" / "data" / "meta.json"
    if meta_p.exists():
        bt = json.loads(meta_p.read_text()).get("national", {}).get("backtest")
        if bt:
            sig_names = {"mos": "Months of supply > 4", "price": "Prices falling y/y",
                         "dom": "Time-to-sell up > 40% y/y", "inv": "Inventory up > 50% y/y"}
            rows = "".join(
                f'<tr><td>{esc(nm)}</td>'
                f'<td class="n">{bt["sig"][k]["x"]:.1f}%</td>'
                f'<td class="n">{bt["sig"][k]["c"]:.1f}%</td></tr>'
                for k, nm in sig_names.items() if k in bt.get("sig", {}))
            backtest = f"""
<h2>The danger lines are backtested</h2>
<p>Each signal's threshold was tested against the FHFA's official ZIP-level
house-price outcomes ({bt.get("n", 0):,} zip-year pairs, {bt.get("y0")}–{bt.get("y1")},
outcomes through {bt.get("fhfa")}): of markets past a line at year-end, the share whose
FHFA index declined the following year, versus markets clear of it.</p>
<table><thead><tr><th>Signal crossed</th><th>Declined next year</th><th>Clear of the line</th></tr></thead>
<tbody>{rows}</tbody></table>
<p class="note">Warning ≠ crash: a WATCH/ACT market is one where decline risk is
elevated versus baseline, not one guaranteed to fall. The full backtest method is
described on the <a href="/">homepage's signal explanations</a>.</p>"""

    body = f"""
<div class="eyebrow">SHOULDISELLYET RESEARCH</div>
<h1>Warning-Sign Index — methodology</h1>
<p class="lede">Everything needed to check, reuse, or challenge the number.
The definition is versioned; changes are listed at the bottom and annotated
on the chart at the month they take effect. History is restated on cutover,
never silently redefined.</p>

<h2>Definition</h2>
<p><b>WSI = ZIP markets at WATCH or ACT ÷ all scored ZIP markets</b>, as a
percentage, computed monthly. A ZIP is <b>scored</b> when at least two of the
four index signals are known for the month. Insufficient-data ZIPs are
excluded from both numerator and denominator. STRONG (seller's-market)
verdicts count in the denominator only.</p>

<h2>The four signals</h2>
<p>Identical thresholds to the site's published danger lines, evaluated by
the same verdict engine — restated on a constant four-signal basis so every
month of the series measures the same thing:</p>
<table><thead><tr><th>Signal</th><th>Danger line</th></tr></thead><tbody>
<tr><td>Months of supply</td><td class="mono">&gt; 4 (severe &gt; 6)</td></tr>
<tr><td>Median sale price, y/y</td><td class="mono">&lt; −2% (fast &lt; −5%)</td></tr>
<tr><td>Time to sell, y/y</td><td class="mono">&gt; +40%</td></tr>
<tr><td>Inventory, y/y</td><td class="mono">&gt; +50%</td></tr>
</tbody></table>
<p class="note">The site's per-ZIP verdicts additionally use the share of
listings with price cuts (&gt; 35%) where Redfin publishes it. That signal has
no history before 2026 and is deliberately excluded from the index; measured
impact of the exclusion at adoption was 0.2 points (62.2% vs 62.4%).</p>

<h2>Sources and the seam</h2>
<p>The <b>continuous series</b> begins {esc(pretty(seam))}: Redfin Data Center
hub data, the same file the site refreshes from, ~25,000 scored ZIPs per
month. The <b>2012–2019 tail</b> is reconstructed from Redfin's legacy market
tracker (~18,000 ZIPs, a prior universe), drawn in a lighter stroke, and
<b>excluded from every record, delta, and superlative</b>. The two sources
overlap for 72 months; per-ZIP level agreement across 1.36M shared zip-months
is 72.7% — similar, not the same, which is exactly why claims never reach
across the seam. The current month is always computed from the site's own
published per-ZIP data, so the index and the ZIP pages a reader can check
agree by construction.</p>

<h2>Records and streaks</h2>
<p>"Highest since {{month}}" names the last month the index was <b>at or
above</b> the current value — ties block the bigger claim, so no superlative
can contradict the archive. "Record" always means "within the continuous
series", never "ever". ZIP warning streaks count consecutive months at WATCH
or ACT; a month without a score breaks the streak.</p>

<h2>Metro definitions</h2>
<p>ZIPs map to Metropolitan Statistical Areas via the Census 2020
ZCTA↔county relationship file (largest land-overlap county per ZCTA) chained
to the OMB 2023 CBSA delineation — the same definitions the press already
uses. ZCTAs approximate ZIP codes; the divergence is the standard documented
compromise, because USPS publishes no ZIP geography. Metro league tables
require ≥ 15 scored ZIPs.</p>
{backtest}

<h2>Use and citation</h2>
<p>Index values, league tables, and release CSVs are free to use, chart, and
republish with citation: <b>"Source: ShouldISellYet Research."</b> The CSVs
carry ShouldISellYet's derived indicators only — never upstream raw metrics,
which belong to their publishers. Media/data questions:
<a href="mailto:press@shouldisellyet.com">press@shouldisellyet.com</a>.</p>

<h2>Changelog</h2>
<table><thead><tr><th>Version</th><th>Effective</th><th>Change</th></tr></thead>
<tbody>{entries}</tbody></table>
"""
    (outdir / "methodology.html").write_text(page(
        "Warning-Sign Index methodology — ShouldISellYet Research",
        "Definition, danger lines, sources, the seam, records rules, metro "
        "mapping, FHFA backtest, and the versioned changelog.",
        f"{SITE}/research/methodology.html", body))

# ————— html scaffolding —————

def page(title, desc, canonical, body, og_image="", jsonld=""):
    og = (f'<meta property="og:image" content="{og_image}">'
          '<meta name="twitter:card" content="summary_large_image">'
          f'<meta name="twitter:image" content="{og_image}">') if og_image else ""
    if jsonld:
        og += f'<script type="application/ld+json">{jsonld}</script>'
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self' https://kfbjooteazwvdsonthba.supabase.co; img-src 'self' data:; object-src 'none'; base-uri 'self'">
<meta name="referrer" content="strict-origin-when-cross-origin">
<script src="/track.js" defer></script>
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{canonical}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">{og}
<link rel="icon" href="/favicon.svg">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<meta name="theme-color" content="#faf8f4">
<link href="https://fonts.googleapis.com/css2?family=Archivo:wght@500;700&family=Newsreader:ital,opsz,wght@0,6..72,400..700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
:root{{--bg:#faf8f4;--ink:#1c2430;--muted:#5c6673;--faint:#8a8578;--fainter:#a49d8d;
--hairline:#e7e2d8;--hairline2:#f0ebe0;--navy:#1f3a5f;--gold:#8a7a55;
--green:#2e9e5b;--amber:#c8891f;--red:#d64545}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,sans-serif;font-size:1.0625rem;line-height:1.6}}
a{{color:var(--navy)}}
.mono{{font-family:'IBM Plex Mono',monospace}}
nav{{display:flex;align-items:center;justify-content:space-between;padding:16px 20px;border-bottom:1px solid var(--hairline);max-width:900px;margin:0 auto}}
.logo{{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}}
.logo-text{{display:flex;flex-direction:column;gap:2px}}
.logo-word{{font-family:'Archivo',system-ui,sans-serif;font-weight:700;font-size:17px;letter-spacing:-.022em;line-height:1}}
.logo-tag{{font-family:'Archivo',system-ui,sans-serif;font-weight:500;font-size:7.75px;letter-spacing:.22em;line-height:1;color:#8a8d86;white-space:nowrap}}
.wrap{{max-width:900px;margin:0 auto;padding:34px 20px 80px}}
.eyebrow{{font-family:'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.14em;color:var(--gold)}}
h1{{font-family:'Newsreader',serif;font-weight:500;font-size:clamp(1.7rem,3.4vw,2.4rem);line-height:1.15;margin:10px 0 8px}}
h2{{font-family:'Newsreader',serif;font-weight:600;font-size:1.35rem;margin:36px 0 10px}}
.lede{{font-size:1.15rem;color:var(--muted);max-width:64ch}}
.big{{font-family:'Newsreader',serif;font-size:clamp(2.2rem,5vw,3.2rem);font-weight:500;color:var(--navy)}}
img.chart{{width:100%;height:auto;border:1px solid var(--hairline);border-radius:12px;margin:10px 0}}
table{{width:100%;border-collapse:collapse;font-size:.9rem;margin:8px 0}}
th{{font-family:'IBM Plex Mono',monospace;font-size:.66rem;letter-spacing:.08em;color:var(--faint);text-align:left;padding:7px 8px;border-bottom:1px solid var(--hairline);text-transform:uppercase}}
td{{padding:7px 8px;border-bottom:1px solid var(--hairline2)}}
td.n{{text-align:right;font-variant-numeric:tabular-nums}}
.up{{color:var(--red)}}.down{{color:var(--green)}}
.bullets li{{margin:8px 0}}
.dl{{display:inline-block;border:1.5px solid var(--navy);border-radius:8px;padding:9px 16px;margin:4px 8px 4px 0;font-size:.9rem;text-decoration:none;font-weight:600}}
.note{{font-size:.85rem;color:var(--fainter);line-height:1.55}}
.cols{{display:grid;grid-template-columns:1fr 1fr;gap:26px}}
@media(max-width:700px){{.cols{{grid-template-columns:1fr}}}}
footer{{border-top:1px solid var(--hairline);margin-top:46px;padding-top:18px;font-size:.85rem;color:var(--fainter);line-height:1.6}}
.statecard{{border:1px solid var(--hairline);border-radius:10px;padding:12px 14px;font-size:.9rem}}
.stategrid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(250px,1fr));gap:10px}}
</style></head><body>
<nav>
  <a class="logo" href="/"><img src="/logo-mark.svg" alt="" width="30" height="30" style="display:block"><span class="logo-text"><span class="logo-word">Should I sell yet<span style="color:#b5591e">?</span></span><span class="logo-tag">LOCAL HOUSING MARKET SIGNALS</span></span></a>
  <a class="mono" style="font-size:11px;letter-spacing:.14em;color:var(--gold);text-decoration:none" href="/research/">RESEARCH</a>
</nav>
<div class="wrap">
{body}
<footer>
  <div><a href="/research/">ShouldISellYet Research</a> · <a href="/research/methodology.html">Methodology</a> · <a href="/">Home</a> · <a href="/press.html">Press</a></div>
  <div style="margin-top:8px">{CITE}</div>
  <div style="margin-top:8px">Free to use with citation: "Source: ShouldISellYet Research." Verdicts and the Warning-Sign Index are computed by ShouldISellYet from public market data and are general information, not financial or real-estate advice.</div>
</footer>
</div></body></html>"""


def arrow(delta):
    if delta is None:
        return ""
    cls = "up" if delta > 0 else ("down" if delta < 0 else "")
    sign = "+" if delta > 0 else ""
    return f'<span class="{cls}">{sign}{delta:.1f}</span>'


def headline_sentence(rec):
    wsi, delta = rec.get("wsi"), rec.get("delta")
    bits = [f"Warning signs are flashing in <b>{wsi:.1f}%</b> of scored U.S. ZIP markets"]
    if delta is not None:
        word = "up from" if delta > 0 else ("down from" if delta < 0 else "unchanged from")
        bits.append(f"{word} {rec['prev_wsi']:.1f}% last month" if delta != 0
                    else "unchanged from last month")
    # Superlatives never reach across the source seam: "record" claims are
    # bounded to the continuous series and say so out loud.
    basis = rec.get("basis_since")
    basis_txt = f" (continuous series since {pretty(basis)})" if basis else ""
    hs = rec.get("highest_since")
    if delta is not None and delta > 0:
        bits.append(f"the highest share in the index's continuous history{basis_txt}"
                    if hs == "record" else f"the highest share since {pretty(hs)}")
    elif delta is not None and delta < 0:
        ls = rec.get("lowest_since")
        bits.append(f"the lowest share in the index's continuous history{basis_txt}"
                    if ls == "record" else f"the lowest share since {pretty(ls)}")
    return " — ".join([bits[0], ", ".join(bits[1:])]) + "." if len(bits) > 1 else bits[0] + "."


def three_bullets(rep):
    out = []
    sm = rep["state_moves"]
    if sm:
        worst = max(sm, key=lambda r: r["delta"])
        best = min(sm, key=lambda r: r["delta"])
        if worst["delta"] > 0:
            out.append(f"<b>{STATE_NAMES.get(worst['key'], worst['key'])}</b> deteriorated most: "
                       f"{worst['share']:.1f}% of its scored ZIPs now show warning signs "
                       f"({arrow(worst['delta'])} pts this month).")
        if best["delta"] < 0:
            out.append(f"<b>{STATE_NAMES.get(best['key'], best['key'])}</b> improved most: "
                       f"warning share fell to {best['share']:.1f}% ({arrow(best['delta'])} pts).")
    ts = rep["top_streaks"]
    if ts:
        s = ts[0]
        place = f"{s['city']}, {s['state']}" if s["city"] else s["state"]
        out.append(f"Longest current warning streak: <b>{s['zip']}</b> ({esc(place)}) — "
                   f"{s['months']} consecutive months at WATCH or ACT.")
    n = len(rep["flips_to_warning"])
    if n:
        out.append(f"<b>{n:,} ZIP markets crossed into warning territory</b> this month "
                   f"(full list in the release CSVs).")
    return out[:3]


def state_paragraph(st, e, month):
    name = STATE_NAMES.get(st, st)
    c = e["counts"]
    parts = [f"In {name}: {e['share']:.1f}% of {e['scored']:,} scored ZIP markets "
             f"show warning signs as of {pretty(month)}"
             f" ({c['yellow']:,} WATCH, {c['red']:,} ACT)"]
    if e.get("delta") is not None:
        d = e["delta"]
        parts.append(f"{'up' if d > 0 else 'down' if d < 0 else 'flat'} "
                     f"{abs(d):.1f} points from last month" if d else "flat on last month")
    if e.get("flips_in"):
        parts.append(f"{e['flips_in']} ZIP{'s' if e['flips_in'] != 1 else ''} "
                     f"crossed the danger line this month")
    return ". ".join([parts[0]] + [p.capitalize() for p in parts[1:]]) + "."


# ————— CSVs —————

def write_csvs(rep, series, outdir):
    month = rep["month"]
    seam = rep.get("seam", "")

    with (outdir / "wsi-history.csv").open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        # The series column is not optional metadata: without it, anyone
        # charting this file draws the source seam as a market move — the
        # exact misread the chart's two strokes exist to prevent. The page
        # can explain; a CSV must carry its own caveats.
        w.writerow(["month", "wsi_pct", "series"])
        for m, v in series:
            w.writerow([m, f"{v:.2f}",
                        "continuous" if (seam and m >= seam) else "reconstruction"])

    with (outdir / f"state-aggregates-{month}.csv").open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["state", "scored_zips", "hold", "watch", "act", "strong",
                    "warning_share_pct", "delta_pts"])
        for st, e in sorted(rep["states"].items()):
            c = e["counts"]
            w.writerow([st, e["scored"], c["green"], c["yellow"], c["red"],
                        c["strong"], e["share"], e.get("delta", "")])

    with (outdir / f"metro-aggregates-{month}.csv").open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["cbsa", "metro", "scored_zips", "warning_share_pct", "delta_pts"])
        for r in sorted(rep["metros_deteriorating"] + rep["metros_improving"],
                        key=lambda r: -r["delta"]):
            w.writerow([r["key"], r["name"], r["scored"], r["share"], r["delta"]])

    with (outdir / f"zip-flips-{month}.csv").open("w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["zip", "city", "state", "from_verdict", "to_verdict"])
        for r in rep["flips_to_warning"]:
            w.writerow([r["zip"], r["city"], r["state"], r["from"], r["to"]])

    (outdir / "LICENSE.txt").write_text(
        f"""ShouldISellYet Research — {pretty(month)} release data
{SITE}/research/{month}/

Free to use, republish, and chart — including commercially — with citation:

    Source: ShouldISellYet Research

These files contain ShouldISellYet's own derived indicators (verdict counts,
the Warning-Sign Index, warning shares, verdict changes). They do not contain
and may not be represented as Redfin's or Realtor.com's underlying market
metrics; obtain those from the sources directly. Verdict methodology:
{SITE}/research/methodology.html
""")


# ————— pages —————

def word(level):
    return {"green": "HOLD", "yellow": "WATCH", "red": "ACT", "strong": "STRONG"}.get(level, level)


def release_page(rep, series, outdir, rel_url, gen_date=""):
    month = rep["month"]
    rec = rep["records"]
    bullets = "".join(f"<li>{b}</li>" for b in three_bullets(rep))

    # Quotable-stat rule: the WSI historical series was the one headline stat
    # with no HTML-text form — it lived only in the chart PNG and the CSV,
    # and an engine cannot cite a PNG. One dated sentence fixes that.
    year_ago_m = f"{int(month[:4]) - 1}-{month[5:7]}"
    year_ago = next((v for m0, v in series if m0 == year_ago_m), None)
    # prev_wsi is optional (absent on a single-month series — research.py only
    # emits it with >=2 months), so guard it like headline_sentence guards delta.
    series_text = (f"In text: the index stood at {rec['wsi']:.1f}% in {pretty(month)}"
                   + (f", versus {rec['prev_wsi']:.1f}% the month before" if rec.get("prev_wsi") is not None else "")
                   + (f" and {year_ago:.1f}% in {pretty(year_ago_m)}" if year_ago is not None else "")
                   + f". The full monthly series back to {series[0][0]} is in the CSV below.")

    def metro_rows(rows):
        return "".join(
            f'<tr><td>{esc(r["name"])}</td><td class="n">{r["scored"]}</td>'
            f'<td class="n">{r["share"]:.1f}%</td><td class="n">{arrow(r["delta"])}</td></tr>'
            for r in rows)

    flips = rep["flips_to_warning"]
    flip_rows = "".join(
        f'<tr><td class="mono"><a href="/zip/{r["zip"]}/">{r["zip"]}</a></td>'
        f'<td>{esc(r["city"])}, {r["state"]}</td><td>{word(r["from"])} → <b>{word(r["to"])}</b></td></tr>'
        for r in flips[:40])
    streak_rows = "".join(
        f'<tr><td class="mono"><a href="/zip/{r["zip"]}/">{r["zip"]}</a></td>'
        f'<td>{esc(r["city"])}, {r["state"]}</td><td class="n">{r["months"]}</td>'
        f'<td>{word(r["level"])}</td></tr>'
        for r in rep["top_streaks"][:15])

    state_cards = "".join(
        f'<div class="statecard"><b>{esc(STATE_NAMES.get(st, st))}</b><br>'
        f'{esc(state_paragraph(st, e, month))}</div>'
        for st, e in sorted(rep["states"].items()))

    csv_links = "".join(
        f'<a class="dl" href="{esc(n)}" download>{esc(t)}</a>' for n, t in [
            ("wsi-history.csv", "WSI history"),
            (f"state-aggregates-{month}.csv", "State aggregates"),
            (f"metro-aggregates-{month}.csv", "Metro movers"),
            (f"zip-flips-{month}.csv", "ZIP flip list"),
            ("LICENSE.txt", "License"),
        ])

    body = f"""
<div class="eyebrow">SHOULDISELLYET RESEARCH · {esc(pretty(month)).upper()} RELEASE · INDEX v{esc(rep['index_version'])}</div>
<h1>Warning-Sign Index: {rec['wsi']:.1f}%</h1>
<p class="lede">{headline_sentence(rec)}</p>
<ul class="bullets">{bullets}</ul>
<img class="chart" src="wsi-chart.png" alt="Warning-Sign Index time series through {esc(pretty(month))}" width="1200" height="675">
<p class="note">{esc(series_text)}</p>
<img class="chart" src="state-map.png" alt="Warning share by state, {esc(pretty(month))}" width="1200" height="675">

<div class="cols">
<div><h2>Metros deteriorating fastest</h2>
<table><thead><tr><th>Metro</th><th>ZIPs</th><th>Warning</th><th>Δ pts</th></tr></thead>
<tbody>{metro_rows(rep['metros_deteriorating'])}</tbody></table></div>
<div><h2>Metros improving fastest</h2>
<table><thead><tr><th>Metro</th><th>ZIPs</th><th>Warning</th><th>Δ pts</th></tr></thead>
<tbody>{metro_rows(rep['metros_improving'])}</tbody></table></div>
</div>
<p class="note">Metro league tables cover Metropolitan Statistical Areas with at least 15 scored ZIPs, so small-sample noise cannot top the table.</p>

<h2>Crossed the danger line this month</h2>
<p class="lede" style="font-size:1rem">{len(flips):,} ZIP markets moved from HOLD or STRONG into WATCH or ACT.{' Showing the first 40 — the CSV has all of them.' if len(flips) > 40 else ''}</p>
<table><thead><tr><th>ZIP</th><th>Place</th><th>Change</th></tr></thead><tbody>{flip_rows}</tbody></table>

<h2>Longest current warning streaks</h2>
<table><thead><tr><th>ZIP</th><th>Place</th><th>Months</th><th>Now</th></tr></thead><tbody>{streak_rows}</tbody></table>

<h2>Your state, in one paragraph</h2>
<p class="note">Written for reuse — every paragraph is quotable as-is with citation.</p>
<div class="stategrid">{state_cards}</div>

<h2>Download the data</h2>
<p>{csv_links}</p>
<p class="note">Free with citation ("Source: ShouldISellYet Research"). Files carry ShouldISellYet's derived indicators only — verdicts, shares, changes — never upstream raw metrics.</p>

<h2>Methodology, briefly</h2>
<p class="note">A ZIP is scored when at least two of its market signals are known; the Warning-Sign Index is the share of scored ZIPs whose verdict is WATCH or ACT. Verdicts come from fixed, published danger lines (months of supply&nbsp;&gt;4, prices falling&nbsp;&gt;2%&nbsp;y/y, time-to-sell up&nbsp;&gt;40%, inventory up&nbsp;&gt;50%, price cuts&nbsp;&gt;35%), backtested against FHFA outcomes. Pre-2026 history is restated from Redfin's archived tracker with identical thresholds. Full detail, definitions, and the versioned changelog: <a href="/research/methodology.html">methodology</a>.</p>
"""
    # Article + Dataset markup for answer engines. Dates follow the ZIP-page
    # precedent: the data build's generated stamp (meta.json), day-precision;
    # no truer per-release publish date exists in the research JSONs, which
    # carry month granularity only.
    canon = f"{SITE}{rel_url}"
    pub = gen_date or f"{month}-01"
    org = {"@type": "Organization", "@id": SITE + "/#org", "name": "ShouldISellYet",
           "url": SITE + "/", "legalName": "Yayday LLC",
           "logo": {"@type": "ImageObject", "url": SITE + "/apple-touch-icon.png"}}
    dataset = lambda name, desc_t, fname, cover: {
        "@type": "Dataset", "@id": canon + "#" + fname, "name": name,
        "description": desc_t, "license": canon + "LICENSE.txt",
        "isAccessibleForFree": True, "creator": {"@id": SITE + "/#org"},
        "temporalCoverage": cover,
        "distribution": [{"@type": "DataDownload", "encodingFormat": "text/csv",
                          "contentUrl": canon + fname}]}
    ld = json.dumps({"@context": "https://schema.org", "@graph": [
        org,
        {"@type": "Article", "@id": canon + "#article", "mainEntityOfPage": canon,
         "headline": f"Warning-Sign Index: {rec['wsi']:.1f}% — {pretty(month)}",
         "description": headline_sentence(rec),
         "datePublished": pub, "dateModified": pub,
         "author": {"@id": SITE + "/#org"}, "publisher": {"@id": SITE + "/#org"},
         "image": canon + "og.png"},
        dataset("ShouldISellYet Warning-Sign Index — monthly history",
                "Monthly share of scored U.S. ZIP markets whose verdict is WATCH or ACT, "
                "with a series column separating the continuous run from the reconstructed tail.",
                "wsi-history.csv", f"{series[0][0]}/{month}"),
        dataset(f"State warning-sign aggregates — {pretty(month)}",
                "Scored ZIPs, warning share, and month-over-month change per U.S. state.",
                f"state-aggregates-{month}.csv", month),
        dataset(f"Metro warning-sign movers — {pretty(month)}",
                "Metro areas (≥15 scored ZIPs) deteriorating and improving fastest.",
                f"metro-aggregates-{month}.csv", month),
        dataset(f"ZIP verdict flips — {pretty(month)}",
                "Every ZIP market that moved from HOLD or STRONG into WATCH or ACT this month.",
                f"zip-flips-{month}.csv", month),
    ]}, separators=(",", ":"))

    (outdir / "index.html").write_text(page(
        f"Warning-Sign Index {rec['wsi']:.1f}% — {pretty(month)} · ShouldISellYet Research",
        f"{rep['national']['scored']:,} U.S. ZIP markets scored in {pretty(month)}: "
        f"{rec['wsi']:.1f}% show warning signs. Monthly index, metro league tables, "
        "and downloadable data.",
        canon, body, og_image=f"{SITE}{rel_url}og.png", jsonld=ld))


def hub_page(h, series, releases, outdir):
    cur_m, cur_v = series[-1]
    rel_list = "".join(
        f'<tr><td><a href="/research/{m}/">{esc(pretty(m))}</a></td>'
        f'<td class="n">{v:.1f}%</td></tr>'
        for m, v in reversed([(m, dict(series)[m]) for m in releases if m in dict(series)]))
    body = f"""
<div class="eyebrow">SHOULDISELLYET RESEARCH</div>
<h1>The Warning-Sign Index</h1>
<p class="lede">One number for the temperature of the U.S. housing market:
the share of scored ZIP markets whose verdict is WATCH or ACT — computed
monthly for {len(series)} months and counting, from fixed, published danger
lines. Free to cite; the data is downloadable in every release.</p>
<p><span class="big">{cur_v:.1f}%</span><br>
<span class="note">of scored U.S. ZIP markets show warning signs · data through {esc(pretty(cur_m))}</span></p>
<img class="chart" src="wsi-chart.png" alt="Warning-Sign Index, full history" width="1200" height="675">
<h2>Monthly releases</h2>
<table><thead><tr><th>Release</th><th>WSI</th></tr></thead><tbody>{rel_list}</tbody></table>
<h2>How it works</h2>
<p class="note">Definitions, danger lines, the FHFA backtest, restatement
rules, and the versioned changelog live on the
<a href="/research/methodology.html">methodology page</a>. Media and data
questions: <a href="mailto:press@shouldisellyet.com">press@shouldisellyet.com</a>.</p>
"""
    (outdir / "index.html").write_text(page(
        f"Warning-Sign Index: {cur_v:.1f}% of U.S. ZIP markets show warning signs",
        "A monthly index of U.S. housing-market health at ZIP level, from "
        "ShouldISellYet Research. League tables, local data, free downloads.",
        f"{SITE}/research/", body, og_image=f"{SITE}/research/wsi-chart.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default=str(ROOT / "web"))
    args = ap.parse_args()

    h = load_history()
    if not h["months"]:
        print("no research history — skipping research build")
        return
    series = national_series(h)
    changelog_p = RESEARCH_DIR / "changelog.json"
    changelog = json.loads(changelog_p.read_text()) if changelog_p.exists() else []

    reports = sorted(RESEARCH_DIR.glob("research-*.json"))
    releases = [p.stem.replace("research-", "") for p in reports]

    stage = Path(args.web) / ".research-build"
    final = Path(args.web) / "research"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    # Day-precision date for Article markup — the data build's generated
    # stamp, same source the ZIP pages already use for datePublished.
    meta_p = Path(args.web) / "data" / "meta.json"
    gen_date = (json.loads(meta_p.read_text()).get("generated", "")
                if meta_p.exists() else "")

    seam = h.get("seam")
    wsi_chart(series, {"delta": None}, changelog, stage / "wsi-chart.png", seam=seam)
    for p in reports:
        rep = json.loads(p.read_text())
        month = rep["month"]
        outdir = stage / month
        outdir.mkdir()
        upto = [(m, v) for m, v in series if m <= month]
        wsi_chart(upto, rep["records"], changelog, outdir / "wsi-chart.png", seam=seam)
        state_map({st: e for st, e in rep["states"].items()}, month,
                  outdir / "state-map.png")
        write_csvs(rep, upto, outdir)
        og_card(rep, outdir / "og.png")
        social_set(rep, upto, outdir)
        release_page(rep, upto, outdir, f"/research/{month}/", gen_date=gen_date)

    hub_page(h, series, releases, stage)
    methodology_page(h, changelog, stage)

    # Machine-readable current WSI at a STABLE url (/research/wsi.json) so the
    # homepage's "Your market vs. the nation" row can carry the live number
    # without hardcoding it or knowing the release month. Contents are the
    # latest release's records verbatim (wsi, delta, prev_wsi, month, streaks)
    # plus the release path for the "full monthly research" link. The homepage
    # FEATURE-DETECTS this file — absent or stale, the row degrades to the
    # verdict mix + percentile and no research link, never an error.
    latest = json.loads(reports[-1].read_text())
    (stage / "wsi.json").write_text(json.dumps(
        dict(latest["records"], release=f"/research/{latest['month']}/"),
        separators=(",", ":")))

    if final.exists():
        shutil.rmtree(final)
    stage.rename(final)
    print(f"research: hub + {len(releases)} release(s) → {final} "
          f"(WSI {series[-1][1]:.1f}% through {series[-1][0]})")


if __name__ == "__main__":
    main()
