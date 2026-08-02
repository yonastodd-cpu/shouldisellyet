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

VERDICT = {
    "green":  {"word": "HOLD",  "rgb": (30, 122, 66),  "band": (233, 244, 238), "edge": (188, 220, 201)},
    "yellow": {"word": "WATCH", "rgb": (150, 101, 12), "band": (250, 241, 221), "edge": (232, 213, 168)},
    "red":    {"word": "ACT",   "rgb": (192, 47, 47),  "band": (251, 233, 233), "edge": (236, 195, 195)},
    "strong": {"word": "ACT",   "rgb": (31, 58, 95),   "band": (232, 238, 247), "edge": (195, 210, 232)},
}

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

    zip_code/city/state — public location
    level               — verdict key (green|yellow|red|strong)
    stat_line           — ONE pre-formatted public market stat, e.g.
                          "Homes here sell in 31 days"
    data_month          — e.g. "May 2026"
    """
    from PIL import Image, ImageDraw

    v = VERDICT.get(level, VERDICT["green"])
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # Left accent bar in the verdict colour — carries the state read even when
    # the card is scaled to a thumbnail and the words go sub-legible.
    d.rectangle([0, 0, 18, H], fill=v["rgb"])

    # Soft band behind the verdict word, echoing the site's result header.
    d.rectangle([18, 96, W, 350], fill=v["band"])
    d.line([(18, 96), (W, 96)], fill=v["edge"], width=2)
    d.line([(18, 350), (W, 350)], fill=v["edge"], width=2)

    pad = 72

    # ——— top line: brand + ZIP · City, ST ———
    f_brand = _font("IBMPlexMono-Bold.ttf", 26)
    d.text((pad, 44), "SHOULDISELLYET.COM", font=f_brand, fill=NAVY)

    # ——— verdict word: the dominant element ———
    f_v = _fit(d, v["word"], "IBMPlexMono-Bold.ttf", 168, W - pad * 2 - 300)
    d.text((pad, 150), v["word"], font=f_v, fill=v["rgb"])

    # ZIP + city sit to the right of the verdict word, baseline-aligned low
    loc1 = f"{zip_code}"
    place = f"{city}, {state}" if city else state
    f_zip = _font("IBMPlexMono-Bold.ttf", 46)
    f_city = _fit(d, place, "IBMPlexMono-Regular.ttf", 34, W - pad * 2 - 460, 20)
    vx = pad + d.textlength(v["word"], font=f_v) + 44
    d.text((vx, 176), loc1, font=f_zip, fill=INK)
    d.text((vx, 236), place, font=f_city, fill=MUTED)

    # ——— the one stat ———
    f_stat = _fit(d, stat_line, "IBMPlexMono-Regular.ttf", 40, W - pad * 2, 24)
    d.text((pad, 408), stat_line, font=f_stat, fill=INK)

    # ——— footer: freshness + call to action ———
    d.line([(pad, 520), (W - pad, 520)], fill=HAIRLINE, width=2)
    f_foot = _font("IBMPlexMono-Regular.ttf", 25)
    d.text((pad, 548), f"Data through {data_month}", font=f_foot, fill=FAINT)
    cta = "Check any ZIP free →"
    d.text((W - pad - d.textlength(cta, font=f_foot), 548), cta, font=f_foot, fill=NAVY)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    # Palette-quantised: these cards are flat colour + text, so 8-bit palette
    # is visually lossless here and roughly a third the size of RGB PNG.
    img.convert("P", palette=Image.Palette.ADAPTIVE, colors=64).save(
        out_path, format="PNG", optimize=True)
    return Path(out_path).stat().st_size
