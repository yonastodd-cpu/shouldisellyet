"""
ShouldISellYet — Open Graph share-card renderer.

Draws the 1200x630 card that appears when someone shares a ZIP verdict.

PRIVACY (governs this whole module): a card may only ever show ZIP-level
PUBLIC data — verdict, ZIP, city/state, and a market stat drawn from the same
public feed the page shows. It must NEVER receive or render a personal input
(home value, mortgage balance, equity, walk-away, rate, PITI, purchase price).
render_card()'s signature deliberately accepts nothing that could carry one:
it takes a ZIP, a place, a verdict level and a pre-formatted public stat
string. Keep it that way — if a future caller needs more, add another public
field explicitly rather than passing a dict through.

Rendered with Pillow and a bundled OFL font so mac and ubuntu CI produce
identical output; no system-font dependency, no network.
"""

from pathlib import Path

FONTS = Path(__file__).parent / "fonts"
W, H = 1200, 630

# Site palette. Verdict colours are the *ink* variants — the vivid dot colours
# don't hold contrast as large text on a light card.
BG        = (250, 248, 244)
INK       = (28, 36, 48)
MUTED     = (92, 102, 115)
FAINT     = (138, 133, 120)
HAIRLINE  = (231, 226, 216)
NAVY      = (31, 58, 95)

# Verdict word, translation and colours come from the shared copy map — the
# card must never carry its own wording, or the card and the share text drift
# apart and the recipient sees two different meanings for one verdict.
import sys as _sys
_sys.path.insert(0, str(Path(__file__).parent))
from verdict_copy import get as _copy


def _hex(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))

_cache = {}


def _font(name, size):
    from PIL import ImageFont
    key = (name, size)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(str(FONTS / name), size)
    return _cache[key]


def _fit(draw, text, name, start, max_w, min_size=28):
    """Largest size at which `text` fits `max_w`. The verdict word and city
    names vary a lot in length; nothing may overflow the card."""
    size = start
    while size > min_size:
        f = _font(name, size)
        if draw.textlength(text, font=f) <= max_w:
            return f
        size -= 2
    return _font(name, min_size)


def render_card(zip_code, city, state, level, stat_line, data_month, out_path):
    """Write the 1200x630 PNG.

    Layout is built for a COLD recipient — someone who has never heard of the
    site and sees this in a chat thread. Top to bottom it answers, in order:
    what question is this, about where, what's the answer in plain English,
    what's the evidence, and what is this site.

    zip_code/city/state — public location
    level               — verdict key (green|yellow|red|strong)
    stat_line           — ONE pre-formatted public market stat
    data_month          — e.g. "May 2026"
    """
    from PIL import Image, ImageDraw

    c = _copy(level)
    ink = _hex(c["ink"])
    band, edge = _hex(c["band"]), _hex(c["edge"])
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    pad = 72

    # Left accent bar: carries the state read at thumbnail size, after the
    # words themselves have gone sub-legible.
    d.rectangle([0, 0, 16, H], fill=ink)

    # ——— 1. the question, so the verdict lands as an answer ———
    f_eyebrow = _font("IBMPlexMono-Bold.ttf", 27)
    d.text((pad, 52), "IS IT A GOOD TIME TO SELL A HOME IN…", font=f_eyebrow, fill=MUTED)

    # ——— 2. the place — the subject of the sentence ———
    place = f"{city}, {state}" if city else (state or "")
    f_place = _fit(d, place, "IBMPlexMono-Bold.ttf", 64, W - pad * 2 - 200, 34)
    d.text((pad, 96), place, font=f_place, fill=INK)
    f_zip = _font("IBMPlexMono-Regular.ttf", 34)
    if zip_code:
        d.text((pad + d.textlength(place, font=f_place) + 22,
                96 + f_place.size - 34), zip_code, font=f_zip, fill=FAINT)

    # ——— 3. verdict + translation, one visual unit ———
    # They share a band so the word can never be cropped or skimmed away from
    # its meaning — the whole point of the redesign.
    top, bot = 186, 402   # tall enough that the translation sits fully inside
    d.rectangle([16, top, W, bot], fill=band)
    d.line([(16, top), (W, top)], fill=edge, width=2)
    d.line([(16, bot), (W, bot)], fill=edge, width=2)

    word = c["word"]
    f_v = _fit(d, word, "IBMPlexMono-Bold.ttf", 116, W - pad * 2, 64)
    d.text((pad, top + 26), word, font=f_v, fill=ink)

    trans = c["translation"]
    f_t = _fit(d, trans, "IBMPlexMono-Regular.ttf", 38, W - pad * 2, 22)
    d.text((pad, top + 26 + f_v.size + 14), trans, font=f_t, fill=INK)

    # ——— 4. the evidence ———
    f_stat = _fit(d, stat_line, "IBMPlexMono-Regular.ttf", 36, W - pad * 2, 22)
    d.text((pad, 438), stat_line, font=f_stat, fill=MUTED)

    # ——— 5. what this site is + freshness ———
    d.line([(pad, 512), (W - pad, 512)], fill=HAIRLINE, width=2)
    f_foot = _font("IBMPlexMono-Bold.ttf", 26)
    f_foot_r = _font("IBMPlexMono-Regular.ttf", 24)
    explain = "A free monthly market checkup for any ZIP"
    d.text((pad, 542), explain, font=f_foot, fill=NAVY)
    d.text((pad, 578), "shouldisellyet.com", font=f_foot_r, fill=MUTED)
    if data_month and data_month.strip():
        t = f"Data through {data_month}"
        d.text((W - pad - d.textlength(t, font=f_foot_r), 578), t, font=f_foot_r, fill=FAINT)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.convert("P", palette=Image.Palette.ADAPTIVE, colors=32).save(
        out_path, format="PNG", optimize=True)
    return Path(out_path).stat().st_size
