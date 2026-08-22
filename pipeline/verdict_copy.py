"""
Canonical verdict copy — the one place the word/translation/emoji live.

The card, the OG title, the share text, the ZIP pages and the homepage all
read from pipeline/data/verdict_copy.json (the homepage via the generated
web/verdict-copy.js). Nothing may hard-code a translation string: the whole
point is that a recipient sees the same plain-English meaning wherever the
verdict appears.
"""

import json
from pathlib import Path

_PATH = Path(__file__).parent / "data" / "verdict_copy.json"
COPY = {k: v for k, v in json.loads(_PATH.read_text(encoding="utf-8")).items()
        if not k.startswith("_")}
STATES = ("green", "yellow", "red", "strong")


def get(level):
    return COPY.get(level, COPY["green"])


# ————— methodology sentence —————
# Lifted out of verdict_v2.py on 2026-08-22. It is reader-facing copy, and it
# was carrying two errors that could not be fixed where it lived because that
# module holds scoring logic and is edited under a different bar:
#   "Three public signals"        -> the feed is licensed, not public.
#   "how long homes take to sell" -> the number is time ON MARKET across unsold
#                                    listings, which is not time-to-contract and
#                                    runs longer (see methodology section 2).
# The numbers still come from verdict_v2.SPEC via disclosure(); only the words
# live here. Imported lazily so this module stays importable on its own.

SIGNAL_NAMES = ("the year-over-year price trend",
                "how long listed homes have been on the market",
                "how the pool of homes for sale is changing")


def methodology_sentence(spec=None):
    """One sentence naming every signal and its line, built from the spec."""
    from verdict_v2 import SPEC, disclosure
    d = disclosure(spec if spec is not None else SPEC)
    return (f"Three signals drawn from licensed market statistics, each with a "
            f"danger line recalibrated for active-listing data: the "
            f"year-over-year price trend ({d['price_slow']}), how long listed "
            f"homes have been on the market ({d['dom_stretch']} year over "
            f"year), and the number of homes for sale ({d['inventory_surge']} "
            f"year over year). A ZIP crossing enough of them reads WATCH or "
            f"ACT; a clean ZIP reads HOLD.")


def as_js():
    """Emit the map as a browser global so hand-written pages read the same
    source as the generators."""
    payload = json.dumps(COPY, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return ("// GENERATED from pipeline/data/verdict_copy.json by build_pages.py.\n"
            "// Do not edit — change the JSON and rebuild.\n"
            f"window.VERDICT_COPY = {payload};\n")
