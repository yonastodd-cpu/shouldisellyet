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


def as_js():
    """Emit the map as a browser global so hand-written pages read the same
    source as the generators."""
    payload = json.dumps(COPY, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return ("// GENERATED from pipeline/data/verdict_copy.json by build_pages.py.\n"
            "// Do not edit — change the JSON and rebuild.\n"
            f"window.VERDICT_COPY = {payload};\n")
