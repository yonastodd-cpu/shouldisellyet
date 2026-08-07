"""
ShouldISellYet — static per-ZIP page generator.

Renders one indexable page per ZIP with sufficient data, plus per-state hubs,
a chunked sitemap index, and robots.txt.

  python pipeline/build_pages.py [--web web] [--limit N] [--only 20874,20906]

Reads ONLY committed derived data (web/data/**) and the bundled place file
(pipeline/data/zip_places.csv) — no network, no raw-source download. That is
deliberate: the GitHub Pages deploy uploads web/ wholesale, and push-triggered
runs skip the refresh pipeline. If these pages were built only during a data
refresh, a site-only edit would deploy a web/ with no zip/ directory and
silently delete every ZIP URL. Building on every deploy keeps the artifact
complete and the swap atomic.

"Sufficient data" = months of supply, price trend, and days-on-market (with its
year-ago comparison) all present, a verdict that isn't insufficient_data, and a
known city name. ZIPs failing any of those get no page at all — never an empty
shell, which would be a thin-content liability.
"""

import argparse
import csv
import html
import json
import os
import shutil
import sys
from collections import defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
PLACES = Path(__file__).parent / "data" / "zip_places.csv"
SITE = "https://shouldisellyet.com"
UTM = "utm_source=zippage&utm_medium=organic&utm_campaign=zip_seo"

MONTHS = ["January", "February", "March", "April", "May", "June",
          "July", "August", "September", "October", "November", "December"]
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

KINDS = {
    "green":  {"tag":"HOLD",  "hex":"#2e9e5b","soft":"#e9f4ee","line":"#bcdcc9",
               "head":"No warning signs in {zip}",
               "sub":"Nothing in the current data says this market is turning. If you sell now, it should be about your life — not the market."},
    "yellow": {"tag":"WATCH", "hex":"#c8891f","soft":"#faf1dd","line":"#e8d5a8",
               "head":"Early signals moving in {zip}",
               "sub":"A warning signal has tripped. Not a crisis — but this is exactly how turns start, months before prices move."},
    "red":    {"tag":"ACT",   "hex":"#d64545","soft":"#fbe9e9","line":"#ecc3c3",
               "head":"Danger lines crossed in {zip}",
               "sub":"Multiple signals are past the thresholds that preceded past downturns. Sellers here are losing pricing power."},
    "strong": {"tag":"ACT",   "hex":"#1f3a5f","soft":"#e8eef7","line":"#c3d2e8",
               "head":"Strong seller's market in {zip}",
               "sub":"Buyers are competing for homes here. If selling was already on your mind, conditions favor you right now."},
}

from verdict_copy import COPY as VCOPY, get as vcopy, as_js as vcopy_js

esc = lambda s: html.escape(str(s), quote=True)
clamp = lambda x: max(3, min(97, x))
tcol = lambda t: "#d64545" if t == "r" else "#c8891f" if t == "a" else "#1f3a5f" if t == "s" else "#2e9e5b"
pct = lambda x: ("+" if x >= 0 else "−") + f"{abs(x*100):.1f}%"


def load_places():
    out = {}
    if not PLACES.exists():
        print(f"WARNING: {PLACES} missing — no pages can be generated", file=sys.stderr)
        return out
    for r in csv.DictReader(open(PLACES, encoding="utf-8")):
        out[r["zip"]] = (r["city"], r["state"], r.get("county", ""))
    return out


def metric_rows(m, strong):
    """Mirrors buildMetricRows() in web/index.html — same thresholds, same colours."""
    rows = []
    if m.get("mos") is not None:
        v = m["mos"]; t = ("s" if v < 2.5 else "g") if strong else ("r" if v > 6 else "a" if v > 4 else "g")
        rows.append(("MONTHS OF SUPPLY", f"{v:.1f} mo", t, clamp(v/8*100), 31.3 if strong else 50,
                     "strong line: 2.5 mo" if strong else ("line: 4.0 mo" if t == "g" else "past the line")))
    if m.get("spy") is not None:
        v = m["spy"]; t = ("s" if v >= .05 else "g") if strong else ("r" if v < -.05 else "a" if v < -.02 else "g")
        rows.append(("PRICES VS. LAST YR", pct(v), t, clamp((0.12-v)/0.24*100), 29.2 if strong else 58.3,
                     "strong line: +5% y/y" if strong else ("holding or rising" if t == "g" else "line: −2% y/y")))
    if m.get("dom") is not None and m.get("domy") is not None:
        d, dy = m["dom"], m["domy"]; prior = d - dy; p = dy/prior if prior > 0 else 0
        t = ("s" if p <= -.15 else "g") if strong else ("a" if p > .4 else "g")
        rows.append(("TIME TO SELL", f"{round(d)} days", t, clamp((p*100+50)/150*100), 23.3 if strong else 60,
                     (f"+{round(dy)} days y/y" if dy > 0 else "as fast as last yr")))
    if m.get("pd") is not None:
        v = m["pd"]; t = ("s" if v < .20 else "g") if strong else ("a" if v > .35 else "g")
        rows.append(("LISTINGS W/ PRICE CUTS", f"{round(v*100)}%", t, clamp(v/0.7*100), 28.6 if strong else 50,
                     "strong line: 20%" if strong else ("line: 35%" if t == "g" else "past the line")))
    if m.get("invy") is not None:
        v = m["invy"]; t = "a" if v > .5 else "g"
        rows.append(("NEW SUPPLY VS. LAST YR", pct(v).replace(".0", ""), t, clamp((v*100+20)/120*100), 58.3,
                     "line: +50% y/y" if t == "g" else "surging"))
    return rows[:4]


