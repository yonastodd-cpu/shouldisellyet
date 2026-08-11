#!/usr/bin/env python3
"""ShouldISellYet — post-pack: one rendered card per marketing task.

    python3 pipeline/post_pack.py --render [--period 2026-06] [--out web/assets/mkt]

ONE MODE, ON PURPOSE. This runs on EVERY deploy beside build_research.py and
is pure: it reads the committed manifest pipeline/marketing/pack-{period}.json
that marketing_tasks.py wrote at refresh time, and draws PNGs. No network, no
Supabase, no clock — the same manifest always produces the same bytes, which
is what lets `git status` stay clean after a deploy and what makes
test_render_is_deterministic meaningful.

WHY THE OUTPUT IS PUBLIC. Cards land under web/, which GitHub Pages uploads
wholesale, so every card has a public URL. That is correct rather than
regrettable: these images exist to be posted to Instagram. They are also
gitignored (web/assets/mkt/) because they are re-rendered from the manifest on
every deploy — committing them would be committing a build artifact.

PRIVACY (og_card.py's contract, restated). Every renderer below takes only
PUBLIC aggregates as explicit scalars — a metro name, a share, a count, a
pre-formatted stat string. There is no dict passthrough, so a personal input
(home value, equity, rate, PITI) cannot reach a card even by accident. If a
future card needs another field, add it explicitly and this comment stays true.

VISUAL LANGUAGE. Reuses build_research._social_frame — the same 1080x1350
portrait frame the research release's social set uses — with the foot line
overridden, because a marketing card is not a research release and must not
foot with a /research/ URL. One brand, one frame, one place to change it.
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "pipeline" / "marketing"

# The generator's own guard lists, mirrored so a card cannot render copy the
# database would have refused. BANNED is docs/ATTRIBUTION.md's list; HYPE is
# the doom-account vocabulary a smoke detector does not use.
import marketing_config as MC


def compliant(text):
    """Tripped words in a string bound for a card, or []. Same bar as the
    generator's guard() and the marketing_tasks_no_affiliation_claim CHECK."""
    low = (text or "").lower()
    hits = [w for w in MC.BANNED if w in low]
    hits += [w for w in MC.NAOMI_NEVER if w in low]
    hits += [w for w in MC.HYPE if w in low]
    if re.search(r"\b0(\.0)? months?\b", low):
        hits.append("zero-months")
    return hits


MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def _pct(v):
    """A stored ratio as the percentage a reader expects. -0.1775 is a number
    only a database loves; a card that prints it has published nothing."""
    return "—" if v is None else f"{v * 100:+.1f}%"


def _pretty_month(s):
    """'2022-08' → 'August 2022'. Cards are read by people."""
    try:
        y, m = str(s).split("-")[:2]
        return f"{MONTH_NAMES[int(m) - 1]} {y}"
    except Exception:
        return str(s or "")


def _pretty_day(s):
    """'2026-07-31' → 'July 31, 2026'."""
    try:
        y, m, d = str(s).split("-")[:3]
        return f"{MONTH_NAMES[int(m) - 1]} {int(d)}, {y}"
    except Exception:
        return str(s or "")


# ————— card renderers —————
# Each takes explicit public scalars — never a dict passthrough — so a personal
# input cannot reach an image (og_card.py's contract, restated).
#
# THESE NO LONGER USE build_research._social_frame. That frame is two title
# lines and a footer, which is exactly the "no hierarchy, dead middle" the
# redesign existed to fix, and the research releases still want it unchanged.
# Sharing one frame across two jobs was the earlier call; it cost the marketing
# cards their hierarchy, so marketing draws its own. One brand, two layouts.
RULE_TINT = (226, 220, 208)


def _track(d, s, f, x, y, fill, extra=2.4):
    """Letterspacing by hand — Pillow has none, and tracking is what makes a
    small line read as a label rather than as shrunken prose."""
    for ch in s:
        d.text((x, y), ch, font=f, fill=fill)
        x += d.textlength(ch, font=f) + extra
    return x


