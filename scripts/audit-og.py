"""OG / social-preview audit — basis-correctness, not figure-absence.

HISTORY OF THE RULE. The original audit flagged any rating or market figure in
an OG/twitter field as a "leak": it was written during the data pause, when the
site published no readings and a figure in a share card meant withdrawn data
was escaping through the surface nobody rechecks. The relaunch inverted that —
share cards carrying current readings are now intentional product (80 of 95
priority URLs "leaked" by the old rule on 2026-08-27, all of them correct
cards). So the question changed from "is there a figure?" to "is the figure on
the right basis?":

  - the prior vendor must not be named or credited;
  - v1-only vocabulary must not appear — months of supply, homes sold,
    price-cut share, the four-dial count, "days to sell" — because the current
    active-listing basis cannot produce those measurements;
  - any dated claim ("data through May 2026", "August 2026") must be current:
    a month more than STALE_MONTHS calendar months old is a stale card;
  - and every audited page must HAVE OG tags at all — /methodology.html and
    /pricing/ shipped with none, so scrapers guessed (found 2026-08-27).

Usage: python3 scripts/audit-og.py scripts/og-priority-urls.txt
Exit 0 clean, 1 on any finding.
"""
import re, sys, datetime, urllib.request, concurrent.futures as cf
sys.path.insert(0, 'pipeline')
from fetch_data import _ssl_context
CTX = _ssl_context()
SITE = "https://shouldisellyet.com"

META = re.compile(r'<meta[^>]+(?:property|name)="((?:og|twitter):[^"]+)"[^>]*content="([^"]*)"', re.I)
TITLE = re.compile(r'<title>(.*?)</title>', re.S | re.I)

# Wrong-basis vocabulary: the prior vendor by name, and measurements only the
# retired sold-home feed could produce. "good time to sell" is natural English,
# not the retired dial label — same carve-out gate B makes.
WRONG_BASIS = [
    (re.compile(r'Redfin', re.I), "prior vendor named"),
    (re.compile(r'months? of supply', re.I), "v1 signal (supply)"),
    (re.compile(r'\d[\d,]*\s+homes? sold', re.I), "v1 figure (sold count)"),
    (re.compile(r'price[- ]cuts?', re.I), "v1 signal (price cuts)"),
    (re.compile(r'four (?:market )?dials', re.I), "v1 dial count (current basis has three)"),
    (re.compile(r'days to sell|TIME TO SELL'), "retired dial label"),
]

# A dated claim older than this many calendar months is a stale card.
STALE_MONTHS = 2
MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}
DATED = re.compile(r'\b(' + '|'.join(MONTHS) + r')\s+(20\d\d)\b|\b(20\d\d)-(\d\d)\b', re.I)

def month_index(m):
    if m.group(1):
        return int(m.group(2)) * 12 + MONTHS[m.group(1).lower()]
    return int(m.group(3)) * 12 + int(m.group(4))

TODAY = datetime.date.today()
CUTOFF = TODAY.year * 12 + TODAY.month - STALE_MONTHS

def get(url):
    try:
        r = urllib.request.Request(url, headers={"User-Agent": "sisy-og-audit"})
        return urllib.request.urlopen(r, timeout=25, context=CTX).read().decode("utf-8", "replace")
    except Exception as e:
        return f"__ERR__{e}"

def audit(url):
    h = get(url)
    if h.startswith("__ERR__"):
        return {"url": url, "error": h[7:][:60]}
    fields = {}
    m = TITLE.search(h)
    if m: fields["<title>"] = re.sub(r"\s+", " ", m.group(1)).strip()
    d = re.search(r'<meta[^>]+name="description"[^>]*content="([^"]*)"', h, re.I)
    if d: fields["description"] = d.group(1)
    og = {}
    for k, v in META.findall(h):
        fields[k] = v
        og[k] = v
    findings = {}
    if not any(k.lower().startswith("og:") for k in og):
        findings["(page)"] = {"value": "", "why": ["no OG tags at all — scrapers will guess"]}
    for k, v in fields.items():
        bad = []
        for rx, why in WRONG_BASIS:
            mm = rx.search(v)
            if mm and "good time to sell" not in v.lower():
                bad.append(f"{why}: {mm.group(0)!r}")
        for mm in DATED.finditer(v):
            if month_index(mm) < CUTOFF:
                bad.append(f"stale date: {mm.group(0)!r} (> {STALE_MONTHS} months old)")
        if bad: findings[k] = {"value": v[:90], "why": bad}
    return {"url": url, "leaks": findings, "n_fields": len(fields)}

urls = [l.strip() for l in open(sys.argv[1]) if l.strip() and not l.startswith("#")]
with cf.ThreadPoolExecutor(12) as ex:
    res = list(ex.map(audit, urls))
bad = [r for r in res if r.get("leaks")]
err = [r for r in res if r.get("error")]
print(f"audited {len(res)} URLs · clean {len(res)-len(bad)-len(err)} · WRONG-BASIS {len(bad)} · errors {len(err)}")
for r in bad:
    print(f"\n  {r['url']}")
    for k, v in r["leaks"].items():
        print(f"    {k}: {v['why']} → {v['value']!r}")
for r in err[:3]:
    print(f"  ERR {r['url']}: {r['error']}")
sys.exit(1 if bad else 0)