def fastest_month(h):
    """Calendar month with the lowest average days-on-market, from history."""
    if not h or not h.get("d"):
        return None
    start_m = int(h["s"][5:7])
    by = defaultdict(list)
    for i, v in enumerate(h["d"]):
        if v is not None:
            by[(start_m - 1 + i) % 12].append(v)
    cand = [(mo, sum(a)/len(a)) for mo, a in by.items() if len(a) >= 2]
    return MONTHS[min(cand, key=lambda t: t[1])[0]] if cand else None


def pretty_month(period):
    return f"{MONTHS[int(period[5:7])-1]} {period[:4]}" if len(period) == 7 else period


def card_stat(m):
    """ONE public market stat for the share card. Public feed values only —
    never a personal input (see og_card.py's privacy note)."""
    spy, dom = m.get("spy"), m.get("dom")
    if spy is not None and spy <= -0.02:
        return f"Prices are down {abs(spy)*100:.1f}% from a year ago"
    if spy is not None and spy >= 0.05:
        return f"Prices are up {spy*100:.1f}% from a year ago"
    if dom is not None:
        return f"Homes here sell in {round(dom)} days"
    if spy is not None:
        return f"Prices are {'up' if spy >= 0 else 'down'} {abs(spy)*100:.1f}% from a year ago"
    return "See the four signals for this ZIP"


def percentile(spy, deciles):
    if not deciles or len(deciles) != 11 or spy is None:
        return None
    k = 0
    while k < 10 and spy > deciles[k+1]:
        k += 1
    frac = k*10 + ((spy - deciles[k])/(deciles[k+1] - deciles[k])*10 if deciles[k+1] > deciles[k] else 5)
    return max(1, min(99, round(frac)))


# ————— shared stylesheet (one file for every generated page) —————

CSS = """*{box-sizing:border-box}
:root{--bg:#faf8f4;--ink:#1c2430;--muted:#5c6673;--faint:#8a8578;--fainter:#a49d8d;
--hairline:#e7e2d8;--hairline2:#f0ebe0;--navy:#1f3a5f;--navy-dark:#172d4b;--gold:#8a7a55;--track:#efe9dc;
--green:#2e9e5b;--amber:#c8891f;--red:#d64545;--faint-ink:#6b6558}
body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,sans-serif;font-size:1.0625rem;line-height:1.6}
a{color:var(--navy)}.mono{font-family:'IBM Plex Mono',ui-monospace,monospace}
.wrap{max-width:820px;margin:0 auto;padding:0 20px 56px}
nav.top{display:flex;align-items:center;justify-content:space-between;max-width:820px;margin:0 auto;padding:16px 20px;border-bottom:1px solid var(--hairline);flex-wrap:wrap;gap:10px}
.logo{display:flex;align-items:center;gap:9px;text-decoration:none;color:var(--ink)}
.lights{display:flex;gap:3px}.lights span{width:8px;height:8px;border-radius:50%}
.brand{font-family:Georgia,'Newsreader',serif;font-style:italic;font-weight:600;font-size:17px}
.crumb{font-size:.8125rem;color:var(--muted);padding:14px 0 0}
/* Arrival banner for shared links — slim, dismissible, no modal, no gate. */
#share-banner{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin:14px 0 0;
  padding:11px 14px;background:#f4f6fa;border:1px solid #c3d2e8;border-radius:9px;font-size:.9375rem}
#share-banner[hidden]{display:none}
#share-banner a{font-weight:600}
#share-banner button{margin-left:auto;background:none;border:none;font-size:20px;line-height:1;
  color:var(--muted);cursor:pointer;padding:0 4px}
.crumb a{color:var(--muted)}
h1{font-family:Georgia,'Newsreader',serif;font-weight:500;font-size:clamp(1.6rem,3.6vw,2.3rem);line-height:1.18;margin:14px 0 6px;letter-spacing:-.01em}
.vcard{border:1px solid var(--hairline);border-radius:12px;overflow:hidden;margin:18px 0 22px;background:#fff}
.vhead{display:flex;align-items:center;gap:12px;padding:16px 20px;flex-wrap:wrap}
.vdot{width:13px;height:13px;border-radius:50%;flex:none}
.vtag{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:1.5rem;font-weight:700;letter-spacing:.1em;line-height:1}
.vtitle{font-family:Georgia,'Newsreader',serif;font-size:1.15rem;font-weight:600}
.vbody{padding:16px 20px 20px}
.vbody p{margin:0 0 14px;color:var(--muted)}
.metric{display:grid;grid-template-columns:190px 84px 1fr 132px;gap:12px;align-items:center;margin-bottom:11px}
.metric .name{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:.8125rem;color:var(--muted)}
.metric .val{font-weight:650}
.metric .track{height:7px;border-radius:4px;background:var(--track);position:relative}
.metric .fill{position:absolute;inset:0 auto 0 0;border-radius:4px}
.metric .th{position:absolute;top:-3px;bottom:-3px;width:2px;background:#9a9384;border-radius:1px}
.metric .note{font-size:.8125rem;color:var(--faint-ink)}
.facts{margin:0 0 4px;padding-left:20px}
.facts li{margin-bottom:8px}
.stamp{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:.75rem;color:var(--faint-ink);letter-spacing:.04em;padding:14px 20px;border-top:1px solid var(--hairline2);line-height:1.55}
.ctas{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 6px}
.btn{display:inline-flex;align-items:center;justify-content:center;min-height:48px;padding:12px 18px;border-radius:8px;font-weight:600;font-size:1rem;text-decoration:none;border:1.5px solid var(--navy)}
.btn-primary{background:var(--navy);color:#faf8f4;}
.btn-outline{background:#fff;color:var(--navy)}
.btn-ghost{background:none;border-color:var(--faint);color:var(--muted)}
h2{font-family:Georgia,'Newsreader',serif;font-weight:500;font-size:1.3rem;margin:30px 0 8px}
.method{font-size:.9375rem;color:var(--muted)}
.nearby{display:flex;flex-wrap:wrap;gap:8px;margin:10px 0 0;padding:0;list-style:none}
.nearby a{display:inline-block;border:1px solid var(--hairline);border-radius:7px;padding:7px 11px;font-size:.9375rem;text-decoration:none;background:#fff}
.hubgrid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:8px 18px;padding:0;list-style:none;margin:10px 0 0}
.hubgrid a{text-decoration:none}
.hubgrid .z{font-family:'IBM Plex Mono',ui-monospace,monospace;font-size:.8125rem;color:var(--muted)}
.statecols{columns:200px 4;list-style:none;padding:0;margin:12px 0 0}
.statecols li{margin-bottom:6px;break-inside:avoid}
footer{border-top:1px solid var(--hairline);margin-top:34px;padding-top:16px;font-size:.875rem;color:var(--faint-ink)}
footer a{color:var(--faint-ink)}
.disc{font-size:.8125rem;line-height:1.55;color:var(--faint-ink);margin-top:10px}
@media(max-width:640px){.metric{grid-template-columns:1fr 84px;grid-template-areas:"name val" "track track"}
.metric .name{grid-area:name}.metric .val{grid-area:val;text-align:right}.metric .track{grid-area:track}
.metric .note{display:none}.ctas .btn{width:100%}}
"""

