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

    # ————— Notice pages render NO figures —————
    # The on-demand path (schema-v41) made notice ZIPs purchasable, and the
    # invariant that keeps that honest is structural: a page still showing
    # the rebuilding notice must carry no market figure, because figures
    # render only on pages whose ZIP has validated stored data behind it —
    # a page has its reading, or it has its notice, never both. Checked on
    # the BUILT pages, all of them: the notice title in the body must never
    # co-occur with the metric-row markup or a rendered dollar amount.
    # (Thousands-grouped amounts only — the $5.99 price CTA is not a market
    # figure.) The marker is data_pause.NOTICE_TITLE, imported so a copy
    # edit cannot silently reduce this check to scanning nothing.
    # Skipped when web/zip has not been built; in CI it always has.
    sys.path.insert(0, os.path.join(ROOT, "pipeline"))
    from data_pause import NOTICE_TITLE
    zroot = os.path.join(ROOT, "web", "zip")
    if os.path.isdir(zroot):
        money = re.compile(r"\$\s?\d{1,3},\d{3}")
        scanned = bad = 0
        for name in sorted(os.listdir(zroot)):
            page = os.path.join(zroot, name, "index.html")
            if not os.path.isfile(page):
                continue
            html = open(page, encoding="utf-8", errors="replace").read()
            if NOTICE_TITLE not in html:
                continue
            scanned += 1
            if 'class="metric"' in html:
                bad += 1
                findings.append(f"/zip/{name}/: notice page carries metric markup")
            else:
                text = re.sub(r"\s+", " ", re.sub(
                    r"<[^>]+>", " ", re.sub(
                        r"<!--.*?-->|<script[^>]*>.*?</script>|<style[^>]*>.*?</style>",
                        "", html, flags=re.S)))
                if money.search(text):
                    bad += 1
                    findings.append(f"/zip/{name}/: notice page renders a dollar figure")
        print(f"  {'PASS' if not bad else 'FAIL'}  notice pages figure-free "
              f"({scanned:,} scanned)")
    else:
        print("  SKIP  web/zip not built — notice-page check runs post-build in CI")

    # ————— No waitlist copy on a paid surface (2026-08-28) —————
    # A paying customer whose ZIP lacked a reading was told to "join the
    # waitlist" — free-path copy served to someone who had already paid. The
    # honest paid answers are the pull-in-progress note and the partial
    # report; the waitlist is for people who haven't paid. Checked on
    # COMMENT-STRIPPED SOURCE, not rendered text: the copy lives in script
    # string literals the rendered-text scan structurally cannot see (that is
    # how it shipped). Comments may still say the word — they explain the
    # rule, and a gate that fired on its own rulebook would be deleted rather
    # than obeyed (test_prior_vendor_serving_surfaces tells that story).
    for name in ("report.html", "my-report.html"):
        p = os.path.join(ROOT, "web", name)
        if not os.path.isfile(p):
            continue
        src = open(p, encoding="utf-8", errors="replace").read()
        src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
        src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
        src = re.sub(r"//[^\n]*", " ", src)
        ok = not re.search(r"waitlist", src, re.I)
        print(f"  {'PASS' if ok else 'FAIL'}  /{name} carries no waitlist copy")
        if not ok:
            findings.append(f"/{name}: waitlist copy on a paid surface")

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
