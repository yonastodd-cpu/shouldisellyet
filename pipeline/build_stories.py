#!/usr/bin/env python3
"""web/stories/{slug}/ — one case study, told as five beats.

WHY THIS EXISTS. The methodology page already proves the product to a skeptic:
a backtest table, a disclosed seam, a deliberate miss. It proves nothing to a
homeowner, because it is written for someone who wants to audit us. This page
tells one of those cases as a story a stranger can finish in a minute, and it
is the best cold-audience link in the arsenal — the thing a social post can
point at before anyone trusts us enough to check their own ZIP.

WHY A NEW RENDERER RATHER THAN THE EXISTING CHART. The case charts on the
methodology page are 1200x675 PNGs drawn with Pillow by tools/backtest_cases.py.
Three facts ruled them out here:
  * that script is NOT in the deploy workflow. It streams two Redfin exports
    (~1GB of cache) before it can draw anything, and has no charts-only mode.
  * its main() PRUNES web/data/cases/ — anything not named in its own report is
    deleted, so a staged story asset written there would vanish on the next run.
  * it draws ONE fixed composite. A story needs the same data revealed in
    stages, which is a different picture, not a crop of that one.
So the panels here are inline SVG built from the committed case JSON. No
refetch, nothing to prune, and the story scales to the other cases for free.

EVERY NUMBER IS READ. The beats interpolate values from
web/data/cases/{id}.json — the same file the methodology page computes from —
so this page and that one cannot drift. Nothing is typed but prose.

Output is gitignored and rebuilt on every deploy, like every other generated
surface here. Run: python3 pipeline/build_stories.py
"""

import html
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "web" / "data" / "cases"
SITE = "https://shouldisellyet.com"

# Which cases are published as stories, in order. The template is general —
# austin-2021 and cape-coral-2022 are one line away each — but they are held
# back deliberately so there is a second and third story to publish later
# rather than three that all land on the same day.
PUBLISHED = ["boise-2021"]

# Brand palette, matching web/index.html's CSS custom properties. Literal here
# because these SVGs are also read by scrapers and social unfurlers, where a
# var() would resolve to nothing.
INK, MUTED, FAINT = "#1c2430", "#5c6673", "#a49d8d"
NAVY, GOLD, AMBER, RED = "#1f3a5f", "#8a7a55", "#c8891f", "#d64545"
HAIRLINE, PAPER = "#e7e2d8", "#faf8f4"

MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]


def esc(s):
    return html.escape(str(s), quote=True)


def pretty(period):
    """'2021-11' -> 'November 2021'. Returns the input unchanged if it is not
    a period, so a malformed case file degrades to something readable rather
    than raising during a deploy."""
    try:
        y, m = str(period).split("-")
        return f"{MONTHS[int(m) - 1]} {y}"
    except Exception:
        return str(period)


def short(period):
    """'2021-11' -> 'Nov 21' — for axis ticks, where room is the constraint."""
    try:
        y, m = str(period).split("-")
        return f"{MONTHS[int(m) - 1][:3]} {y[2:]}"
    except Exception:
        return str(period)


def money(n):
    return f"${round(n / 1000)}K"


def pct(x, places=0):
    return f"{x * 100:+.{places}f}%"


# ————— the panels —————
# One function, three stages. The reveal works in TWO directions and needs
# both: each stage adds a layer (price, then the tell, then the wait and the
# fall) AND extends how far along the timeline the lines are drawn.
#
# The second half is not decoration. Beat one says prices are at record highs
# and still climbing; drawing the whole series under it shows the crash before
# the sentence claiming nothing looks wrong, which is the one thing the panel
# must not do. So stages 1 and 2 stop at the signal month.
#
# The x-domain stays the FULL series in every stage even when the line stops
# early, so the drawn portion never shifts or rescales between panels. A reader
# watching the line grow in place reads it as one chart revealing itself; a
# reader watching it rescale reads it as three different charts.

W, H = 760, 300
PAD_L, PAD_R, PAD_T, PAD_B = 58, 18, 26, 34
PLOT_W = W - PAD_L - PAD_R
PRICE_H = 150                      # top band: price
TELL_TOP = PAD_T + PRICE_H + 30    # bottom band: the tell
TELL_H = 62


def _x(i, n):
    return PAD_L + (PLOT_W * i / max(1, n - 1))


def _price_y(v, lo, hi):
    span = max(1, hi - lo)
    return PAD_T + PRICE_H - (PRICE_H * (v - lo) / span)