NAVBAR = """<nav class="top">
  <a class="logo" href="/"><span class="lights"><span style="background:var(--green)"></span><span style="background:var(--amber)"></span><span style="background:var(--red)"></span></span><span class="brand">Should I sell yet?</span></a>
  <a href="/#check" style="font-size:.875rem">Check any ZIP free →</a>
</nav>"""

# The one linked citation. Each generated page carries it EXACTLY ONCE:
# a ZIP page in its stamp (beside the data it credits, so its footer passes
# cite=""), a state hub or the markets index in its footer, since neither has
# a stamp. See docs/ATTRIBUTION.md.
CITE = ('Data provided by <a href="https://www.redfin.com" target="_blank" rel="noopener">Redfin</a>, '
        'a national real estate brokerage')

# City names come from the GeoNames US postal export (CC BY 4.0), which asks
# for credit and accepts a link to www.geonames.org. Any one city name is a
# bare fact, but across ~18.6k ZIP pages and 51 state hubs we reproduce a
# substantial part of the compilation — which is the thing the licence covers.
# So it is credited on the pages that actually print a city name, and NOT on
# the markets index, which lists states only. See docs/ATTRIBUTION.md.
PLACES_CITE = ('Place names from <a href="https://www.geonames.org" target="_blank" '
               'rel="noopener">GeoNames</a> (CC BY 4.0)')

FOOTER = """<footer>
  <a href="/">Home</a> · <a href="/zip/">Browse markets by state</a> · <a href="/press.html">Press</a> ·
  <a href="/terms.html">Terms</a> · <a href="/privacy.html">Privacy</a>
  <div class="disc">{cite}Verdicts are computed from public housing-market data and are general information only — not financial, legal, tax, or real-estate advice. Every home is different; consult a licensed professional before making decisions. © 2026 ShouldISellYet.com · operated by Yayday LLC.</div>
</footer>"""


