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
import textwrap
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

# THE BADGE WORD IS NOT TYPED HERE. It used to be, and "strong" was given the
# tag "ACT" — so a page whose own answer sentence read "the reading is STRONG"
# displayed an ACT badge directly beneath it, and its meta description (the
# search snippet, for 1,360 ZIPs) read "ACT — Anchorage, AK" exactly like a
# danger verdict. The colour differed; the word did not, which is all a screen
# reader, a search result or a shared link ever gets.
#
# verdict_copy.json is the canonical copy map — the same file the prose, the OG
# card and the browser all read. The tag is now taken from it, so a fifth place
# to change the word no longer exists.
KINDS = {
    "green":  {"tag":"HOLD",  "hex":"#2e9e5b","soft":"#e9f4ee","line":"#bcdcc9",
               "head":"No warning signs in {zip}",
               "sub":"Nothing in the current data says this market is turning. If you sell now, it should be about your life — not the market."},
    "yellow": {"tag":"WATCH", "hex":"#c8891f","soft":"#faf1dd","line":"#e8d5a8",
               "head":"Early signals moving in {zip}",
               "sub":"A warning signal has tripped. Not a crisis — but this is exactly how turns start, months before prices move."},
    "red":    {"tag":"ACT",   "hex":"#d64545","soft":"#fbe9e9","line":"#ecc3c3",
               "head":"Danger lines crossed in {zip}",
               # NOT "multiple". Under v1 red needed 4 points and no single
               # check could reach it. Under v2 price_falling_fast alone
               # scores 3 = ACT, so an ACT page can have exactly one line
               # crossed and this sentence would be false on it.
               "sub":"At least one signal is past the thresholds that preceded past downturns. Sellers here are losing pricing power."},
    "strong": {"tag":"ACT",   "hex":"#1f3a5f","soft":"#e8eef7","line":"#c3d2e8",
               "head":"Strong seller's market in {zip}",
               "sub":"Buyers are competing for homes here. If selling was already on your mind, conditions favor you right now."},
}

from verdict_copy import COPY as VCOPY, get as vcopy, as_js as vcopy_js
import data_pause as PAUSE
import figures_switch as FIG
import realtor_crosscheck as RDC
from build_manifest import read_manifest
from verdict_v2 import SPEC as V2, disclosure
from verdict_copy import methodology_sentence

# Every number this file states to a reader comes from the engine's own spec.
# The copy and the thresholds drifted once already — the Tier B refit moved two
# lines and the pages went on quoting the old ones.
DISCLOSED = disclosure()
METHOD_SENTENCE = methodology_sentence()

# Derived, never typed: whatever verdict_copy.json says is the word. Placed
# here rather than beside KINDS because the copy map is imported below it.
for _lvl, _k in KINDS.items():
    _k["tag"] = VCOPY[_lvl]["word"]

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
    # v1-ONLY DIALS. Months of supply and price-cut share need a closed-sale
    # count that active-listing statistics cannot produce, so a v2 reading
    # carries neither and these two branches never fire for one. They are kept
    # rather than deleted so a legacy record still renders correctly if one is
    # ever inspected, and their lines are the v1 lines because that is what a
    # v1 record was scored against.
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
        # The calibrated active-listing lines, not the ported sale-basis ones.
        t = ("s" if p <= V2["dom_shrink"] else "g") if strong else ("a" if p > V2["dom_stretch"] else "g")
        # "TIME TO SELL" overstated what the number is. On the active-listing
        # basis this is days a STANDING listing has been on the market, which
        # methodology section 2 says is not time-to-contract and runs longer.
        rows.append(("TIME ON MARKET", f"{round(d)} days", t, clamp((p*100+50)/150*100), 23.3 if strong else 60,
                     (f"+{round(dy)} days y/y" if dy > 0 else
                      f"−{abs(round(dy))} days y/y" if dy < 0 else "same as last yr")))
    if m.get("pd") is not None:
        v = m["pd"]; t = ("s" if v < .20 else "g") if strong else ("a" if v > .35 else "g")
        rows.append(("LISTINGS W/ PRICE CUTS", f"{round(v*100)}%", t, clamp(v/0.7*100), 28.6 if strong else 50,
                     "strong line: 20%" if strong else ("line: 35%" if t == "g" else "past the line")))
    if m.get("invy") is not None:
        # +30% is the calibrated active-listing line (TIER-B-GATE.md). Only
        # v2 entries are ever displayed — every legacy entry is paused — so
        # the dial and the engine agree on everything a reader can see.
        v = m["invy"]; t = "a" if v > V2["inventory_surge"] else "g"
        rows.append(("NEW SUPPLY VS. LAST YR", pct(v).replace(".0", ""), t, clamp((v*100+20)/120*100), 41.7,
                     f"line: {DISCLOSED['inventory_surge']} y/y" if t == "g" else "surging"))
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
    """ONE market stat for the share card. Values already shown on the page —
    never a personal input (see og_card.py's privacy note). The feed itself is
    licensed, not public; only these derived figures are published."""
    spy, dom = m.get("spy"), m.get("dom")
    if spy is not None and spy <= -0.02:
        return f"Prices are down {abs(spy)*100:.1f}% from a year ago"
    if spy is not None and spy >= 0.05:
        return f"Prices are up {spy*100:.1f}% from a year ago"
    if dom is not None:
        return f"Listed homes here average {round(dom)} days on the market"
    if spy is not None:
        return f"Prices are {'up' if spy >= 0 else 'down'} {abs(spy)*100:.1f}% from a year ago"
    return "See the signals for this ZIP"


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
.logo{display:flex;align-items:center;gap:10px;text-decoration:none;color:var(--ink)}
/* Brand lockup — the delivered artboard's ratios (see web/index.html), but
   deliberately WITHOUT the Source Serif 4 the rest of the site now loads.
   These 22.9k pages ship zero webfonts on purpose: they are the SEO surface,
   and a font request in the head is paid on every one of them for a one-line
   wordmark. Georgia stands in, exactly as the h1 rule below already does, so
   the page falls back consistently instead of this one line reaching for a
   face nothing else here loads — and Georgia is the delivered file's own
   first fallback, so this matches what that file renders on its own. Sizing,
   tracking and ink are the artboard's regardless, so only the face differs.
   If brand exactness beats the request, add the font to the head here and
   drop the fallback. */
.logo{--lockup:40px;gap:calc(var(--lockup)*.2333)}
.logo img{width:var(--lockup);height:var(--lockup)}
.logo-text{display:flex;flex-direction:column;justify-content:center;gap:2px}
.logo-word{font-family:Georgia,'Source Serif 4',serif;font-weight:600;
           font-size:calc(var(--lockup)*.5333);letter-spacing:-.0094em;line-height:1}