def _tell_y(v, lo, hi):
    span = max(0.01, hi - lo)
    return TELL_TOP + TELL_H - (TELL_H * (v - lo) / span)


def panel(case, stage):
    """Inline SVG for one beat. stage is 1, 2 or 3."""
    s = case["series"]
    n = len(s)
    months = [r["month"] for r in s]
    prices = [r["price"] for r in s]
    tells = [r["dials"].get("dom_stretch") for r in s]

    p_lo, p_hi = min(prices), max(prices)
    known = [t for t in tells if t is not None]
    t_lo, t_hi = (min(known), max(known)) if known else (0.0, 1.0)

    sig_i = months.index(case["first_signal"]) if case["first_signal"] in months else None
    neg_i = months.index(case["first_negative_yoy"]) if case.get("first_negative_yoy") in months else None
    peak_i = months.index(case["peak_month"]) if case.get("peak_month") in months else None
    trough_i = months.index(case["trough_month"]) if case.get("trough_month") in months else None
    line = (case.get("crossings", {}).get("dom_stretch") or {}).get("line")

    out = [f'<svg viewBox="0 0 {W} {H}" role="img" xmlns="http://www.w3.org/2000/svg" '
           f'aria-label="{esc(_alt(case, stage))}">']
    out.append(f'<rect width="{W}" height="{H}" fill="{PAPER}"/>')

    # How far along the timeline this stage draws. Full series only at the end.
    cross_persist = (case.get("crossings", {}).get("dom_stretch") or {}).get("persisted") or 0
    last_price = (n - 1) if stage >= 3 else (sig_i if sig_i is not None else n - 1)
    last_tell = ((n - 1) if stage >= 3
                 else min(n - 1, (sig_i or 0) + max(1, cross_persist)))

    # Stage 3 shades the wait first, so every line lands on top of it.
    if stage >= 3 and sig_i is not None and neg_i is not None:
        x0, x1 = _x(sig_i, n), _x(neg_i, n)
        out.append(f'<rect x="{x0:.1f}" y="{PAD_T}" width="{max(1, x1 - x0):.1f}" '
                   f'height="{PRICE_H + 30 + TELL_H}" fill="{AMBER}" opacity="0.09"/>')
        gap = case.get("lead_months")
        if gap:
            out.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{PAD_T - 10}" text-anchor="middle" '
                       f'font-size="12" font-weight="700" fill="{AMBER}">'
                       f'{gap} months of warning</text>')

    # Price line — same geometry in every stage, drawn as far as `last_price`.
    pts = " ".join(f"{_x(i, n):.1f},{_price_y(v, p_lo, p_hi):.1f}"
                   for i, v in enumerate(prices) if i <= last_price)
    out.append(f'<polyline points="{pts}" fill="none" stroke="{NAVY}" stroke-width="2.4" '
               f'stroke-linejoin="round" stroke-linecap="round"/>')
    out.append(f'<text x="{PAD_L}" y="{PAD_T - 10}" font-size="11" font-weight="700" '
               f'fill="{NAVY}">Typical sale price</text>')

    # Price axis: the start, and the last value the line has actually reached.
    # NOT the series maximum in the early stages — printing $515K above a line
    # that stops at $464K sits directly under a sentence saying prices are at
    # record highs, and quietly contradicts it. The SCALE still spans the full
    # series so the line never moves between panels; only the label follows
    # what is drawn.
    for v in {p_lo, prices[last_price]} if stage < 3 else {p_lo, p_hi}:
        y = _price_y(v, p_lo, p_hi)
        out.append(f'<text x="{PAD_L - 8}" y="{y + 4:.1f}" text-anchor="end" font-size="10" '
                   f'fill="{FAINT}">{money(v)}</text>')

    # Stage 1 marks the month the signal fired, with prices still climbing —
    # the whole point of the first beat is that nothing looks wrong yet.
    if sig_i is not None:
        x = _x(sig_i, n)
        rule_bottom = (TELL_TOP + TELL_H) if stage >= 2 else (PAD_T + PRICE_H)
        out.append(f'<line x1="{x:.1f}" y1="{PAD_T}" x2="{x:.1f}" y2="{rule_bottom}" '
                   f'stroke="{GOLD}" stroke-width="1.2" stroke-dasharray="3 3"/>')
        out.append(f'<circle cx="{x:.1f}" cy="{_price_y(prices[sig_i], p_lo, p_hi):.1f}" r="4" '
                   f'fill="{PAPER}" stroke="{GOLD}" stroke-width="2.4"/>')

    # Stage 2 adds the tell.
    if stage >= 2 and known:
        tp = " ".join(f"{_x(i, n):.1f},{_tell_y(v, t_lo, t_hi):.1f}"
                      for i, v in enumerate(tells) if v is not None and i <= last_tell)
        if line is not None:
            ly = _tell_y(line, t_lo, t_hi)
            out.append(f'<line x1="{PAD_L}" y1="{ly:.1f}" x2="{W - PAD_R}" y2="{ly:.1f}" '
                       f'stroke="{RED}" stroke-width="1.2" stroke-dasharray="5 4"/>')
            out.append(f'<text x="{W - PAD_R}" y="{ly - 6:.1f}" text-anchor="end" font-size="10" '
                       f'fill="{RED}">danger line — {pct(line)} vs a year ago</text>')
        out.append(f'<polyline points="{tp}" fill="none" stroke="{AMBER}" stroke-width="2.2" '
                   f'stroke-linejoin="round" stroke-linecap="round"/>')
        out.append(f'<text x="{PAD_L}" y="{TELL_TOP - 8}" font-size="11" font-weight="700" '
                   f'fill="{AMBER}">How much longer homes sat than a year earlier</text>')
        if sig_i is not None and tells[sig_i] is not None:
            out.append(f'<circle cx="{_x(sig_i, n):.1f}" cy="{_tell_y(tells[sig_i], t_lo, t_hi):.1f}" '
                       f'r="4.5" fill="{RED}"/>')

    # Stage 3 marks the fall itself.
    if stage >= 3 and peak_i is not None and trough_i is not None:
        for i, lab in ((peak_i, money(prices[peak_i])), (trough_i, money(prices[trough_i]))):
            out.append(f'<circle cx="{_x(i, n):.1f}" cy="{_price_y(prices[i], p_lo, p_hi):.1f}" '
                       f'r="4" fill="{NAVY}"/>')
        ptt = case.get("peak_to_trough")
        if ptt is not None:
            xm = (_x(peak_i, n) + _x(trough_i, n)) / 2
            ym = _price_y((prices[peak_i] + prices[trough_i]) / 2, p_lo, p_hi)
            out.append(f'<text x="{xm:.1f}" y="{ym - 12:.1f}" text-anchor="middle" font-size="13" '
                       f'font-weight="700" fill="{NAVY}">{pct(ptt, 1)}</text>')

    # Time axis: first, the signal, and last. Enough to orient, no more.
    last_drawn = max(last_price, last_tell if stage >= 2 else 0)
    ticks = {0: short(months[0]), last_drawn: short(months[last_drawn])}
    if sig_i is not None and sig_i != last_drawn:
        ticks[sig_i] = short(months[sig_i])
    for i, lab in sorted(ticks.items()):
        anchor = "start" if i == 0 else ("end" if i == last_drawn else "middle")
        out.append(f'<text x="{_x(i, n):.1f}" y="{H - 10}" text-anchor="{anchor}" font-size="10" '
                   f'fill="{FAINT}">{lab}</text>')

    out.append("</svg>")
    return "".join(out)