def zip_page(z, e, place, meta, neighbours, has_card=False):
    city, st, _ = place
    k = KINDS[e["l"]]; m = e.get("m", {}); strong = e["l"] == "strong"
    period = meta.get("period", "")
    pretty_period = f"{MONTHS[int(period[5:7])-1]} {period[:4]}" if len(period) == 7 else period
    updated = meta.get("generated", date.today().isoformat())
    state_name = STATE_NAMES.get(st, st)
    stat = card_stat(m)
    vc = vcopy(e["l"])          # shared verdict copy: word, translation, emoji
    # T3: share text introduces the site before the card even loads. Built
    # from the same map, so the translation can never drift from the card.
    share_text = (f"{vc['emoji']} Just ran a free checkup on my ZIP's housing market — "
                  f"{city} ({z}) says {vc['word']}: {vc['translation'].split(' — ')[0].lower()}. "
                  f"Check yours:")

    rows = "".join(
        f'<div class="metric"><span class="name">{esc(n)}</span>'
        f'<span class="val" style="color:{tcol(t)}">{esc(v)}</span>'
        f'<span class="track"><span class="fill" style="width:{f:.1f}%;background:{tcol(t)}"></span>'
        f'<span class="th" style="left:{th}%"></span></span>'
        f'<span class="note">{esc(note)}</span></div>'
        for n, v, t, f, th, note in metric_rows(m, strong))

    # Two-to-four sentences that exist only for this ZIP.
    facts = []
    if m.get("spy") is not None:
        d = m["spy"]
        facts.append(f"The typical home here sold for <b>{pct(d)}</b> compared with a year ago." if d < 0 or d > 0
                     else "The typical sale price here is flat against a year ago.")
    if m.get("dom") is not None and m.get("domy") is not None:
        dy = round(m["domy"])
        unit = "day" if abs(dy) == 1 else "days"
        tail = (f"{abs(dy)} {unit} {'slower' if dy > 0 else 'faster'} than a year ago" if dy else "the same pace as a year ago")
        facts.append(f"Homes are taking about <b>{round(m['dom'])} days</b> to sell — {tail}.")
    fm = fastest_month(e.get("h"))
    if fm:
        facts.append(f"Over the last three years, homes in {esc(city)} have sold fastest in <b>{fm}</b> — worth knowing when you plan a listing.")
    p = percentile(m.get("spy"), (meta.get("national") or {}).get("spy_deciles"))
    if p:
        pack = ("near the top of the pack" if p >= 85 else "ahead of most markets" if p >= 60
                else "squarely mid-pack" if p > 40 else "behind most markets" if p > 15 else "near the bottom of the pack")
        facts.append(f"Prices here are rising faster than about <b>{p}%</b> of U.S. ZIP codes — {pack}.")
    facts_html = "".join(f"<li>{s}</li>" for s in facts)

    # Share card: per-ZIP where we render one, generic brand card otherwise.
    # The data month is in the path so a new month is a NEW url — that is the
    # cache-busting strategy: scrapers key on the image url, so cards refresh
    # exactly when the data does and never go stale behind a CDN.
    og_img = (f"{SITE}/og/{period}/{z}.png" if has_card else f"{SITE}/og/default.png")
    # T2: the CARD asks the question, so the TITLE states the finding —
    # together they read as Q then A in the preview stack. Drop the state
    # before the city if the 70-char budget is tight.
    # ≤70 chars so nothing truncates in a preview. Degrade in order: drop the
    # state, then shorten the label, then drop the trailing ZIP (it is already
    # on the card and in the URL).
    def _title(place, label="housing market check", show_zip=True):
        tail = f" ({z})" if show_zip else ""
        return f"{place} {label}: {vc['word']} — {vc['short']}{tail}"
    for cand in (_title(f"{city}, {st}"), _title(city), _title(city, "market check"),
                 _title(city, "market check", False)):
        og_title = cand
        if len(cand) <= 70:
            break
    og_desc = f"{stat}. Free monthly verdict for any U.S. ZIP."
    og_alt = f"{city}, {st} {z}: {vc['word']} — {vc['translation']}. {stat}"
    title = f"Should I Sell My House in {city}, {st}? — {z} Verdict ({pretty_period})"
    desc = (f"{k['tag']} — {city}, {st} ({z}). "
            + (f"Prices {pct(m['spy'])} vs. a year ago; " if m.get("spy") is not None else "")
            + f"homes selling in {round(m['dom'])} days. Free verdict from public market data, updated {updated}."
            if m.get("dom") is not None else
            f"{k['tag']} — {city}, {st} ({z}). Free verdict from public market data, updated {updated}.")
    url = f"{SITE}/zip/{z}/"

    nb = "".join(f'<li><a href="/zip/{n}/">{esc(nc)} · {n}</a></li>' for n, nc in neighbours)
    ld = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebPage", "@id": url, "url": url, "name": title, "description": desc,
             "inLanguage": "en-US", "datePublished": updated, "dateModified": updated,
             "isPartOf": {"@type": "WebSite", "name": "ShouldISellYet", "url": SITE + "/"},
             "about": {"@type": "Place", "name": f"{city}, {st} {z}",
                       "address": {"@type": "PostalAddress", "postalCode": z,
                                   "addressLocality": city, "addressRegion": st, "addressCountry": "US"}}},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
                {"@type": "ListItem", "position": 2, "name": "Markets by state", "item": f"{SITE}/zip/"},
                {"@type": "ListItem", "position": 3, "name": state_name, "item": f"{SITE}/zip/{st}/"},
                {"@type": "ListItem", "position": 4, "name": f"{city}, {st} {z}", "item": url}]},
        ]}, separators=(",", ":"))

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta property="og:type" content="article"><meta property="og:title" content="{esc(og_title)}">
<meta property="og:description" content="{esc(og_desc)}"><meta property="og:url" content="{url}">
<meta property="og:site_name" content="ShouldISellYet"><meta property="og:image" content="{og_img}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{esc(og_alt)}">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{esc(og_title)}">
<meta name="twitter:description" content="{esc(og_desc)}"><meta name="twitter:image" content="{og_img}">
<link rel="stylesheet" href="/zip/zip.css">
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><rect x='30' y='6' width='40' height='88' rx='12' fill='%231c2430'/><circle cx='50' cy='26' r='11' fill='%23d64545'/><circle cx='50' cy='50' r='11' fill='%23c8891f'/><circle cx='50' cy='74' r='11' fill='%232e9e5b'/></svg>">
<script type="application/ld+json">{ld}</script>
</head><body>
{NAVBAR}
<div class="wrap">
<div id="share-banner" hidden>Someone shared this ZIP's market checkup with you.
  <a href="/?{UTM}#check">Check your own ZIP free</a> — takes 5 seconds.
  <button type="button" id="share-banner-x" aria-label="Dismiss">&times;</button></div>