.logo-tag{font-family:'IBM Plex Mono',ui-monospace,monospace;font-weight:500;
          font-size:calc(var(--lockup)*.1583);letter-spacing:.28em;
          line-height:1;color:#7E7A70;white-space:nowrap}
@media (max-width:400px){ .logo-tag{display:none} }
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
/* The extractable answer sentence under the H1 — body ink, not muted: it is
   the page's one-line summary for humans AND the sentence engines lift. */
.answer{font-size:1.0625rem;line-height:1.6;color:var(--ink);margin:2px 0 18px;max-width:72ch}
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
  <a class="logo" href="/"><img src="/logo-mark.svg" alt="" width="40" height="40" style="display:block"><span class="logo-text"><span class="logo-word">Should I sell yet?</span><span class="logo-tag">LOCAL HOUSING MARKET SIGNALS</span></span></a>
  <a href="/#check" style="font-size:.875rem">Check any ZIP free →</a>
</nav>"""

# The one linked citation. Each generated page carries it EXACTLY ONCE:
# a ZIP page in its stamp (beside the data it credits, so its footer passes
# cite=""), a state hub or the markets index in its footer, since neither has
# a stamp. See docs/ATTRIBUTION.md.
# The credit has to name the source the reading actually came from. Tranche 1
# published RentCast-derived readings under "Data provided by Redfin", two
# weeks after Redfin ingestion stopped — a false attribution to a vendor whose
# data the site had just withdrawn, on the one line a reader would check.
CITE_V1 = ''   # withdrawn 2026-08-25: no prior-vendor value is published, so the citation has nothing to attach to
# THE VENDOR IS NOT NAMED HERE. The licence bars use of the mark "in
# advertising, publicity or any other commercial manner" without written
# consent, and asks for no attribution in return — so naming it on 22,874 ZIP
# pages, 51 hubs and the markets index is a trademark exposure that buys
# nothing. The provenance a reader needs is that the figures are licensed
# rather than public, and that is what this says. The name survives in exactly
# one place, web/methodology.html, as a plain nominative statement of source.
# Pending counsel; a precaution, not a settled conclusion.
CITE_V2 = "Market statistics from a licensed data provider"


def cite_for(basis):
    """Attribution for a reading on this basis."""
    return CITE_V2 if basis == PAUSE.RELEASED_BASIS else CITE_V1


CITE = CITE_V1


def hub_cite():
    """Attribution for a page that lists many ZIPs rather than showing one.

    The 51 state hubs and the markets index carried "Data provided by Redfin,
    a national real estate brokerage" in their footers — present tense, on
    pages listing readings computed from RentCast, eleven days after Redfin
    ingestion stopped. Found by the crawl gate on its first production run,
    after three earlier rounds of checking had gone past them: a hub is
    generated, so it has a template, but nothing in the matrix asked what its
    FOOTER said.

    A hub does not display any one ZIP's figures, so it credits the source of
    the readings it lists rather than a per-record basis.
    """
    return CITE_V2 if PAUSE.RELEASED_BASIS else CITE_V1

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
  <div class="disc">{cite}Readings are computed from licensed market statistics and are general information only — not financial, legal, tax, or real-estate advice. Every home is different; consult a licensed professional before making decisions. © 2026 ShouldISellYet.com · operated by Yayday LLC.</div>
</footer>"""


def zip_page(z, e, place, meta, neighbours, has_card=False):
    city, st, _ = place
    # A provisioned record for an unreleased ZIP is just {"st": ST} — no
    # level, no metrics. That is the ordinary case now, not an error: the
    # pause branch below replaces every one of these values anyway.
    level = e.get("l") or "green"
    # FIGURES_KILL_SWITCH. Every figure on this page reaches it through these
    # two lines, and when the switch is on they hand back an empty metric
    # block and no history. That is deliberately the SAME shape as a record
    # that never had figures — which is the ordinary state of ~17,874 ZIPs, so
    # the withheld path is the path this build already walks tens of thousands
    # of times a run, not a branch that first executes the day somebody flips
    # a flag. Everything downstream (the dials, the prose facts, the answer
    # sentence, the meta description, the OG stat, the national percentile)
    # falls silent on its own. Exactly two things needed saying explicitly and
    # are marked FIGURES_KILL_SWITCH below: the answer sentence, which would
    # otherwise borrow the pause copy and tell a reader the reading is gone
    # when it is not, and the OG image, which has its stat painted into the
    # pixels where no later branch can reach it.
    m = FIG.metrics(e.get("m", {}))
    hist = FIG.history(e.get("h"))
    k = KINDS[level]; strong = level == "strong"
    # meta.json is frozen at the last Redfin run (2026-06) because fetch_data
    # has not run since ingestion stopped. A v2 reading is as-of its own month,
    # and tranche 1 published August readings under "Data through June 2026" —
    # two months stale, and pointing at a window inside the withdrawn data.
    #
    # THE meta.json FALLBACK IS GONE. It was the last route by which a frozen
    # global date reached a page: a ZIP with no reading of its own inherited
    # June 2026 and stated it as the vintage of a reading it was not showing.
    # A page with no reading now carries NO date anywhere — head, body, stamp
    # or JSON-LD — which is the only honest thing an undated page can do.
    period = e.get("p") or ""
    pretty_period = pretty_month(period)
    state_name = STATE_NAMES.get(st, st)
    stat = card_stat(m)
    vc = vcopy(level)           # shared verdict copy: word, translation, emoji
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
        # v2 reads ACTIVE LISTINGS: this is the asking price, not the sale
        # price. Calling it "sold for" is the exact confusion the methodology
        # page was rewritten to prevent — asking prices run higher than sale
        # prices — and it shipped over v2 data on the first release.
        if e.get("b") == PAUSE.RELEASED_BASIS:
            facts.append(f"The typical home here is <b>asking</b> {pct(d)} compared with a year ago."
                         if d < 0 or d > 0
                         else "The typical asking price here is flat against a year ago.")
        else:
            facts.append(f"The typical home here sold for <b>{pct(d)}</b> compared with a year ago." if d < 0 or d > 0
                         else "The typical sale price here is flat against a year ago.")
    if m.get("dom") is not None and m.get("domy") is not None:
        dy = round(m["domy"])
        unit = "day" if abs(dy) == 1 else "days"
        # NOT "taking N days to sell". This counts days a listing that is still
        # for sale has been on the market — methodology section 2: it is not
        # time-to-contract, and across unsold listings it runs longer than one.
        tail = (f"{abs(dy)} {unit} {'longer' if dy > 0 else 'shorter'} than a year ago" if dy else "the same as a year ago")
        facts.append(f"Listed homes here have been on the market about <b>{round(m['dom'])} days</b> — {tail}.")
    fm = fastest_month(hist)
    if fm:
        facts.append(f"Over the last three years, listings in {esc(city)} have spent the fewest days on the market in <b>{fm}</b> — worth knowing when you plan a listing.")
    # spy_deciles is a table of Redfin SOLD-price year-over-year changes. A v2
    # spy is an ASKING-price change. Ranking one against the other compares two
    # different measurements and reports the answer as a national percentile —
    # published on every released page in tranche 1. Withheld until the deciles
    # are rebuilt on the active-listing basis.
    p = (None if e.get("b") == PAUSE.RELEASED_BASIS
         else percentile(m.get("spy"), (meta.get("national") or {}).get("spy_deciles")))
    if p:
        pack = ("near the top of the pack" if p >= 85 else "ahead of most markets" if p >= 60
                else "squarely mid-pack" if p > 40 else "behind most markets" if p > 15 else "near the bottom of the pack")
        facts.append(f"Prices here are rising faster than about <b>{p}%</b> of U.S. ZIP codes — {pack}.")
    facts_html = "".join(f"<li>{s}</li>" for s in facts)

    # Share card: per-ZIP where we render one, generic brand card otherwise.
    # The data month is in the path so a new month is a NEW url — that is the
    # cache-busting strategy: scrapers key on the image url, so cards refresh
    # exactly when the data does and never go stale behind a CDN.
    # FIGURES_KILL_SWITCH. A card is a PICTURE of the reading and its evidence
    # line, flattened to pixels — nothing downstream can blank a figure that is
    # already painted. The card loop in main() re-renders these from the same
    # withheld metrics, so a card built under the switch carries the reading
    # word and no evidence line; a card built BEFORE it does not, and stays on
    # disk under its month's path. Pointing at the brand card is the only
    # answer that holds for both.
    og_img = (f"{SITE}/og/{period}/{z}.png"
              if has_card and period and FIG.shows_figures()
              else f"{SITE}/og/default.png")
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
    og_desc = f"{stat}. Free monthly reading for any U.S. ZIP."
    og_alt = f"{city}, {st} {z}: {vc['word']} — {vc['translation']}. {stat}"
    # "Verdict" is gone from everything a visitor reads: it promised a ruling
    # this site does not issue. The internal level names, JSON keys and
    # function names keep it — renaming those would be a data migration
    # wearing a copy change's clothes.
    title = (f"Should I Sell My House in {city}, {st}? — {z} Reading ({pretty_period})"
             if pretty_period else
             f"Should I Sell My House in {city}, {st}? — {z} Reading")
    # No "updated {date}" any more. It rendered meta.json's frozen build stamp
    # — 2026-08-10 on every one of 22,874 descriptions — beside figures that
    # were as-of a different month entirely. The only date this page can stand
    # behind is its reading's own as-of month, and that is in the title and the
    # stamp already.
    # A BARE WORD IS THE WHOLE PROBLEM WITH THE FOURTH STATE. The engine has
    # four levels and three reader-facing words (verdict_v2.LEVELS: strong ->
    # ACT), so whatever word the copy map holds, "strong" and "red" can arrive
    # at a reader looking identical — a search snippet reading "ACT —
    # Anchorage, AK" is the danger reading and the seller's market spelled the
    # same way. The colour is not in a snippet, a screen reader or a shared
    # link. The qualifier is, so it goes wherever the word appears without the
    # headline beside it to explain it.
    qual = " (seller's market)" if strong and k["tag"] == KINDS["red"]["tag"] else ""
    desc = (f"{k['tag']}{qual} — {city}, {st} ({z}). "
            + (f"Prices {pct(m['spy'])} vs. a year ago; " if m.get("spy") is not None else "")
            + f"homes on the market ~{round(m['dom'])} days. Free reading from licensed market statistics."
            if m.get("dom") is not None else
            f"{k['tag']}{qual} — {city}, {st} ({z}). Free reading from licensed market statistics.")
    url = f"{SITE}/zip/{z}/"

    nb = "".join(f'<li><a href="/zip/{n}/">{esc(nc)} · {n}</a></li>' for n, nc in neighbours)

    # The extractable answer: one self-contained sentence an answer engine can
    # lift whole — entity, date, verdict, and the two stats every standing
    # page is guaranteed to have (eligibility requires mos+dom non-null).
    # Every number in it is the page's own live data; nothing is hardcoded.
    # The second stat differs by basis: months of supply needs a closed-sale
    # count no active-listing feed has, so a v2 page states its listing count
    # instead. Guarded rather than assumed — an unguarded m['mos'] here would
    # KeyError on every re-scored ZIP.
    # A record with no reading has none of these. Build the sentence only when
    # there is something to say; the pause branch below replaces it wholesale
    # anyway, and reaching into m for a page that has no metrics is how a
    # reading-less record used to crash the build one KeyError at a time.
    if m.get("dom") is not None:
        second = (f"{m['mos']:.1f} months of supply" if m.get("mos") is not None
                  else f"{int(m['inv']):,} homes on the market" if m.get("inv") is not None
                  else "its current listing activity")
        answer = (f"As of {pretty_period}, the housing market in {city}, {st} ({z}) shows "
                  f"{vc['short']} — the reading is {vc['word']}, with listed homes on the "
                  f"market about {round(m['dom'])} days and {second}.")
    elif e.get("l") and not FIG.shows_figures():
        # FIGURES_KILL_SWITCH. This page HAS a reading; only the figures behind
        # it are withheld. Falling through to the pause sentence below would
        # tell a reader — and an answer engine, which lifts this line whole —
        # that the reading is being rebuilt, which is false and is the exact
        # kind of half-true the pause work kept having to undo. So the reading
        # is stated, and the absence of figures is stated as a choice.
        answer = ((f"As of {pretty_period}, the housing market in " if pretty_period
                   else "The housing market in ")
                  + f"{city}, {st} ({z}) shows {vc['short']} — the reading is "
                  + f"{vc['word']}. {FIG.WITHHELD_LINE}")
    else:
        answer = f"{PAUSE.NOTICE_TITLE} for {city}, {st} ({z}). {PAUSE.NOTICE_BODY}"
    # The Q&A pair: question a person actually asks, two-sentence answer from
    # the canonical copy map (verdict_copy.json qa — never hand-written here,
    # so the FAQ can't drift from the card and the share text).
    faq_q = f"Is it a good time to sell a home in {city}?"
    faq_a = vc["qa"].format(city=city)
    # Credit rides with the data: shown when a reading is, blanked when it is
    # not. Overwritten by the pause branch below.
    basis = e.get("b", PAUSE.LEGACY_BASIS)
    # "updated {meta.generated}" is gone with the rest of the frozen stamp: it
    # was a build date presented next to a data vintage, which reads as
    # freshness and was not. A retrieved_at exists in market_stats but is not
    # selected by readings_for_scoring(), so it reaches no record and no
    # template; until it does, the as-of month is the only date we have.
    stamp_html = " · ".join(x for x in (
        f"Data through {esc(pretty_period)}" if pretty_period else "",
        cite_for(basis), PLACES_CITE) if x)

    # ————— REDFIN SUNSET, PHASE 0 —————
    # The body banner is the least of it: the verdict word and the metric
    # values are also in the title, the description, both social-card blocks,
    # the OG image itself and the JSON-LD. A crawler, a social unfurl and a
    # shared link read those, not the banner. So they are ALL neutralised here,
    # in one block, and the per-ZIP OG card falls back to the brand image.
    # A RELEASED ZIP WHOSE READING SAYS IT HAS NO READING. verdict_v2 returns
    # level "green" with an insufficient_data reason when fewer than two
    # signals are known — HOLD there is a safe default, not a finding. Rendered
    # without this branch it becomes a confident "No warning signs right now"
    # on a market we cannot actually read, while the homepage tells the truth
    # about the same ZIP (index.html branches on the same reason). It stays
    # noindexed: a page that says it has nothing to say should not compete in
    # search for a rating it does not have.
    thin = any(r and r[0] == "insufficient_data" for r in e.get("r") or [])
    if thin and PAUSE.shows_data(z, e.get("b", PAUSE.LEGACY_BASIS)):
        where = f"{city}, {st} ({z})"
        title = og_title = f"{where} housing market — not enough recent data"
        desc = og_desc = ("Too few recent listings in this ZIP to read the "
                          "market reliably. We hold the reading until the "
                          "signals are dependable.")
        og_alt = "Not enough recent data for a reading"
        og_img = f"{SITE}/og/default.png"
        answer = (f"As of {pretty_period}, there are too few recent listings in "
                  f"{where} to produce a dependable reading.")
        stat = ""
        rows = ""
        facts_html = ""
        faq_q = f"Why is there no reading for {z}?"
        faq_a = ("Smaller markets report too few listings for the signals to be "
                 "reliable. Rather than publish a rating we cannot stand "
                 "behind, we hold it until there is enough data.")
        share_text = f"Not enough recent market data to read {where} yet."
        k = dict(k, tag="", hex="#6b6861", soft="#f3f1ea", line="#e7e4dd",
                 head="Not enough recent data",
                 sub="Too few recent listings here to read the market reliably.")

    if not PAUSE.shows_data(z, e.get("b", PAUSE.LEGACY_BASIS)):
        where = f"{city}, {st} ({z})"
        title = og_title = PAUSE.title_for(where)
        desc = og_desc = PAUSE.NOTICE_DESC
        og_alt = PAUSE.NOTICE_TITLE
        og_img = f"{SITE}/og/default.png"
        answer = f"{PAUSE.NOTICE_TITLE} for {where}. {PAUSE.NOTICE_BODY}"
        stat = ""
        rows = ""
        faq_q = f"Why is the reading for {z} unavailable?"
        faq_a = PAUSE.NOTICE_BODY
        share_text = f"{PAUSE.NOTICE_TITLE} for {where} on ShouldISellYet."
        # The prose facts list. It is built from the same withdrawn metrics as
        # the dials and it renders in the page BODY, so leaving it out of this
        # block published sentences like "the typical home here sold for +0.2%
        # compared with a year ago" underneath a header saying the reading was
        # being refreshed. Verified live on /zip/20601/ before this line
        # existed. A blanking that covers the metadata and forgets the prose is
        # not a blanking.
        facts_html = ""
        # THE STAMP. It credited the withdrawn vendor by name and asserted a
        # data vintage — "Data through June 2026 · Data provided by Redfin, a
        # national real estate brokerage" — directly beneath a banner saying
        # the reading was being rebuilt. On all 22,874 pages, for the whole
        # withdrawal.
        #
        # Attribution is required on a page that DISPLAYS a vendor's data
        # (docs/ATTRIBUTION.md). A paused page displays none, so the credit is
        # not merely unnecessary: it tells a reader and a crawler the page is
        # built on data it is not showing, and it names the one vendor
        # data_pause's own copy rule says the notice must never name.
        stamp_html = ""
        k = dict(k, tag="", hex="#6b6861", soft="#f3f1ea", line="#e7e4dd",
                 head=PAUSE.NOTICE_TITLE, sub=PAUSE.NOTICE_BODY)

    ld = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "Organization", "@id": SITE + "/#org", "name": "ShouldISellYet",
             "url": SITE + "/", "legalName": "Yayday LLC",
             "logo": {"@type": "ImageObject", "url": SITE + "/apple-touch-icon.png"}},
            # datePublished/dateModified used to be meta.json's "generated"
            # stamp — one frozen build date asserted on 22,874 pages as when
            # each was last changed. They now carry the reading's own as-of
            # month (a bare YYYY-MM is a valid ISO 8601 date) and are OMITTED
            # entirely on a page with no reading, because a page that has no
            # date should not state one to a crawler either.
            {"@type": "WebPage", "@id": url, "url": url, "name": title, "description": desc,
             "inLanguage": "en-US",
             **({"datePublished": period, "dateModified": period} if period else {}),
             "publisher": {"@id": SITE + "/#org"},
             "isPartOf": {"@type": "WebSite", "name": "ShouldISellYet", "url": SITE + "/"},
             "about": {"@type": "Place", "name": f"{city}, {st} {z}",
                       "address": {"@type": "PostalAddress", "postalCode": z,
                                   "addressLocality": city, "addressRegion": st, "addressCountry": "US"}}},
            {"@type": "FAQPage", "@id": url + "#faq", "mainEntity": [
                {"@type": "Question", "name": faq_q,
                 "acceptedAnswer": {"@type": "Answer", "text": faq_a}}]},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": SITE + "/"},
                {"@type": "ListItem", "position": 2, "name": "Markets by state", "item": f"{SITE}/zip/"},
                {"@type": "ListItem", "position": 3, "name": state_name, "item": f"{SITE}/zip/{st}/"},
                {"@type": "ListItem", "position": 4, "name": f"{city}, {st} {z}", "item": url}]},
        ]}, separators=(",", ":"))

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
{PAUSE.robots_meta(z, thin, e.get("b", PAUSE.LEGACY_BASIS))}
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self' https://kfbjooteazwvdsonthba.supabase.co; img-src 'self' data:; object-src 'none'; base-uri 'self'">
<meta name="referrer" content="strict-origin-when-cross-origin">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)}</title>
<script src="/track.js" defer></script>
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
<link rel="icon" href="/favicon.svg">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<link rel="manifest" href="/site.webmanifest">
<meta name="theme-color" content="#faf8f4">
<script type="application/ld+json">{ld}</script>
</head><body>
{NAVBAR}
<div class="wrap">
<div id="share-banner" hidden>Someone shared this ZIP's market checkup with you.
  <a href="/?{UTM}#check">Check your own ZIP free</a> — takes 5 seconds.
  <button type="button" id="share-banner-x" aria-label="Dismiss">&times;</button></div>