def _alt(case, stage):
    """Alt text carries the same fact the panel does — a screen reader gets the
    story, not 'chart'."""
    name, sig = case["name"], pretty(case["first_signal"])
    if stage == 1:
        return (f"Typical sale price in {name}, rising through {sig}, "
                f"with {sig} marked.")
    if stage == 2:
        return (f"The same price line, with how much longer homes sat than a year "
                f"earlier crossing its danger line in {sig} while prices kept rising.")
    return (f"The same chart with the {case.get('lead_months')} months between the "
            f"{sig} signal and the first price fall shaded, and the peak-to-trough "
            f"change of {pct(case.get('peak_to_trough'), 1)} marked.")


# ————— the beats —————

def beats(case):
    """(kicker, prose, stage-or-None) per beat. Prose interpolates the case
    file; the only literals are connective words."""
    name = case["name"]
    sig, neg = pretty(case["first_signal"]), pretty(case.get("first_negative_yoy"))
    lead = case.get("lead_months")
    ptt = case.get("peak_to_trough")
    cross = (case.get("crossings", {}) or {}).get("dom_stretch") or {}
    persisted = cross.get("persisted")
    peak, trough = case.get("peak_price"), case.get("trough_price")

    return [
        ("The setup",
         f"{sig}. {name} is one of the hottest housing markets in America. "
         f"Prices are at record highs and still climbing. Every headline says boom.",
         1),
        ("The tell",
         f"But underneath, one thing had changed: homes were suddenly taking far "
         f"longer to sell. That month {name} crossed a line that has historically "
         f"come before price declines — homes sitting {pct(cross.get('value'))} longer "
         f"than a year earlier, against a danger line of {pct(cross.get('line'))}"
         + (f", and it stayed across for {persisted} months running" if persisted else "")
         + f". Prices did not blink for another {lead} months.",
         2),
        ("What followed",
         f"Prices began to fall in {neg}. From their peak of {money(peak)} they reached "
         f"{money(trough)} — a change of {pct(ptt, 1)}.",
         3),
        ("The point",
         f"A {name} homeowner watching this signal had {lead} months of a strong "
         f"seller's market to decide in — sell, refinance, renovate, or stay, with "
         f"eyes open. That is the entire product: not a prediction, a head start.",
         None),
    ]


