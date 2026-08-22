#!/usr/bin/env python3
"""Does this archived copy still show a withdrawn figure?

The survey's third column, and the one a lawyer actually reads. "There is a
capture from 18 August" is weak; "there is a capture from 18 August whose
title reads 'WATCH' and whose body carries a days-on-market value" is the
finding.

PORTED, NOT REINVENTED. The rating and figure patterns and the disclosure
subtraction come from scripts/smoke-browser.mjs and scripts/audit-og.py, which
are the two detectors already trusted against production. Keeping a third,
subtly different definition of "a figure" would mean the survey and the gates
could disagree about the same bytes.

THE DISTINCTION THAT BIT THREE TESTS. Naming the rating vocabulary is not a
leak. /zip/ and /press.html describe the product — "HOLD / WATCH / ACT
verdicts for 22,874 U.S. ZIP codes" — and were correct as written on the day
of the 19 August audit. Publishing a specific ZIP's rating is what stopped.
So this returns a three-way verdict, never a boolean: a survey row that flags
the press page as leaking because it uses the word WATCH is a row counsel has
to be talked out of.

Likewise the danger lines. Every page states the thresholds the engine scores
against — "the year-over-year price trend (−2%)". Those are ours, published,
identical on every page. They are subtracted before the figure scan; whatever
still looks like a figure afterwards is the ZIP's own measured value.
"""

import re

RATING = re.compile(r"\b(HOLD|WATCH|ACT)\b")

# A market figure as a reader would see one: a percentage, a day count, a
# months-of-supply value, a price. Same shape as smoke-browser.mjs FIGURE.
FIGURE = re.compile(
    r"[-−+]?\d[\d,]*\.?\d*\s*(%|days?\b|mo\b|months? of supply)"
    r"|\$\s?\d[\d,]{2,}")

# The published danger lines, subtracted before the scan. Kept byte-identical
# to smoke-browser.mjs DISCLOSED, including both hyphen and U+2212 minus,
# because the pages render one and the source carries the other.
DISCLOSED = ("−20%", "−15%", "-15%", "-20%", "+30%", "+10%", "-2%",
             "30%", "20%", "+5%", "10%", "-5%", "−2%", "−5%",
             "15%", "5%", "2%")

# Pages whose whole subject is the rating vocabulary. A rating word here is
# product description; a rating word anywhere else is a reading.
VOCABULARY_PAGES = ("/zip/", "/press.html", "/", "/llms.txt")

TAG = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
ANGLE = re.compile(r"<[^>]+>")
META = re.compile(
    r'<meta[^>]+(?:property|name)="((?:og|twitter):[^"]+|description)"'
    r'[^>]*content="([^"]*)"', re.I)
TITLE = re.compile(r"<title>(.*?)</title>", re.S | re.I)

# The verdicts. Ordered worst-first; a survey sorts on this.
FIGURES_VISIBLE = "figures_visible"      # a specific market's number is on the page
RATING_VISIBLE = "rating_visible"        # a rating word where it can only be a reading
VOCABULARY_ONLY = "vocabulary_only"      # names HOLD/WATCH/ACT, publishes no reading
CLEAN = "clean"                          # nothing withdrawn found
NOT_FETCHED = "not_fetched"              # no body was retrieved — see the row's note


def strip_disclosed(text):
    for d in DISCLOSED:
        text = text.replace(d, "")
    return text


def visible_text(html):
    """Body text plus the metadata fields, which is what a preview shows.

    Metadata is included on purpose. The memo's first round was share
    metadata: a page whose body had been blanked while its <title> and og:*
    still carried the verdict looked fixed to anyone reading the page and was
    not fixed for anyone sharing it.
    """
    parts = []
    m = TITLE.search(html)
    if m:
        parts.append(m.group(1))
    parts += [v for _, v in META.findall(html)]
    parts.append(ANGLE.sub(" ", TAG.sub(" ", html)))
    return re.sub(r"\s+", " ", " ".join(parts))


def classify(html, url=""):
    """(verdict, evidence). Evidence is the literal match, for the CSV.

    Non-HTML bodies — the research CSV is the case that matters — fall through
    the same path: the tag strippers are no-ops on a CSV and the figure
    pattern finds its rows. A withdrawn ratings file with 2,403 rows in it
    reads as figures_visible, which is correct.
    """
    if html is None:
        return NOT_FETCHED, ""
    text = visible_text(html)
    fig = FIGURE.search(strip_disclosed(text))
    if fig:
        return FIGURES_VISIBLE, fig.group(0).strip()[:60]
    rat = RATING.search(text)
    if rat:
        path = url.split("://", 1)[-1].split("/", 1)[-1] if "://" in url else url
        path = "/" + path.lstrip("/")
        if path in VOCABULARY_PAGES:
            return VOCABULARY_ONLY, rat.group(0)
        return RATING_VISIBLE, rat.group(0)
    return CLEAN, ""