<div class="crumb"><a href="/">Home</a> › <a href="/zip/">Markets</a> › <a href="/zip/{st}/">{esc(state_name)}</a> › {z}</div>
<h1>Should I sell my house in {esc(city)}, {esc(st)}? ({z})</h1>
<p class="answer">{esc(answer)}</p>
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
  <div class="stamp">{stamp_html}</div>
</div>
<div class="ctas">
  <button class="btn btn-outline" id="share-btn" type="button" data-zip="{z}" data-track="share_click" data-track-zip="{z}" data-text="{esc(share_text)}">Share this checkup</button>
  <a class="btn btn-primary" href="/?zip={z}&amp;{UTM}">Check this ZIP live</a>
  <a class="btn btn-outline" data-track="purchase_click_monitor" data-track-zip="{z}" href="/subscribe.html?plan=monitor&amp;zip={z}&amp;{UTM}">Set up notifications</a>
  <a class="btn btn-ghost" data-track="purchase_click_report" data-track-zip="{z}" href="/subscribe.html?plan=report&amp;zip={z}&amp;{UTM}">Get the full report</a>
</div>
<h2>{esc(faq_q)}</h2>
<p class="method">{esc(faq_a)}</p>
<h2>How this reading is computed</h2>
<p class="method">{METHOD_SENTENCE} <a href="/methodology.html">See the full explanation of each dial</a>, including the exact math and what goes into it.</p>
<h2>Nearby markets</h2>
<ul class="nearby">{nb}</ul>
<p style="margin-top:16px"><a href="/zip/{st}/">All {esc(state_name)} markets →</a></p>
{FOOTER.format(cite="")}
</div>
<script>
// Share this ZIP's reading. NOTHING PERSONAL — the button carries the ZIP,
// the reading word and the place name, all of which are already on the page.
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
    vc = vcopy(e.get("l") or "green")
    # FIGURES_KILL_SWITCH. A stub is pure metadata and its og:description IS a
    # figure — "Prices are down 3.1% from a year ago" was what a scraper got.
    # Routed through the switch for the same reason the page's metrics are:
    # card_stat over an empty block already returns a figure-free line.
    stat = card_stat(FIG.metrics(e.get("m", {})))
    # The card is rendered into /og/{the record's own month}/, so the stub has
    # to build the URL from the same place the page does. Reading meta.json
    # here pointed every released stub at /og/2026-06/{zip}.png — a month whose
    # cards are not rendered — while /zip/{zip}/ pointed at /og/2026-08/.
    period = e.get("p") or ""
    live = PAUSE.shows_data(z, e.get("b", PAUSE.LEGACY_BASIS))
    # A share stub is pure metadata — its whole job is to be read by a scraper
    # rather than a person, which is exactly why it must honour the pause. It
    # had no pause check at all, so every /s/{zip} was serving the verdict word
    # in <title> and a metric in og:description while the page it points at
    # showed the refresh notice (verified live on /s/20601/). The per-ZIP OG
    # image goes with it: the card has the numbers painted into the pixels.
    og_img = (f"{SITE}/og/{period}/{z}.png"
              if has_card and live and period and FIG.shows_figures()
              else f"{SITE}/og/default.png")

    def _title(p_, label="housing market check", show_zip=True):
        return f"{p_} {label}: {vc['word']} — {vc['short']}" + (f" ({z})" if show_zip else "")
    if not live:
        og_title = PAUSE.title_for(f"{city}, {st} ({z})")
        og_desc = PAUSE.NOTICE_DESC
        # og:image:alt was interpolated inline in the template below, so the
        # branch that blanked the title and description never reached it and
        # it kept serving the verdict word AND a metric to every scraper.
        og_alt = PAUSE.NOTICE_TITLE
    else:
        for cand in (_title(f"{city}, {st}"), _title(city), _title(city, "market check"),
                     _title(city, "market check", False)):
            og_title = cand
            if len(cand) <= 70:
                break
        og_desc = f"{stat}. Free monthly reading for any U.S. ZIP."
        og_alt = f"{city}, {st} {z}: {vc['word']} — {vc['translation']}. {stat}"
    dest = f"/?from={z}&amp;utm_source=share"
    dest_js = f"/?from={z}&utm_source=share"

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
{PAUSE.robots_meta()}
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self' https://kfbjooteazwvdsonthba.supabase.co; img-src 'self' data:; object-src 'none'; base-uri 'self'">
<meta name="referrer" content="strict-origin-when-cross-origin">
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
<meta property="og:image:alt" content="{esc(og_alt)}">
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