def _shell(period_pretty, title, subtitle):
    """Masthead + title block + footer, shared by every marketing card.
    Returns (img, draw) with the body area from y≈300 to y≈1190 free."""
    from PIL import Image, ImageDraw
    from build_research import font, REG, BOLD, BG, INK, FAINT, MUTED
    W, H, M = 1080, 1350, 84
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    # No dangling separator when the period is missing: a masthead reading
    # "SHOULDISELLYET RESEARCH ·" looks like a truncated string, which is worse
    # than simply not dating the card.
    _track(d, (f"SHOULDISELLYET RESEARCH · {period_pretty.upper()}"
               if period_pretty else "SHOULDISELLYET RESEARCH"),
           font(BOLD, 21), M, 82, MUTED)
    d.line([(M, 132), (W - M, 132)], fill=INK, width=3)
    d.text((M, 172), title, font=font(BOLD, 56), fill=INK)
    if subtitle:
        d.text((M, 248), subtitle, font=font(REG, 23), fill=FAINT)
    d.line([(M, 1206), (W - M, 1206)], fill=INK, width=3)
    d.text((M, 1244), "SHOULDISELLYET", font=font(BOLD, 26), fill=INK)
    dom = "shouldisellyet.com"
    d.text((W - M - d.textlength(dom, font=font(REG, 26)), 1244), dom,
           font=font(REG, 26), fill=FAINT)
    return img, d


def card_metro(t):
    """Metro story card.

    HIERARCHY WITHOUT A SECOND TYPEFACE. Only IBM Plex Mono ships with this
    repo (CI must render identical bytes, so a font has to be committed), so
    the steps are size and weight: 21 eyebrow / 24 field label / 56 metro /
    250 hero. Four sizes and two weights do the work a serif would.

    THE TWO FIGURES MUST NOT BE ADDABLE. 76% moving toward a line and 63%
    rating HOLD are the SAME ZIP codes measured two ways, and they routinely
    sum past 100 — a caption has room to say so, a card does not. Three things
    stop the arithmetic here, in the order a reader meets them: the denominator
    is named ONCE above both ("two measures of the same 76 ZIP codes"), each
    figure sits under a numbered label posing a different QUESTION (where they
    are headed / where they stand today), and a closing line says the two
    overlap and do not sum. Someone who still adds them has been told three
    times.

    Accent is NAVY, never red. This brand is a smoke detector; red is a fire.
    """
    from build_research import font, REG, BOLD, INK, MUTED, FAINT, NAVY, GREEN

    M = 84
    RULE = RULE_TINT
    r = t.get("render") or {}
    det, hold = round(r.get("share_det") or 0), round(r.get("hold_share") or 0)
    zips = r.get("zips") or 0
    title = r.get("short_name") or r.get("name", "")
    sub = r.get("name", "")
    img, d = _shell(r.get("period_pretty", ""), title, sub if sub != title else "")
    track = lambda s, f, x, y, fill, extra=2.4: _track(d, s, f, x, y, fill, extra)

    # The denominator, once, before either figure.
    track(f"TWO MEASURES OF THE SAME {zips} ZIP CODES", font(REG, 22), M, 312, MUTED, 2.2)

    # ——— 1. the hero ———
    track("1 — WHERE THEY ARE HEADED", font(BOLD, 20), M, 386, FAINT, 2.6)
    d.text((M - 10, 384), f"{det}%", font=font(BOLD, 250), fill=NAVY)
    d.text((M, 668), "of them are moving toward a danger line —", font=font(REG, 31), fill=INK)
    d.text((M, 708), "the level where sellers have historically", font=font(REG, 31), fill=MUTED)
    d.text((M, 748), "started losing leverage.", font=font(REG, 31), fill=MUTED)

    # ——— 2. the counterweight ———
    d.line([(M, 872), (1080 - M, 872)], fill=RULE, width=2)
    track("2 — WHERE THEY STAND TODAY", font(BOLD, 20), M, 906, FAINT, 2.6)
    d.text((M, 948), f"{hold}%", font=font(BOLD, 76), fill=INK)
    x = M + d.textlength(f"{hold}%", font=font(BOLD, 76)) + 26
    d.text((x, 970), "still rate ", font=font(REG, 34), fill=INK)
    x += d.textlength("still rate ", font=font(REG, 34))
    d.text((x, 970), "HOLD", font=font(BOLD, 34), fill=GREEN)
    x += d.textlength("HOLD", font=font(BOLD, 34))
    d.text((x, 970), " today.", font=font(REG, 34), fill=INK)

    d.text((M, 1054), "The same ZIP codes, counted two ways: a market can rate",
           font=font(REG, 26), fill=MUTED)
    d.text((M, 1090), "HOLD today and still be drifting. These overlap; they do",
           font=font(REG, 26), fill=MUTED)
    d.text((M, 1126), "not sum.", font=font(REG, 26), fill=MUTED)

    return img