<div class="crumb"><a href="/">Home</a> › <a href="/zip/">Markets</a> › <a href="/zip/{st}/">{esc(state_name)}</a> › {z}</div>
<h1>Should I sell my house in {esc(city)}, {esc(st)}? ({z})</h1>
<div class="vcard" style="border-color:{k['line']}">
  <div class="vhead" style="background:{k['soft']}">
    <span class="vdot" style="background:{k['hex']};box-shadow:0 0 0 4px {k['soft']},0 0 0 5px {k['hex']}"></span>
    <span class="vtag" style="color:{k['hex']}">{k['tag']}</span>
    <span class="vtitle">{esc(k['head'].format(zip=z))}</span>
  </div>
  <div class="vbody">
    <p>{esc(k['sub'])}</p>
    {rows}
    <ul class="facts">{facts_html}</ul>
  </div>
  <div class="stamp">Data through {esc(pretty_period)} · updated {esc(updated)} · {CITE} · {PLACES_CITE}</div>
</div>
<div class="ctas">
  <button class="btn btn-outline" id="share-btn" type="button" data-zip="{z}" data-text="{esc(share_text)}">Share this checkup</button>
  <a class="btn btn-primary" href="/?zip={z}&amp;{UTM}">Check this ZIP live</a>
  <a class="btn btn-outline" href="/subscribe.html?plan=monitor&amp;zip={z}&amp;{UTM}">Set up notifications</a>
  <a class="btn btn-ghost" href="/subscribe.html?plan=report&amp;zip={z}&amp;{UTM}">Get the full report</a>