def coverage_line(live, total, noun, as_of=""):
    """The one sentence that states how much of the site is actually live.

    ONE SOURCE OF TRUTH. The counts used to be typed per surface — "33,000+"
    on the homepage, len(entries) on a hub, a manifest sum on the index — and
    they disagreed with each other and with the site. `live` is the number of
    ZIPs that pass data_pause.shows_data(zip, basis); `total` is the number of
    standing pages. Both are computed in main() from the manifest and the
    provisioned records, so neither can be typed wrong here.

    "with enough reported sales to score" is gone with them. The v2 engine
    reads active listings; it cannot see a closed sale, so no page has ever
    been gated on one and the phrase was false wherever it appeared.

    DEGRADES RATHER THAN LYING. provision_readings runs before this builder,
    and the CI smoke path runs it with --no-readings — where `live` is 0. A
    sentence that published "Live readings for 0 of 22,874 ZIP codes" as fact
    would be the same class of error this function exists to end, so a zero
    count states coverage without a number instead.
    """
    if not live:
        return f"Housing-market pages for {total:,} {noun}. Readings are being rebuilt."
    line = (f"Live readings for {live:,} of {total:,} {noun}, computed from "
            f"licensed active-listing statistics; the rest are being rebuilt.")
    return f"{line} Data through {pretty_month(as_of)}." if as_of else line