def card_receipt(t):
    """A receipt: the hero is the LEAD TIME, because that is the whole claim."""
    from build_research import font, REG, BOLD, INK, MUTED, FAINT, NAVY
    r = t.get("render") or {}
    lead = r.get("lead_days") or 0
    img, d = _shell(_pretty_month(str(r.get("published_on", ""))[:7]),
                    "We flagged it first", r.get("metro", ""))
    M = 84
    _track(d, "OUR HEAD START ON THE COVERAGE", font(REG, 22), M, 312, MUTED, 2.2)
    d.text((M - 10, 384), str(lead), font=font(BOLD, 250), fill=NAVY)
    x = M - 10 + d.textlength(str(lead), font=font(BOLD, 250))
    d.text((x + 16, 560), "days", font=font(BOLD, 64), fill=NAVY)
    d.text((M, 668), f"Our index flagged {r.get('metro','')}", font=font(REG, 31), fill=INK)
    d.text((M, 708), f"on {_pretty_day(r.get('flag_date'))}.", font=font(REG, 31), fill=MUTED)
    d.text((M, 748), f"{r.get('outlet','')} reported it on "
                     f"{_pretty_day(r.get('published_on'))}.", font=font(REG, 31), fill=MUTED)
    d.line([(M, 872), (1080 - M, 872)], fill=RULE_TINT, width=2)
    d.text((M, 912), "Every claim on this card is a published article with a",
           font=font(REG, 26), fill=MUTED)
    d.text((M, 948), "date. We log no receipt without a source.",
           font=font(REG, 26), fill=MUTED)
    return img


def card_case(t):
    """A track-record case: hero is the lead time in months, counterweight the
    decline that followed."""
    from build_research import font, REG, BOLD, INK, MUTED, FAINT, NAVY
    r = t.get("render") or {}
    n = r.get("lead_months") or 0
    # The masthead date is the DATA MONTH this card was published in, not the
    # case's own first-signal month: a 2021 stamp on a card posted in 2026 reads
    # as four years stale. The signal month belongs in the body, where it is
    # about the case rather than about the card.
    title = r.get("short_name") or r.get("name", "")
    sub = r.get("name", "")
    img, d = _shell(r.get("period_pretty", ""), title, sub if sub != title else "")
    M = 84
    _track(d, "WARNING BEFORE THE DECLINE", font(REG, 22), M, 312, MUTED, 2.2)
    d.text((M - 10, 384), str(n), font=font(BOLD, 250), fill=NAVY)
    x = M - 10 + d.textlength(str(n), font=font(BOLD, 250))
    d.text((x + 16, 560), "months", font=font(BOLD, 64), fill=NAVY)
    d.text((M, 668), f"of warning before home prices here", font=font(REG, 31), fill=INK)
    ptt = r.get("peak_to_trough")
    d.text((M, 708), f"fell {abs(ptt) * 100:.1f}% from their high."
           if ptt is not None else "fell from their high.",
           font=font(REG, 31), fill=MUTED)
    d.line([(M, 872), (1080 - M, 872)], fill=RULE_TINT, width=2)
    d.text((M, 912), "Re-run with the same danger lines we use today —",
           font=font(REG, 26), fill=MUTED)
    d.text((M, 948), "including one market that tripped a line and recovered.",
           font=font(REG, 26), fill=MUTED)
    return img