</div>
<h2>How this verdict is computed</h2>
<p class="method">Four public signals, each with a danger line drawn from past national downturns: months of supply (4.0), the year-over-year price trend (−2%), how long homes take to sell (+40% year over year), and the share of listings cutting price (35%). A ZIP crossing enough of them reads WATCH or ACT; a clean ZIP reads HOLD. <a href="/#signals">See the full explanation of each dial</a>, including the exact math and what goes into it.</p>
<h2>Nearby markets</h2>
<ul class="nearby">{nb}</ul>
<p style="margin-top:16px"><a href="/zip/{st}/">All {esc(state_name)} markets →</a></p>
{FOOTER.format(cite="")}
</div>
<script>
// Share this ZIP's verdict. PUBLIC DATA ONLY — the button carries the ZIP,
// the verdict word and the place name, all of which are already on the page.
// No personal input exists on this page and none may be introduced here.
// T4: close the loop for a shared arrival. Banner only — no modal, no email
// gate; the page below already explains itself. Dismissal sticks per session.
(function(){{
  try {{
    var shared = new URLSearchParams(location.search).get("utm_source") === "share";
    var el = document.getElementById("share-banner");
    if (shared && el && !sessionStorage.getItem("sisy_share_banner_x")) {{
      el.hidden = false;
      document.getElementById("share-banner-x").addEventListener("click", function(){{
        el.hidden = true;
        try {{ sessionStorage.setItem("sisy_share_banner_x", "1"); }} catch (e) {{}}
      }});
    }}
  }} catch (e) {{}}
}})();
(function(){{
  var b = document.getElementById("share-btn"), t;
  if (!b) return;
  var url = "https://shouldisellyet.com/s/" + b.dataset.zip;
  var text = b.dataset.text;
  b.addEventListener("click", function(){{
    if (navigator.share) {{ navigator.share({{ text: text, url: url }}).catch(function(){{}}); return; }}
    var payload = text + " " + url, done = function(ok){{
      clearTimeout(t); b.textContent = ok ? "Copied ✓" : "Couldn't copy";
      t = setTimeout(function(){{ b.textContent = "Share this checkup"; }}, 2400);
    }};
    if (navigator.clipboard && navigator.clipboard.writeText) {{
      navigator.clipboard.writeText(payload).then(function(){{ done(true); }}).catch(function(){{ done(false); }});
    }} else {{
      var ta = document.createElement("textarea");
      ta.value = payload; ta.setAttribute("readonly", "");
      ta.style.cssText = "position:fixed;top:-1000px;opacity:0";
      document.body.appendChild(ta); ta.select();
      var ok = false; try {{ ok = document.execCommand("copy"); }} catch (e) {{}}
      document.body.removeChild(ta); done(ok);
    }}
  }});
}})();
</script>
</body></html>"""


def share_stub(z, e, place, meta, has_card):
    """/s/{zip} — the share destination.

    Carries the full per-ZIP OG card so the preview still shows the SENDER's
    verdict (that's the hook), then bounces the human to the homepage.

    The redirect deliberately does NOT carry the ZIP as `zip=`: that param
    prefills and auto-runs the checker, which would satisfy the recipient's
    curiosity with someone else's result. `from=` is context only. The whole
    point of the share is to get the recipient to type their OWN ZIP.

    Scrapers read meta and never execute JS or follow the refresh, so they get
    the card; humans get the redirect. noindex + absent from the sitemap so
    these never compete with the real /zip/ pages in search.
    """
    city, st, _ = place
    vc = vcopy(e["l"])
    stat = card_stat(e.get("m", {}))
    period = meta.get("period", "")
    og_img = f"{SITE}/og/{period}/{z}.png" if has_card else f"{SITE}/og/default.png"

    def _title(p_, label="housing market check", show_zip=True):
        return f"{p_} {label}: {vc['word']} — {vc['short']}" + (f" ({z})" if show_zip else "")
    for cand in (_title(f"{city}, {st}"), _title(city), _title(city, "market check"),
                 _title(city, "market check", False)):
        og_title = cand
        if len(cand) <= 70:
            break
    og_desc = f"{stat}. Free monthly verdict for any U.S. ZIP."
    dest = f"/?from={z}&amp;utm_source=share"
    dest_js = f"/?from={z}&utm_source=share"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>{esc(og_title)}</title>
<meta name="description" content="{esc(og_desc)}">
<link rel="canonical" href="{SITE}/">
<meta property="og:type" content="website"><meta property="og:title" content="{esc(og_title)}">
<meta property="og:description" content="{esc(og_desc)}"><meta property="og:url" content="{SITE}/s/{z}">
<meta property="og:site_name" content="ShouldISellYet">
<meta property="og:image" content="{og_img}">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta property="og:image:alt" content="{esc(city)}, {esc(st)} {z}: {vc['word']} — {esc(vc['translation'])}. {esc(stat)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(og_title)}">
<meta name="twitter:description" content="{esc(og_desc)}">
<meta name="twitter:image" content="{og_img}">
<script>location.replace({dest_js!r});</script>
<meta http-equiv="refresh" content="0;url={dest}">
<style>body{{font-family:system-ui,-apple-system,sans-serif;background:#faf8f4;color:#5c6673;
padding:40px 20px;text-align:center;font-size:16px}}a{{color:#1f3a5f}}</style>
</head><body>
<p>Taking you to the free ZIP checker… <a href="{dest}">continue</a></p>
</body></html>"""


def state_hub(st, entries, meta):
    """entries: sorted [(zip, city, county, tag, hex)]"""
    name = STATE_NAMES.get(st, st)
    updated = meta.get("generated", date.today().isoformat())
    groups = defaultdict(list)
    for z, city, county, tag, hexc in entries:
        groups[county or (z[:3] + "xx")].append((z, city, tag, hexc))
    body = []
    for g in sorted(groups):
        label = f"{g} County" if not g.endswith("xx") else f"ZIPs starting {g[:3]}"
        items = "".join(
            f'<li><a href="/zip/{z}/">{esc(city)}</a> <span class="z">{z} · '
            f'<span style="color:{hexc}">{tag}</span></span></li>'
            for z, city, tag, hexc in sorted(groups[g], key=lambda t: (t[1], t[0])))
        body.append(f'<h2>{esc(label)}</h2><ul class="hubgrid">{items}</ul>')
    title = f"Housing market verdicts for every {name} ZIP code — ShouldISellYet"
    desc = f"Free HOLD / WATCH / ACT verdicts for {len(entries)} {name} ZIP codes, computed from public market data and updated {updated}."
    url = f"{SITE}/zip/{st}/"
    ld = json.dumps({"@context":"https://schema.org","@graph":[
        {"@type":"WebPage","@id":url,"url":url,"name":title,"description":desc,
         "inLanguage":"en-US","dateModified":updated,
         "isPartOf":{"@type":"WebSite","name":"ShouldISellYet","url":SITE+"/"}},
        {"@type":"BreadcrumbList","itemListElement":[
            {"@type":"ListItem","position":1,"name":"Home","item":SITE+"/"},
            {"@type":"ListItem","position":2,"name":"Markets by state","item":f"{SITE}/zip/"},
            {"@type":"ListItem","position":3,"name":name,"item":url}]}]}, separators=(",",":"))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}"><link rel="stylesheet" href="/zip/zip.css">
