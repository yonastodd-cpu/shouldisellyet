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


# ————— card renderers —————
# Each takes explicit public scalars and returns a PIL image. TEMPLATES holds
# the sentences; note that not one of them contains a numeral — every figure
# arrives from the manifest, so a stale hardcoded number cannot survive here
# (the failure mode test_no_handwritten_claims.py exists to catch).
TEMPLATES = {
    "metro_head": "{name}",
    "metro_sub": "{share_det}% of its {zips} scored ZIP codes are deteriorating",
    "metro_body": "{hold_share}% still rate HOLD.\nMedian nearest signal:\n{mtl}.",
    "receipt_head": "We flagged it first",
    "receipt_sub": "{metro} — {lead} days before {outlet}",
    "receipt_body": "Our index flagged {metro}\non {flag_date}.\n{outlet} reported it\non {pub_date}.",
    "case_head": "{name}",
    "case_sub": "flagged {lead} months before prices fell",
    "case_body": "First signal {signal}.\nPeak to trough {ptt}.\nComputed from the same data\nand thresholds we use today.",
}

FOOT = "ShouldISellYet · shouldisellyet.com"


def _frame(head, sub, body_lines, foot=FOOT):
    """The shared card. Imported lazily so --render can no-op without Pillow."""
    from build_research import _social_frame, font, REG, INK, MUTED
    img, d = _social_frame([head, sub], "", foot=foot)
    y = 300
    for ln in body_lines:
        d.text((64, y), ln, font=font(REG, 34), fill=INK if ln else MUTED)
        y += 52
    return img


def card_metro(t):
    r = t.get("render") or {}
    head = TEMPLATES["metro_head"].format(name=r.get("name", ""))
    sub = TEMPLATES["metro_sub"].format(share_det=round(r.get("share_det") or 0),
                                        zips=r.get("zips") or 0)
    from build_research import mtl_prose
    body = TEMPLATES["metro_body"].format(hold_share=round(r.get("hold_share") or 0),
                                          mtl=mtl_prose(r.get("median_mtl")))
    return head, sub, body


def card_receipt(t):
    r = t.get("render") or {}
    head = TEMPLATES["receipt_head"]
    sub = TEMPLATES["receipt_sub"].format(metro=r.get("metro", ""),
                                          lead=r.get("lead_days") or 0,
                                          outlet=r.get("outlet", ""))
    body = TEMPLATES["receipt_body"].format(metro=r.get("metro", ""),
                                            flag_date=_pretty_day(r.get("flag_date")),
                                            outlet=r.get("outlet", ""),
                                            pub_date=_pretty_day(r.get("published_on")))
    return head, sub, body


def _pct(v):
    """A stored ratio as the percentage a reader expects. -0.1775 is a number
    only a database loves; a card that prints it has published nothing."""
    return "—" if v is None else f"{v * 100:+.1f}%"


def _pretty_month(s):
    """'2022-08' → 'August 2022'. Cards are read by people, not by the ISO
    committee; the same rule the release pages already follow."""
    try:
        y, m = str(s).split("-")[:2]
        return f"{MONTH_NAMES[int(m) - 1]} {y}"
    except Exception:
        return str(s or "")


MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def _pretty_day(s):
    """'2026-07-31' → 'July 31, 2026'. Same reason as _pretty_month."""
    try:
        y, m, d = str(s).split("-")[:3]
        return f"{MONTH_NAMES[int(m) - 1]} {int(d)}, {y}"
    except Exception:
        return str(s or "")


def card_case(t):
    r = t.get("render") or {}
    head = TEMPLATES["case_head"].format(name=r.get("name", ""))
    sub = TEMPLATES["case_sub"].format(lead=r.get("lead_months") or 0)
    body = TEMPLATES["case_body"].format(signal=_pretty_month(r.get("first_signal")),
                                         ptt=_pct(r.get("peak_to_trough")))
    return head, sub, body


BUILDERS = {"post": card_metro, "receipt_quote": card_receipt, "evergreen": card_case}


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
        build = BUILDERS.get(kind)
        if not build:
            continue
        head, sub, body = build(t)
        bad = compliant(" ".join([head, sub, body]))
        if bad:
            print(f"post-pack: {tok} refused — copy tripped {sorted(set(bad))}")
            skipped += 1
            continue
        try:
            img = _frame(head, sub, body.split("\n"))
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