def card_contrarian(t):
    """The contrarian card is a CHART, and that is a deliberate exception.

    Every other card here refuses a chart: the per-metro series has holes,
    because a metro drops off the gathering list in months it does not qualify,
    and a line with gaps misrepresents a trend. The NATIONAL series has no such
    problem — 73 continuous points read through research.national_series() so
    it can never cross the 2020-06 source seam.

    It earns the exception because the story is a SHAPE, not a figure. "Fewer
    neighborhoods are showing warning signs than last month" is an argument
    about direction, and a single big number cannot make it: 62.2% on its own
    is indistinguishable from 62.2% on the way up. The line shows the rise, the
    turn, and the three months since — which is the whole claim, visible before
    a word is read.

    The falling segment is drawn in the verdict GREEN. A falling warning share
    is good news, and colouring it like the rest of the line would hide the one
    thing the card exists to say. Still no red anywhere.
    """
    from build_research import font, REG, BOLD, INK, MUTED, FAINT, NAVY, GREEN
    r = t.get("render") or {}
    series = [(m, float(w)) for m, w in (r.get("series") or []) if w is not None]
    img, d = _shell(r.get("period_pretty", ""), "The headlines, and the data", "")
    M = 84

    _track(d, "SHARE OF U.S. ZIP CODES SHOWING WARNING SIGNS",
           font(REG, 22), M, 312, MUTED, 2.2)

    if len(series) < 4:
        # No usable history: say the number plainly rather than draw a line
        # from three points and call it a trend.
        d.text((M - 10, 400), f"{r.get('wsi', 0):.1f}%", font=font(BOLD, 250), fill=NAVY)
        d.text((M, 700), "of the ZIP codes we track are showing", font=font(REG, 31), fill=INK)
        d.text((M, 740), "at least one warning sign.", font=font(REG, 31), fill=MUTED)
        return img

    # ——— the plot ———
    # The right margin is reserved for the end label — drawn over its own
    # marker in the first render, which made both unreadable.
    X0, X1, Y0, Y1 = M + 8, 1080 - M - 190, 400, 812
    lo = min(w for _, w in series) - 3
    hi = max(w for _, w in series) + 3
    px = lambda i: X0 + (X1 - X0) * i / (len(series) - 1)
    py = lambda w: Y1 - (Y1 - Y0) * (w - lo) / (hi - lo)

    # A faint baseline only — gridlines would turn a story into a spreadsheet.
    d.line([(X0, Y1 + 26), (1080 - M, Y1 + 26)], fill=RULE_TINT, width=2)

    # The peak is where the turn happened; naming it is what makes the last
    # three months read as a reversal rather than as noise.
    peak_i = max(range(len(series)), key=lambda i: series[i][1])
    pts = [(px(i), py(w)) for i, (_, w) in enumerate(series)]
    d.line(pts[:peak_i + 1], fill=(150, 160, 172), width=7, joint="curve")
    d.line(pts[peak_i:], fill=GREEN, width=9, joint="curve")

    for i in (peak_i, len(series) - 1):
        x, y = pts[i]
        c = GREEN if i == len(series) - 1 else (150, 160, 172)
        d.ellipse([x - 11, y - 11, x + 11, y + 11], fill=(250, 248, 244), outline=c, width=6)

    # End label: the current figure, set large, beside its own dot.
    cur = series[-1][1]
    lbl = f"{cur:.1f}%"
    d.text((pts[-1][0] + 30, pts[-1][1] - 44), lbl, font=font(BOLD, 70), fill=INK)
    # Peak label, small, above its dot.
    pk = f"{series[peak_i][1]:.1f}%"
    d.text((pts[peak_i][0] - d.textlength(pk, font=font(REG, 26)) / 2,
            pts[peak_i][1] - 62), pk, font=font(REG, 26), fill=MUTED)

    # x labels: first and last only. Twelve tick labels is furniture.
    d.text((X0, Y1 + 44), _pretty_month(series[0][0]), font=font(REG, 24), fill=FAINT)
    last = _pretty_month(series[-1][0])
    d.text((1080 - M - d.textlength(last, font=font(REG, 24)), Y1 + 44), last,
           font=font(REG, 24), fill=FAINT)

    # ——— the claim, in words, under the line ———
    d.line([(M, 928), (1080 - M, 928)], fill=RULE_TINT, width=2)
    # run_length comes from research.detect_records() — the same number the
    # caption and the release page use. Deriving it here again is how the card
    # came to claim a fifth consecutive fall against a truth of three.
    run = r.get("run_length") or 0
    falling = r.get("run_direction") == "down"
    d.text((M, 968),
           f"Down for the {_ordinal_word(run)} month in a row." if (falling and run >= 2)
           else ("Lower than last month." if falling else "Higher than last month."),
           font=font(BOLD, 40), fill=INK)
    d.text((M, 1036), "The headlines are telling a different story. We publish",
           font=font(REG, 27), fill=MUTED)
    d.text((M, 1072), "this measurement every month, whichever way it moves.",
           font=font(REG, 27), fill=MUTED)
    return img


_ordinal_word = lambda n: {2: "second", 3: "third", 4: "fourth", 5: "fifth",
                           6: "sixth", 7: "seventh", 8: "eighth", 9: "ninth",
                           10: "tenth", 11: "eleventh", 12: "twelfth"}.get(n, f"{n}th")


BUILDERS = {"post": card_metro, "contrarian": card_contrarian, "receipt_quote": card_receipt, "evergreen": card_case}