<meta property="og:type" content="website"><meta property="og:url" content="{url}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="{SITE}/og/default.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{SITE}/og/default.png">
<script type="application/ld+json">{ld}</script></head><body>
{NAVBAR}
<div class="wrap">
<div class="crumb"><a href="/">Home</a> › <a href="/zip/">Markets</a> › {esc(name)}</div>
<h1>{esc(name)} housing markets</h1>
<p class="method">A free HOLD / WATCH / ACT verdict for each of the {len(entries)} {esc(name)} ZIP codes with enough reported sales to score. Data through {esc(meta.get('period',''))} · updated {esc(updated)}.</p>
{''.join(body)}
{FOOTER.format(cite=CITE + ". " + PLACES_CITE + ". ")}
</div></body></html>"""


def markets_index(states, meta):
    updated = meta.get("generated", date.today().isoformat())
    total = sum(n for _, n in states)
    items = "".join(f'<li><a href="/zip/{st}/">{esc(STATE_NAMES.get(st, st))}</a> <span class="z">{n}</span></li>'
                    for st, n in sorted(states, key=lambda t: STATE_NAMES.get(t[0], t[0])))
    title = "Browse housing market verdicts by state — ShouldISellYet"
    desc = f"HOLD / WATCH / ACT verdicts for {total:,} U.S. ZIP codes, computed from public market data and updated {updated}."
    url = f"{SITE}/zip/"
    ld = json.dumps({"@context":"https://schema.org","@graph":[
        {"@type":"WebPage","@id":url,"url":url,"name":title,"description":desc,"inLanguage":"en-US","dateModified":updated,
         "isPartOf":{"@type":"WebSite","name":"ShouldISellYet","url":SITE+"/"}},
        {"@type":"BreadcrumbList","itemListElement":[
            {"@type":"ListItem","position":1,"name":"Home","item":SITE+"/"},
            {"@type":"ListItem","position":2,"name":"Markets by state","item":url}]}]}, separators=(",",":"))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title><meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}"><link rel="stylesheet" href="/zip/zip.css">
<meta property="og:type" content="website"><meta property="og:url" content="{url}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<meta property="og:image" content="{SITE}/og/default.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{SITE}/og/default.png">
<script type="application/ld+json">{ld}</script></head><body>
{NAVBAR}
<div class="wrap">
<div class="crumb"><a href="/">Home</a> › Markets</div>
<h1>Browse markets by state</h1>
<p class="method">{total:,} U.S. ZIP codes with enough reported sales to score, each with a free verdict from public market data. Data through {esc(meta.get('period',''))} · updated {esc(updated)}.</p>
<ul class="statecols">{items}</ul>
{FOOTER.format(cite=CITE + ". ")}
</div></body></html>"""


