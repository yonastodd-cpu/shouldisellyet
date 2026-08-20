import re, sys, json, ssl, urllib.request, concurrent.futures as cf
sys.path.insert(0, 'pipeline')
from fetch_data import _ssl_context
CTX = _ssl_context()
SITE = "https://shouldisellyet.com"
RATING = re.compile(r'\b(HOLD|WATCH|ACT)\b')
# a number that looks like a market figure: %, "N days", "N mo", $N, N homes
FIGURE = re.compile(r'[-+]?\d[\d,]*\.?\d*\s*(%|days?|mo\b|months?\b|homes\b)|\$\s?\d')
META = re.compile(r'<meta[^>]+(?:property|name)="((?:og|twitter):[^"]+)"[^>]*content="([^"]*)"', re.I)
TITLE = re.compile(r'<title>(.*?)</title>', re.S | re.I)

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
    for k, v in META.findall(h):
        fields[k] = v
    leaks = {}
    for k, v in fields.items():
        bad = []
        if RATING.search(v): bad.append("rating:" + RATING.search(v).group(0))
        if FIGURE.search(v): bad.append("figure:" + FIGURE.search(v).group(0).strip())
        if bad: leaks[k] = {"value": v[:90], "why": bad}
    return {"url": url, "leaks": leaks, "n_fields": len(fields)}

urls = [l.strip() for l in open(sys.argv[1]) if l.strip()]
with cf.ThreadPoolExecutor(12) as ex:
    res = list(ex.map(audit, urls))
bad = [r for r in res if r.get("leaks")]
err = [r for r in res if r.get("error")]
print(f"audited {len(res)} URLs · clean {len(res)-len(bad)-len(err)} · LEAKING {len(bad)} · errors {len(err)}")
for r in bad:
    print(f"\n  {r['url']}")
    for k, v in r["leaks"].items():
        print(f"    {k}: {v['why']} → {v['value']!r}")
for r in err[:3]:
    print(f"  ERR {r['url']}: {r['error']}")