def coda(miss):
    """The honesty beat. Small print, load-bearing — a track record with no
    misses is a sales page. Reads the miss case so it can never describe a
    market the data does not support."""
    if not miss:
        return ""
    name, sig = miss.get("name"), pretty(miss.get("first_signal"))
    worst = miss.get("peak_to_trough")
    tail = (f" — its worst dip was {pct(worst, 1)}" if worst is not None else "")
    return (f"<p class=\"coda\">And sometimes the alarm is burnt toast. "
            f"{esc(name)} crossed a line in {esc(sig)} and recovered{esc(tail)}. "
            f"We show that case too: a track record with no misses is a sales page, "
            f"not a record. Every chart here is recomputed from the same data and the "
            f"same danger lines we use today, not quoted from memory. "
            f"<a href=\"/methodology/\">See the methodology</a>.</p>")


CSS = """
*{box-sizing:border-box}
body{margin:0;background:#faf8f4;color:#1c2430;
  font-family:'Newsreader',Georgia,serif;font-size:18px;line-height:1.6}
.wrap{max-width:820px;margin:0 auto;padding:0 22px 80px}
nav{display:flex;align-items:center;gap:12px;padding:18px 0;border-bottom:1px solid #e7e2d8;
  margin-bottom:44px}
nav a{display:flex;align-items:center;gap:12px;text-decoration:none;color:inherit}
.logo-word{font-weight:650;font-size:1.05rem}
.eyebrow{font-family:ui-monospace,'IBM Plex Mono',monospace;font-size:11px;letter-spacing:.12em;
  text-transform:uppercase;color:#8a7a55;margin-bottom:14px}
h1{font-size:clamp(2rem,5.4vw,3rem);line-height:1.14;margin:0 0 18px;font-weight:600}
.standfirst{font-size:1.15rem;color:#5c6673;margin:0 0 10px}
.beat{margin:52px 0}
.beat h2{font-size:.78rem;font-family:ui-monospace,'IBM Plex Mono',monospace;letter-spacing:.14em;
  text-transform:uppercase;color:#8a7a55;margin:0 0 10px;font-weight:600}
.beat p{margin:0}
.panel{margin:22px 0 0;border:1px solid #e7e2d8;border-radius:10px;background:#fff;padding:10px}
.panel svg{display:block;width:100%;height:auto}
.coda{font-size:.95rem;color:#5c6673;border-top:1px solid #e7e2d8;padding-top:22px;margin-top:52px}
.end{margin-top:52px;border:1px solid #e7e2d8;border-radius:12px;background:#fff;padding:28px}
.end h2{margin:0 0 8px;font-size:1.5rem}
.end p{margin:0 0 18px;color:#5c6673;font-size:1rem}
.zipform{display:flex;gap:10px;flex-wrap:wrap}
.zipform input{flex:1 1 180px;padding:14px 16px;border:1px solid #e7e2d8;border-radius:8px;
  font-family:ui-monospace,'IBM Plex Mono',monospace;font-size:1rem;background:#faf8f4}
.btn{display:inline-block;padding:14px 22px;border-radius:8px;background:#1f3a5f;color:#fff;
  border:0;text-decoration:none;font-family:inherit;font-size:1rem;font-weight:600;cursor:pointer}
.foot{margin-top:56px;padding-top:22px;border-top:1px solid #e7e2d8;font-size:.85rem;color:#a49d8d}
.foot a{color:#5c6673}
a{color:#1f3a5f}
@media (max-width:560px){ .beat{margin:38px 0} }
"""