def write_redirects(period, web_root):
    """/go/{token}/ — the short link that still measures.

    A caption cannot carry a 90-character UTM URL and stay readable, and the
    obvious fix (show the bare domain, keep the tracked link in the admin Copy
    button) quietly breaks the performance loop: the operator pastes the
    caption, the posted link has no campaign token, and perf_checks measures
    nothing for the life of the post. So the short link is a REAL page that
    redirects to the tracked one — the same static-redirect trick /s/{zip}
    already uses on a host with no server.

    Scrapers read the meta refresh, humans get location.replace, and anyone
    with JS off gets a visible link. noindex because these are not content.
    """
    man = MANIFEST_DIR / f"pack-{period}.json"
    if not man.exists():
        return 0
    n = 0
    for task in json.loads(man.read_text()).get("tasks") or []:
        tok, dest = task.get("utm_campaign"), task.get("utm_url")
        if not tok or not dest:
            continue
        d = web_root / "go" / tok
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.html").write_text(
            "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            "<meta name=\"robots\" content=\"noindex,nofollow\">"
            f"<title>ShouldISellYet</title>"
            f"<script>location.replace({json.dumps(dest)});</script>"
            f"<meta http-equiv=\"refresh\" content=\"0;url={dest}\">"
            "<style>body{font-family:system-ui,-apple-system,sans-serif;"
            "background:#faf8f4;color:#5c6673;padding:40px 20px;text-align:center}"
            "a{color:#1f3a5f}</style></head><body>"
            f"<p>Taking you to the free ZIP checker… <a href=\"{dest}\">continue</a></p>"
            "</body></html>", encoding="utf-8")
        n += 1
    print(f"post-pack: {n} short link(s) written to {web_root / 'go'}")
    return n


def render(period, out_root):
    """Draw every card the manifest asks for. Returns (drawn, skipped)."""
    man = MANIFEST_DIR / f"pack-{period}.json"
    if not man.exists():
        print(f"post-pack: no manifest for {period} — nothing to render")
        return 0, 0
    tasks = json.loads(man.read_text()).get("tasks") or []
    outdir = out_root / period
    drawn = skipped = 0
    for t in tasks:
        tok, kind = t.get("utm_campaign"), t.get("type")
        path = t.get("asset_path") or ""
        if not tok or not path:
            continue
        # A record card reuses the research release's own WSI image rather than
        # drawing a second one — same number, same month, one source.
        if path.startswith("/research/"):
            src = ROOT / "web" / path.lstrip("/")
            if src.exists():
                outdir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, outdir / f"{tok}.png")
                drawn += 1
            else:
                print(f"post-pack: {tok} wants {path} — not built yet, skipped")
                skipped += 1
            continue
        # render["card"] names the builder when the TYPE is not enough: the
        # contrarian post is type "post" like every metro story but needs a
        # different layout entirely (national trend, not a single market).
        build = BUILDERS.get((t.get("render") or {}).get("card") or kind)
        if not build:
            continue
        # The builders now draw and return an image: the card is a LAYOUT, not
        # three strings poured into a shared frame, which is what cost the old
        # cards their hierarchy. Compliance is checked on the strings the
        # builder will draw, gathered from the same render payload.
        bad = compliant(" ".join(str(v) for v in (t.get("render") or {}).values()))
        if bad:
            print(f"post-pack: {tok} refused — copy tripped {sorted(set(bad))}")
            skipped += 1
            continue
        try:
            img = build(t)
        except Exception as exc:                       # Pillow missing, font missing
            print(f"post-pack: cannot render ({exc}) — cards skipped this run")
            return drawn, skipped + 1
        outdir.mkdir(parents=True, exist_ok=True)
        img.save(outdir / f"{tok}.png")
        drawn += 1
    print(f"post-pack: {drawn} card(s) rendered · {skipped} skipped · {outdir}")
    return drawn, skipped


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--render", action="store_true", help="draw the cards (the only mode)")
    ap.add_argument("--period", default="")
    ap.add_argument("--out", default=str(ROOT / "web" / "assets" / "mkt"))
    args = ap.parse_args(argv)

    period = args.period
    if not period:
        meta = ROOT / "web" / "data" / "meta.json"
        period = json.loads(meta.read_text()).get("period", "") if meta.exists() else ""
    if not period:
        print("post-pack: no data period — nothing to render")
        return 0
    render(period, Path(args.out))
    write_redirects(period, ROOT / "web")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
