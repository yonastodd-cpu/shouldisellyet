#!/usr/bin/env python3
"""Gate B — no prior-vendor value renders on a paid or authenticated surface.

This gate exists because the crawl gate structurally cannot cover these pages.
It reads rendered innerText from sampled public URLs; /my-report.html is
session-gated and never crawled, and the figures in question enter the DOM only
when a renderer runs. Both blocking defects of 2026-08-25 lived exactly there:
a national percentile interpolated against the prior vendor's sold-price
deciles, served to purchasers while the free homepage refused the identical
code, and a velocity panel reading a table whose every row carries the prior
vendor's tag.

WHAT IT CHECKS. Rendered text with comments, scripts and stylesheets removed —
`--fs-verdict` is a CSS custom property and `.verdict-tag` a class name, and
counting those as findings is how a gate trains people to ignore it. Source is
checked separately, for the client renderers, where the question is whether the
refusal is unconditional rather than flag-gated.

Usage: python3 scripts/gate-paid-surfaces.py [BASE_URL]
Exit 0 clean, 1 on any finding.
"""
import os
import re
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5177").rstrip("/")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAID = ["/report.html", "/my-report.html"]

FORBIDDEN = [
    (re.compile(r"Redfin", re.I),                    "prior vendor named"),
    (re.compile(r"spy_deciles"),                     "prior-vendor decile array"),
    (re.compile(r"TIME TO SELL"),                    "retired dial label"),
    (re.compile(r"public (?:market|housing-market) data", re.I),
                                                     "provenance misstated"),
    (re.compile(r"\b15,471\b|\b7,110\b|\b9,485\b"),  "prior-vendor national counts"),
]
# Natural English that is not the dial label.
ALLOWED = re.compile(r"good time to sell", re.I)


def rendered(url):
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=45) as r:
        h = r.read().decode("utf-8", "replace")
    for pat in (r"<!--.*?-->", r"<script[^>]*>.*?</script>", r"<style[^>]*>.*?</style>"):
        h = re.sub(pat, "", h, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h))


def main():
    findings = []
    checked = 0
    for path in PAID:
        try:
            text = rendered(f"{BASE}{path}")
        except (urllib.error.URLError, OSError) as e:
            print(f"  ERROR {path}: {e}")
            findings.append(f"{path}: unreachable")
            continue
        checked += 1
        hits = []
        for rx, why in FORBIDDEN:
            for m in rx.finditer(text):
                window = text[max(0, m.start() - 40):m.start() + 40]
                if ALLOWED.search(window):
                    continue
                hits.append(f"{why} ({m.group(0)!r})")
                break
        print(f"  {'PASS' if not hits else 'FAIL'}  {path}" + (f"  {hits}" if hits else ""))
        findings += [f"{path}: {h}" for h in hits]

    # The client renderers: the refusal must be unconditional, not flag-gated.
    mr = os.path.join(ROOT, "web", "market-render.js")
    if os.path.exists(mr):
        src = open(mr, encoding="utf-8", errors="replace").read()
        ok = "false && nat.spy_deciles" in src
        print(f"  {'PASS' if ok else 'FAIL'}  market-render.js percentile refused unconditionally")
        if not ok:
            findings.append("market-render.js: percentile is gated rather than refused — "
                            "FIGURES_OFF is the CURRENT vendor's switch and does not "
                            "govern prior-vendor deciles")

    if checked == 0:
        print("\ngate B: FAIL — no paid surface was reachable; this proves nothing")
        return 1
    if findings:
        print(f"\ngate B: FAIL — {len(findings)} finding(s)")
        return 1
    print(f"\ngate B: PASS — {checked} paid surface(s), no prior-vendor value rendered")
    return 0


if __name__ == "__main__":
    sys.exit(main())