def story_page(case, miss):
    name = case["name"]
    lead, ptt = case.get("lead_months"), case.get("peak_to_trough")
    sig = pretty(case["first_signal"])
    title = f"The data spoke first: {name}"
    desc = (f"In {sig}, {name} crossed a housing danger line while prices were still "
            f"rising. Prices began falling {lead} months later, for a peak-to-trough "
            f"change of {pct(ptt, 1)}.")
    url = f"{SITE}/stories/{slug(case)}/"

    body = []
    for kicker, prose, stage in beats(case):
        body.append(f'<section class="beat"><h2>{esc(kicker)}</h2><p>{esc(prose)}</p>')
        if stage:
            body.append(f'<div class="panel">{panel(case, stage)}</div>')
        body.append("</section>")

    # JSON-LD: an Article, because that is what this is. No claims in here that
    # are not also visible on the page.
    ld = {
        "@context": "https://schema.org", "@type": "Article",
        "headline": title, "description": desc, "url": url,
        "isAccessibleForFree": True,
        "publisher": {"@type": "Organization", "name": "ShouldISellYet",
                      "url": SITE},
        "about": {"@type": "Place", "name": name},
    }

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(title)} — ShouldISellYet</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{esc(url)}">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(title)}">
<meta property="og:description" content="{esc(desc)}">
<meta property="og:url" content="{esc(url)}">
<meta property="og:site_name" content="ShouldISellYet">
<meta property="og:image" content="{SITE}/og/default.png">
<meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<!-- This page exists to be the cold-audience link, so it is the LAST page that
     should arrive untracked. Anonymous counting only; honours DNT/GPC. -->
<script src="/track.js" defer></script>
<script type="application/ld+json">{json.dumps(ld, separators=(",", ":"))}</script>
<style>{CSS}</style></head><body><div class="wrap">
<nav><a href="/"><img src="/logo-mark.svg" alt="" width="36" height="36">
  <span class="logo-word">Should I sell yet?</span></a></nav>

<div class="eyebrow">The data spoke first</div>
<h1>{esc(title)}</h1>
<p class="standfirst">{esc(desc)}</p>

{"".join(body)}

{coda(miss)}

<div class="end">
  <h2>This check is free for your ZIP.</h2>
  <p>One plain answer for your own market — hold, watch, or act.</p>
  <form class="zipform" action="/" method="get">
    <input name="zip" placeholder="ZIP code" inputmode="numeric" maxlength="5"
           aria-label="ZIP code" autocomplete="postal-code">
    <button class="btn" type="submit">Check my ZIP — free</button>
  </form>
</div>

<div class="foot">
  Recomputed from the same public data and danger lines used today
  ({esc(case.get("computed_from", ""))}).
  <a href="/methodology/">Methodology</a> · <a href="/">Home</a>
</div>
</div></body></html>"""


def slug(case):
    """boise-2021 -> boise. The year is an internal disambiguator; a shared
    link should read as a place."""
    return str(case["id"]).rsplit("-", 1)[0]


def main():
    if not CASES.exists():
        print("build-stories: no case data — nothing to build")
        return 0

    def load(cid):
        p = CASES / f"{cid}.json"
        return json.loads(p.read_text()) if p.exists() else None

    # The miss is found rather than named, so renaming the case file cannot
    # silently drop the honesty coda.
    miss = next((c for c in (load(Path(f).stem) for f in
                             sorted(p.name for p in CASES.glob("*.json")))
                 if c and c.get("kind") == "miss"), None)
    if miss is None:
        print("build-stories: no miss case found — refusing to publish a "
              "track record with no misses")
        return 0

    out = ROOT / "web" / "stories"
    out.mkdir(parents=True, exist_ok=True)
    written, facts = 0, []
    for cid in PUBLISHED:
        case = load(cid)
        if not case or not case.get("series"):
            print(f"build-stories: {cid} missing or has no series — skipped")
            continue
        d = out / slug(case)
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(story_page(case, miss))
        written += 1
        facts.append({"slug": slug(case), "name": case["name"],
                      "first_signal": case["first_signal"],
                      "lead_months": case.get("lead_months"),
                      "peak_to_trough": case.get("peak_to_trough"),
                      "url": f"/stories/{slug(case)}/"})

    # The homepage teaser reads this, so the homepage types no numbers either.
    (ROOT / "web" / "data" / "stories.json").write_text(
        json.dumps({"stories": facts}, separators=(",", ":"), sort_keys=True))
    print(f"build-stories: {written} story page(s) written to web/stories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