def write_sitemaps(web, urls, lastmod, chunk=10000):
    """Sitemap index + ≤10k-URL chunks. Returns the number of chunks."""
    sm = web / "sitemaps"
    sm.mkdir(parents=True, exist_ok=True)
    for old in sm.glob("*.xml"):
        old.unlink()
    n = 0
    for i in range(0, len(urls), chunk):
        n += 1
        body = "".join(f"<url><loc>{u}</loc><lastmod>{lastmod}</lastmod></url>" for u in urls[i:i+chunk])
        (sm / f"pages-{n}.xml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + body + "</urlset>\n",
            encoding="utf-8")
    idx = "".join(f"<sitemap><loc>{SITE}/sitemaps/pages-{i}.xml</loc><lastmod>{lastmod}</lastmod></sitemap>"
                  for i in range(1, n + 1))
    (web / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + idx + "</sitemapindex>\n",
        encoding="utf-8")
    (web / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n"
        "# The paid report is per-customer and gated; no value in crawling it.\n"
        "Disallow: /my-report.html\n\n"
        f"Sitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--web", default=str(ROOT / "web"))
    ap.add_argument("--limit", type=int, default=0, help="cap pages (smoke tests)")
    ap.add_argument("--only", default="", help="comma-separated ZIPs (smoke tests)")
    ap.add_argument("--top-cards", type=int, default=2500,
                    help="share cards for the top N ZIPs by homes sold, plus all DMV")
    ap.add_argument("--no-cards", action="store_true", help="skip card rendering")
    args = ap.parse_args()
    web = Path(args.web)
    data = web / "data"
    meta = json.loads((data / "meta.json").read_text())
    places = load_places()
    only = {z.strip() for z in args.only.split(",") if z.strip()}

    eligible, skipped = [], defaultdict(int)
    for f in sorted((data / "zips").glob("*.json")):
        for z, e in json.loads(f.read_text()).items():
            if only and z not in only:
                continue
            m = e.get("m", {})
            if any(r[0] == "insufficient_data" for r in e.get("r", [])):
                skipped["insufficient_verdict"] += 1; continue
            if any(m.get(k) is None for k in ("mos", "spy", "dom", "domy")):
                skipped["incomplete_dials"] += 1; continue
            if z not in places:
                skipped["no_city_name"] += 1; continue
            eligible.append((z, e))
    eligible.sort()
    if args.limit:
        eligible = eligible[:args.limit]

    # Build into a staging dir, then swap — a half-written tree is never
    # what gets uploaded, even if this process dies mid-run.
    final = web / "zip"
    stage = web / ".zip-build"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    (stage / "zip.css").write_text(CSS, encoding="utf-8")
    # Same canonical map the cards and titles use, for hand-written pages.
    (Path(web) / "verdict-copy.js").write_text(vcopy_js(), encoding="utf-8")

    by_prefix = defaultdict(list)
    for z, e in eligible:
        by_prefix[z[:3]].append(z)
    lookup = dict(eligible)

    # ——— share cards ———
    # Rendering all 18.5k costs ~6.5 min and 238MB on EVERY deploy (measured),
    # which is untenable for a step that also runs on a one-line copy fix. So a
    # bounded set gets a real card and everyone else gets the brand card — the
    # brief's fallback, chosen because this host has no serverless runtime for
    # a dynamic /api/og endpoint (GitHub Pages, static only).
    # The set: every DMV ZIP (our home market) + the top N by homes sold, which
    # concentrates cards where real selling activity — and so real sharing — is.
    dmv = {z for z, e in eligible if places[z][1] in ("DC", "MD", "VA")}
    top = {z for z, _ in sorted(eligible, key=lambda t: -(t[1].get("m", {}).get("sold") or 0))[:args.top_cards]}
    card_set = dmv | top
    period = meta.get("period", "")
    og_dir = web / "og"
    cards_made = 0
    if not args.no_cards:
        try:
            from og_card import render_card
        except ImportError as exc:
            print(f"WARNING: Pillow missing ({exc}) — skipping cards, pages fall back to the brand card")
            card_set = set()
        else:
            if og_dir.exists():
                shutil.rmtree(og_dir)      # drop stale data-month dirs
            (og_dir / period).mkdir(parents=True, exist_ok=True)
            render_card("", "", "", "green", "Is your ZIP's market turning?", " ",
                        og_dir / "default.png")     # generic brand card
            for z, e in eligible:
                if z not in card_set:
                    continue
                city, st, _ = places[z]
                render_card(z, city, st, e["l"], card_stat(e.get("m", {})),
                            pretty_month(period), og_dir / period / f"{z}.png")
                cards_made += 1
    else:
        card_set = set()

    by_state, total_bytes, biggest = defaultdict(list), 0, 0
    for z, e in eligible:
        city, st, county = places[z]
        sibs = [s for s in by_prefix[z[:3]] if s != z][:6]
        nb = [(s, places[s][0]) for s in sibs]
        page = zip_page(z, e, places[z], meta, nb, has_card=(z in card_set))
        d = stage / z
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(page, encoding="utf-8")
        b = len(page.encode()); total_bytes += b; biggest = max(biggest, b)
        k = KINDS[e["l"]]
        by_state[st].append((z, city, county, k["tag"], k["hex"]))

    # Share stubs live outside the staged /zip tree, at /s/{zip}.
    s_stage = web / ".s-build"
    if s_stage.exists():
        shutil.rmtree(s_stage)
    s_stage.mkdir(parents=True)
    for z, e in eligible:
        (s_stage / z).mkdir(parents=True, exist_ok=True)
        (s_stage / z / "index.html").write_text(
            share_stub(z, e, places[z], meta, z in card_set), encoding="utf-8")
    s_final = web / "s"
    if s_final.exists():
        shutil.rmtree(s_final)
    s_stage.rename(s_final)

    for st, entries in by_state.items():
        d = stage / st
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(state_hub(st, sorted(entries), meta), encoding="utf-8")
    (stage / "index.html").write_text(
        markets_index([(st, len(v)) for st, v in by_state.items()], meta), encoding="utf-8")

    if final.exists():
        shutil.rmtree(final)
    stage.rename(final)

    lastmod = meta.get("generated", date.today().isoformat())
    urls = [f"{SITE}/", f"{SITE}/report.html", f"{SITE}/press.html", f"{SITE}/zip/"]
    urls += [f"{SITE}/zip/{st}/" for st in sorted(by_state)]
    urls += [f"{SITE}/zip/{z}/" for z, _ in eligible]
    chunks = write_sitemaps(web, urls, lastmod)

    print(f"pages: {len(eligible):,} ZIP + {len(by_state)} state hubs + 1 index")
    print(f"skipped: {dict(skipped)}")
    print(f"html: {total_bytes/1e6:.1f} MB total · avg {total_bytes/max(1,len(eligible))/1024:.1f} KB · largest {biggest/1024:.1f} KB")
    print(f"sitemap: index + {chunks} chunk(s), {len(urls):,} URLs, lastmod {lastmod}")
    print(f"share stubs: {len(eligible):,} at /s/{{zip}} · noindex, not in sitemap")
    if cards_made:
        cb = sum(f.stat().st_size for f in og_dir.rglob("*.png"))
        print(f"og cards: {cards_made:,} rendered ({len(dmv):,} DMV + top {args.top_cards:,}) "
              f"· {cb/1e6:.0f} MB · /og/{period}/ · {len(eligible)-cards_made:,} ZIPs use the brand card")


if __name__ == "__main__":
    main()