def hub_coverage_prose(live, as_of=""):
    """The /zip/ hub's coverage sentence, count-free by decision (2026-08-26).

    Exact site-wide coverage counts live on /methodology.html ONLY — the
    crawl gate asserts both the presence there and the absence here. The
    conversion problem the counts caused: "5,000 of 22,874" told four out of
    five visitors their ZIP was in the unlucky pile before they looked.
    coverage_line() (above) still serves the per-state hubs, whose counts are
    local facts rather than the site-wide pair.

    Degrades the same way coverage_line does: a build with no provisioned
    readings (CI's verify job) must not claim readings are live.
    """
    if not live:
        return "Housing-market pages for every U.S. ZIP with a standing page. Readings are being rebuilt."
    line = ("Free readings are live in thousands of U.S. ZIP codes, computed "
            "from licensed active-listing statistics; the rest are being "
            "rebuilt.")
    return f"{line} Data through {pretty_month(as_of)}." if as_of else line


def state_hub(st, entries, meta, live=None, total=None, as_of=""):
    """entries: sorted [(zip, city, county, tag, hex)]"""
    name = STATE_NAMES.get(st, st)
    if total is None:
        total = len(entries)
    if live is None:
        live = sum(1 for e in entries if e[3])
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
    # REDFIN SUNSET, PHASE 0: a state hub is a list of ratings, so its title
    # and description carry the rating vocabulary and the count. Both go.
    if PAUSE.shows_data():
        title = f"Housing market readings for every {name} ZIP code — ShouldISellYet"
        desc = (f"Free HOLD / WATCH / ACT readings for {live:,} of {total:,} {name} "
                f"ZIP codes, computed from licensed market statistics.")
    else:
        title = PAUSE.title_for(name)
        desc = PAUSE.NOTICE_DESC
    url = f"{SITE}/zip/{st}/"
    ld = json.dumps({"@context":"https://schema.org","@graph":[
        {"@type":"WebPage","@id":url,"url":url,"name":title,"description":desc,
         "inLanguage":"en-US",
         **({"dateModified": as_of} if as_of else {}),
         "isPartOf":{"@type":"WebSite","name":"ShouldISellYet","url":SITE+"/"}},
        {"@type":"BreadcrumbList","itemListElement":[
            {"@type":"ListItem","position":1,"name":"Home","item":SITE+"/"},
            {"@type":"ListItem","position":2,"name":"Markets by state","item":f"{SITE}/zip/"},
            {"@type":"ListItem","position":3,"name":name,"item":url}]}]}, separators=(",",":"))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
{PAUSE.robots_meta()}
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self' https://kfbjooteazwvdsonthba.supabase.co; img-src 'self' data:; object-src 'none'; base-uri 'self'">
<meta name="referrer" content="strict-origin-when-cross-origin">
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
<p class="method">{esc(coverage_line(live, total, f"{name} ZIP codes", as_of))}</p>
{''.join(body)}
{FOOTER.format(cite=hub_cite() + ". " + PLACES_CITE + ". ")}
</div></body></html>"""


def markets_index(states, meta, live=None, total=None, as_of=""):
    if total is None:
        total = sum(n for _, n in states)
    if live is None:
        live = 0
    items = "".join(f'<li><a href="/zip/{st}/">{esc(STATE_NAMES.get(st, st))}</a> <span class="z">{n}</span></li>'
                    for st, n in sorted(states, key=lambda t: STATE_NAMES.get(t[0], t[0])))
    # The markets index had no pause branch, while the state hubs it links to
    # did — the same "covered the page, forgot the index above it" pattern that
    # produced the state-hub leak, one level up. It is not a per-ZIP reading,
    # but it promised readings in the present tense and dated them to a vintage
    # the pages below no longer show.
    # `live` is now the ZIP COUNT, so the layout switch needs its own name —
    # it used to shadow this one and the two mean different things.
    unpaused = PAUSE.shows_data()
    title = ("Browse housing markets by state — ShouldISellYet" if not unpaused
             else "Browse housing market readings by state — ShouldISellYet")
    desc = (f"Per-ZIP housing market pages for {total:,} U.S. ZIP codes. "
            f"{PAUSE.NOTICE_TITLE}." if not unpaused else
            f"HOLD / WATCH / ACT readings for {live:,} of {total:,} U.S. ZIP "
            f"codes, computed from licensed market statistics.")
    url = f"{SITE}/zip/"
    ld = json.dumps({"@context":"https://schema.org","@graph":[
        {"@type":"WebPage","@id":url,"url":url,"name":title,"description":desc,"inLanguage":"en-US",
         **({"dateModified": as_of} if as_of else {}),
         "isPartOf":{"@type":"WebSite","name":"ShouldISellYet","url":SITE+"/"}},
        {"@type":"BreadcrumbList","itemListElement":[
            {"@type":"ListItem","position":1,"name":"Home","item":SITE+"/"},
            {"@type":"ListItem","position":2,"name":"Markets by state","item":url}]}]}, separators=(",",":"))
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="UTF-8">
{PAUSE.robots_meta()}
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self' https://kfbjooteazwvdsonthba.supabase.co; img-src 'self' data:; object-src 'none'; base-uri 'self'">
<meta name="referrer" content="strict-origin-when-cross-origin">
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
<p class="method">{esc(hub_coverage_prose(live, as_of))}</p>
<ul class="statecols">{items}</ul>
{FOOTER.format(cite=hub_cite() + ". ")}
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
    # AI answer engines are the growth channel now — homeowners ask "should I
    # sell my house in {city}" straight to ChatGPT/Perplexity/AI Overviews, and
    # the goal is to be the source those engines cite. Nothing ever BLOCKED
    # these bots here (the old file was one universal group), but an explicit
    # named welcome is the strongest signal robots.txt can send, and it
    # survives any future tightening of the * group. The disallows repeat in
    # every group because a robots group that names a bot REPLACES * for it.
    # /s/ share stubs (meta-noindexed redirect shims) and admin.html (operator
    # plumbing, noindex) were never worth anyone's crawl budget — now stated.
    ai_bots = ["GPTBot", "OAI-SearchBot", "ClaudeBot", "Claude-SearchBot",
               "PerplexityBot", "Google-Extended", "CCBot"]
    deny = ("# The paid report is per-customer and gated; no value in crawling it.\n"
            "Disallow: /my-report.html\n"
            "Disallow: /s/\n"
            "Disallow: /admin.html\n")
    (web / "robots.txt").write_text(
        "User-agent: *\nAllow: /\n" + deny + "\n"
        "# AI answer engines — explicitly welcome.\n"
        + "".join(f"User-agent: {b}\n" for b in ai_bots)
        + "Allow: /\n" + deny + "\n"
        f"Sitemap: {SITE}/sitemap.xml\n", encoding="utf-8")
    return n


def write_llms_txt(web, meta, pages, live=0, as_of=""):
    """llms.txt — the site, described for answer engines, with live numbers.

    Generated (like robots.txt) so the coverage figures and data month can
    never go stale in a hand-edited file. Kept well under the convention's
    ~80-line comfort zone.

    The `scored` argument is gone: it was `len(read_manifest())`, which
    defaults to pages_only and so was the STANDING-PAGE count published under
    the wider scored set's name — 22,874 offered to four named crawlers as the
    number of ZIPs the site can speak for. One count, stated once.

    `live` and `as_of` come from the same count and the same records the ZIP
    pages render, not from meta.json — whose period is frozen at the last v1
    run, so this file told four named crawlers the site was "currently through
    June 2026" while every released page was dated August. When nothing is
    live (the --no-readings CI path) the coverage clause degrades to prose
    rather than publishing a zero.
    """
    pretty = pretty_month(as_of)
    summary = (
        f"ShouldISellYet.com computes a free plain-English housing-market "
        f"reading — HOLD, WATCH, or ACT — for U.S. ZIP codes from licensed "
        f"market statistics. Readings are live for {live:,} of the {pages:,} "
        f"ZIP codes with a standing page"
        + (f", current through {pretty}" if pretty else "")
        + "; the rest are being rebuilt. Operated by Yayday LLC. Not a "
          "brokerage; readings are general information, not financial or "
          "real-estate advice."
        if live else
        f"ShouldISellYet.com computes a free plain-English housing-market "
        f"reading — HOLD, WATCH, or ACT — for U.S. ZIP codes from licensed "
        f"market statistics. Readings are being rebuilt on a new data engine "
        f"and are not shown right now; all {pages:,} ZIP pages stay live. "
        f"Operated by Yayday LLC. Not a brokerage; readings are general "
        f"information, not financial or real-estate advice.")
    # Wrapped here rather than typed as fixed lines: the numbers change the
    # line breaks, and a blockquote whose ">" markers drift is the one part of
    # this file a crawler renders as prose.
    coverage = "\n".join("> " + ln for ln in textwrap.wrap(summary, 74))
    # The Realtor.com clause disappears with the kill switch. This file is read
    # by GPTBot, ClaudeBot, PerplexityBot and CCBot (robots.txt allows all
    # four), so a credit left here outlives one on any rendered page.
    rdc = (" · Listing data from Realtor.com® Economic Research"
           if RDC.shows_crosscheck() else "")
    (web / "llms.txt").write_text(f"""# ShouldISellYet

{coverage}

## How the reading works

{METHOD_SENTENCE} The same signals are tested in the strengthening direction, so a clean
market with unusual buyer competition reads as a strong seller's market.

## Key pages

- [Methodology](https://shouldisellyet.com/research/methodology.html): index
  definition, danger lines, backtest, and changelog for the research series.
- [ShouldISellYet Research](https://shouldisellyet.com/research/): the monthly
  Warning-Sign Index — the share of scored ZIP markets showing warning signs —
  with state league tables and downloadable CSVs (use with attribution; no
  dataset redistribution).
- [Markets by state](https://shouldisellyet.com/zip/): standing reading pages
  for {pages:,} ZIP markets, each with its signal gauges and danger lines.
- [Sample report](https://shouldisellyet.com/report.html): the shape of the
  paid full report. Its market figures are being rebuilt on a new data engine
  and are not shown right now.
- [Press](https://shouldisellyet.com/press.html): coverage facts and contact.

## Citing this site

Cite as: "Source: ShouldISellYet (shouldisellyet.com)" — link either the
research hub or the specific ZIP page. Research CSVs may be quoted and charted
with that attribution; redistributing them as a dataset, or using them to build
a competing data product or service, is not permitted. Full terms ship with
each release as LICENSE.txt.

## Data attribution

Market data: Market statistics from a licensed data provider{rdc} · FHFA
ZIP-level house price index (benchmark, public domain) · Freddie Mac PMMS
30-yr weekly average (mortgage rate). Place names from GeoNames.org (CC BY
4.0). No source sponsors, endorses, or partners with this site.
""", encoding="utf-8")


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

    # THE URL SET COMES FROM THE MANIFEST, NOT FROM THE DATA.
    #
    # It used to be derived here: glob the per-ZIP records and keep whatever
    # passed a completeness test over vendor metrics. That made the published
    # URL set an emergent property of a vendor's monthly coverage, and it made
    # the build fail catastrophically rather than gracefully — with the
    # metrics gone, every ZIP failed the test, zero directories were emitted,
    # and since generated directories are rebuilt each deploy, the deploy
    # would have DELETED ~23,000 live URLs.
    #
    # pipeline/data/page_manifest.csv freezes that decision as a committed,
    # reviewable contract of zip,state. Records now arrive from
    # provision_readings.py: a released ZIP carries its reading, everything
    # else carries {"st": ST} and renders the notice. Losing a reading
    # degrades a page; losing a page destroys a URL. Only one of those is
    # recoverable, so the manifest governs.
    manifest = read_manifest()
    if not manifest:
        raise SystemExit("page_manifest.csv is missing or empty — refusing to "
                         "build, because emitting zero pages deletes every "
                         "live ZIP URL.")
    # Per-ZIP files now (see provision_readings.write). Only the manifest's
    # ZIPs are read, so this is 22,874 small opens rather than a glob of
    # everything that happens to be in the directory.
    entries = {}
    # The build reads the PRIVATE record set. web/data/z carries only state
    # codes now — the figures were removed from it because 5,000 per-ZIP files
    # holding a twelve-month history each is a downloadable dataset, whatever
    # the file layout. Pages still render their own ZIP's figures; they just
    # get them from a directory that never ships.
    zdir = ROOT / ".build" / "readings"
    for zip_code, _st in manifest:
        f = zdir / f"{zip_code}.json"
        if f.exists():
            entries[zip_code] = json.loads(f.read_text())

    eligible, skipped = [], defaultdict(int)
    for z, st in manifest:
        if only and z not in only:
            continue
        if z not in places:
            skipped["no_city_name"] += 1; continue
        # A manifest row with no provisioned record still gets its page. The
        # record only decides whether a reading renders.
        e = entries.get(z) or {"st": st}
        e.setdefault("st", st)
        eligible.append((z, e))
    if not only and len(eligible) + sum(skipped.values()) != len(manifest):
        raise SystemExit(f"manifest has {len(manifest):,} rows but "
                         f"{len(eligible):,} pages were prepared — refusing to "
                         f"build a short site.")
    eligible.sort()
    if args.limit:
        eligible = eligible[:args.limit]

    # THE COUNTS. Every coverage sentence on the site derives from these two
    # lines and nothing else. `live` is the predicate the ZIP pages, the hub
    # rows and the sitemap already use — released tranche AND a record whose
    # basis is the released one — so a hub cannot claim a reading that the
    # page it links to refuses to show.
    live_pairs = [(z, e) for z, e in eligible
                  if PAUSE.shows_data(z, e.get("b", PAUSE.LEGACY_BASIS))]
    live_zips = {z for z, _ in live_pairs}
    live_by_state = defaultdict(int)
    for z in live_zips:
        live_by_state[places[z][1]] += 1
    # The site's data vintage is the as-of month the live readings agree on.
    # Taking the most recent rather than meta.json's frozen build period is
    # the whole of rule 5 at the aggregate level: no live reading, no date.
    as_of = max((e.get("p") or "" for _, e in live_pairs), default="")

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
    # Rank by market size. v1 entries have `sold`; v2 entries do not, so they
    # fall back to the active listing count — without it every re-scored ZIP
    # would sort as zero and quietly lose its share card.
    top = {z for z, _ in sorted(eligible, key=lambda t: -((t[1].get("m", {}).get("sold")
                                or t[1].get("m", {}).get("inv") or 0)))[:args.top_cards]}
    card_set = dmv | top
    # A card is written to /og/{month}/{zip}.png and the page builds that URL
    # from ITS OWN record. Using meta.json's period here wrote every card into
    # /og/2026-06/ while every released page pointed at /og/2026-08/ — cards
    # rendered, deployed, and linked by nobody. The month now comes from the
    # same record on both sides.
    og_dir = web / "og"
    cards_made = 0
    # Stale cards are cleared FIRST, unconditionally. This used to sit inside
    # the else-branch below, so a build without Pillow — or with --no-cards —
    # left a previous build's per-ZIP cards in place, and they shipped in the
    # artifact. Clearing is not the part that needs Pillow.
    if og_dir.exists():
        shutil.rmtree(og_dir)
    og_dir.mkdir(parents=True, exist_ok=True)

    if not args.no_cards:
        try:
            # Probe PIL ITSELF. og_card imports it lazily inside render_card,
            # so importing og_card always succeeds and this guard never fired:
            # a machine without Pillow crashed the build at the first render
            # instead of degrading to the brand card as the message promises.
            # Found when a new CI job did not install it.
            import PIL  # noqa: F401
            from og_card import render_card
        except ImportError as exc:
            print(f"WARNING: Pillow missing ({exc}) — skipping cards, pages fall back to the brand card")
            card_set = set()
        else:
            render_card("", "", "", "green", "Is your ZIP's market turning?", " ",
                        og_dir / "default.png")     # generic brand card
            for z, e in eligible:
                if z not in card_set:
                    continue
                # A card is a PICTURE OF THE READING: render_card paints the
                # verdict and card_stat's figure into the pixels. The pages
                # stopped pointing at these on day one of the pause, but the
                # images kept being generated and kept deploying, so ~3,400 of
                # them sat at /og/{period}/{zip}.png returning 200 to anyone
                # who asked — including anything that had cached the URL from
                # a share. A file nobody links to is still a published file.
                if not PAUSE.shows_data(z, e.get("b", PAUSE.LEGACY_BASIS)):
                    continue
                cp = e.get("p") or ""
                if not cp:
                    continue        # no month, no cache-busting path, no card
                city, st, _ = places[z]
                (og_dir / cp).mkdir(parents=True, exist_ok=True)
                # FIGURES_KILL_SWITCH. The stat line is the card's evidence
                # row and the one place on it a vendor figure appears; the
                # word, the translation and the place are ours. Re-rendering
                # under the switch therefore leaves a card that is still worth
                # having — but the PAGES stop pointing at /og/{month}/ anyway
                # (see zip_page), because cards rendered before the flip are
                # still on disk with their figures painted in, and a file
                # nobody links to is still a published file.
                render_card(z, city, st, e.get("l") or "green",
                            card_stat(FIG.metrics(e.get("m", {}))),
                            pretty_month(cp), og_dir / cp / f"{z}.png")
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
        k = KINDS[e.get("l") or "green"]
        # The hub lists every ZIP in the state with its verdict word beside it.
        # zip_page() blanks the word for a paused ZIP, but that happens inside
        # zip_page — the hub builds its own row here and was publishing the
        # readings the pages themselves refuse to show (verified live on
        # /zip/MD/: 137 HOLD, 127 ACT, 108 WATCH). Released ZIPs keep theirs.
        if PAUSE.shows_data(z, e.get("b", PAUSE.LEGACY_BASIS)):
            # Qualified here for the same reason as the meta description: a
            # hub row is a word and a colour, and the row above it may carry
            # the danger reading under the same word.
            tag = k["tag"] + (" · seller's market"
                              if e.get("l") == "strong" and k["tag"] == KINDS["red"]["tag"]
                              else "")
            by_state[st].append((z, city, county, tag, k["hex"]))
        else:
            by_state[st].append((z, city, county, "", "#6b6861"))

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

    for st, rows in by_state.items():
        d = stage / st
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            state_hub(st, sorted(rows), meta, live=live_by_state.get(st, 0),
                      total=len(rows), as_of=as_of), encoding="utf-8")
    (stage / "index.html").write_text(
        markets_index([(st, len(v)) for st, v in by_state.items()], meta,
                      live=len(live_zips), total=len(eligible), as_of=as_of),
        encoding="utf-8")

    if final.exists():
        shutil.rmtree(final)
    stage.rename(final)

    # lastmod was meta.json's "generated" — 2026-08-10, frozen at the last v1
    # run and asserted on all 22,874 URLs as when each last changed. The
    # readings' own as-of month is the only vintage the site can stand behind;
    # a bare YYYY-MM is valid W3C Datetime, which is what sitemaps take. With
    # nothing live there is no data vintage, so the build date is the honest
    # answer to "when did this file last change".
    lastmod = as_of or date.today().isoformat()
    # /zip/ carries noindex while paused, and submitting a noindexed URL tells
    # a crawler two opposite things at once — the same reasoning that holds the
    # research pages out below. It was the one paused-tree URL still in the
    # submitted sitemap.
    # methodology.html states the sources, the basis and the danger lines. It
    # is disclosure, it stays true while paused, and it is what /methodology
    # now resolves to — so unlike the reading surfaces it belongs in the
    # sitemap whether or not readings are showing.
    urls = [f"{SITE}/", f"{SITE}/press.html", f"{SITE}/methodology.html"]
    if PAUSE.shows_data():
        urls.append(f"{SITE}/zip/")
        # The sample report exists to show a real reading. While paused it
        # shows the notice instead and carries noindex, so submitting it says
        # two opposite things — the same rule already applied to /zip/ and the
        # research tree. It was one of only three URLs in this list, and the
        # WATCH it published for ZIP 20906 was submitted for indexing for the
        # whole of the pause.
        urls.append(f"{SITE}/report.html")
    # Research releases: indexable by design — the citation flywheel needs
    # crawlers to find them. URLs derive from the committed research JSONs,
    # same discipline as the rest of this explicit list.
    research_months = sorted(p.stem.replace("research-", "") for p in
                             (Path(__file__).parent / "research").glob("research-*.json"))
    if research_months:
        # Paused: these restate the index and the ratings and now carry
        # noindex, and submitting a noindexed URL tells a crawler two opposite
        # things at once.
        if PAUSE.shows_data():
            urls += [f"{SITE}/research/", f"{SITE}/research/methodology.html"]
            urls += [f"{SITE}/research/{m}/" for m in research_months]
    # Paused pages stay live and crawlable — that is how the noindex gets
    # read — but leave the submitted sitemap so Phase 4 can re-add them in
    # tranches. State hubs go too: each lists a rating per ZIP.
    if PAUSE.shows_data():
        urls += [f"{SITE}/zip/{st}/" for st in sorted(by_state)]
        urls += [f"{SITE}/zip/{z}/" for z, _ in eligible]
    else:
        # Phase 4: a released ZIP re-enters the submitted sitemap; everything
        # else stays out. State hubs stay out until the pause lifts entirely —
        # each lists a rating per ZIP, so a hub for a part-released state
        # would publish withheld readings beside released ones.
        # WITH the basis. Passing only the ZIP asks the tranche file, not the
        # record, and submits a page that carries noindex — the third place
        # the same split showed up on 2026-08-20, after the head and the body.
        live = sorted(live_zips)
        urls += [f"{SITE}/zip/{z}/" for z in live]
        held = len(eligible) - len(live) + len(by_state)
        print(f"prior-vendor sunset: {held:,} ZIP/state URLs held out of the "
              f"sitemap (pages stay live and noindexed)")
        if live:
            print(f"phase 4: {len(live):,} released ZIP URLs re-added to the sitemap")
        # A ZIP released before its v2 reading landed renders legacy numbers.
        # shows_data() already refuses to show them; this reports the mistake
        # rather than letting it pass as an ordinary paused page.
        wrong = [z for z, e in eligible
                 if PAUSE.wrongly_promoted(z, e.get("b", PAUSE.LEGACY_BASIS))]
        if wrong:
            print(f"::warning::phase 4: {len(wrong):,} released ZIP(s) still "
                  f"carry a legacy reading and stay dark — {', '.join(wrong[:5])}"
                  f"{' …' if len(wrong) > 5 else ''}")
    chunks = write_sitemaps(web, urls, lastmod)
    # pages = ZIPs with a standing page; live = those actually showing one.
    # Both come from this run so llms.txt can't drift — which is also why a
    # LIMITED build must not write it: --limit / --only shrink len(eligible),
    # and a smoke build that reached the host would publish "standing pages
    # for 2 ZIP markets" as fact.
    #
    # The old `scored` count came from the per-ZIP files, which used to be
    # committed source covering every ZIP the vendor scored. They are
    # provisioned output now, so that count became a count of whatever this
    # run happened to write — a build whose provisioning was skipped published
    # "for 0 U.S. ZIP codes" as fact. It was then replaced by len(manifest),
    # which is pages_only and so was the SAME number as `pages` under a wider
    # name. Two counts that were one count: now there is one.
    if not (args.limit or only):
        write_llms_txt(web, meta, len(eligible),
                       live=len(live_zips), as_of=as_of)

    print(f"pages: {len(eligible):,} ZIP + {len(by_state)} state hubs + 1 index")
    print(f"skipped: {dict(skipped)}")
    print(f"html: {total_bytes/1e6:.1f} MB total · avg {total_bytes/max(1,len(eligible))/1024:.1f} KB · largest {biggest/1024:.1f} KB")
    print(f"sitemap: index + {chunks} chunk(s), {len(urls):,} URLs, lastmod {lastmod}")
    print(f"share stubs: {len(eligible):,} at /s/{{zip}} · noindex, not in sitemap")
    if cards_made:
        cb = sum(f.stat().st_size for f in og_dir.rglob("*.png"))
        print(f"og cards: {cards_made:,} rendered ({len(dmv):,} DMV + top {args.top_cards:,}) "
              f"· {cb/1e6:.0f} MB · /og/{as_of}/ · {len(eligible)-cards_made:,} ZIPs use the brand card")


if __name__ == "__main__":
    main()
