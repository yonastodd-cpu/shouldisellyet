"""No artifact may distribute the vendor's underlying figures.

THE DISTINCTION THIS GUARDS. The vendor's licence covers displaying their
statistics; it does not clearly cover redistributing them as a dataset. Those
are the same numbers served two different ways, so the guard has to be about
the SERVING MODEL, not about whether a figure exists.

What we were doing until 2026-08-20: web/data/z/{zip}.json, 5,000 files named
by ZIP code, each carrying seven current metrics and a twelve-month series of
asking prices and days-on-market — roughly 120,000 raw monthly vendor values,
unauthenticated, complete, and collectable by iterating five digits. Two of the
shipped fields (price-per-sqft and new-listings year-over-year) and the entire
history rendered on no page at all: that file was their only exit.

And a denser path that did not look like a data file: each of the 608 metro
pages carried a per-ZIP table with a price-vs-last-year column. One fetch of
/metro/new-york-ny/ returned 211 ZIPs' figures, and 4,699 distinct ZIPs — 94%
of everything released — were harvestable in 608 requests.

Both are closed. Figures now reach a reader one page at a time: rendered into
that page's own HTML at build time, or fetched per-ZIP from the endpoint.

Run: python3 -m pytest pipeline/test_serving_model.py -q
"""

import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"

# Everything a public per-ZIP record may carry: our reading, its basis, the
# month it is as of, and the state. Every one of these is our own output.
PUBLIC_KEYS = {"st", "l", "b", "p"}

# Keys that carry the vendor's measurements. None may ship.
FIGURE_KEYS = {"m", "h", "s", "r"}


def _records():
    d = WEB / "data" / "z"
    if not d.is_dir():
        pytest.skip("records not provisioned in this checkout")
    return sorted(d.glob("*.json"))


def test_no_public_record_carries_a_vendor_figure():
    offenders = []
    for f in _records():
        keys = set(json.loads(f.read_text()))
        if keys - PUBLIC_KEYS:
            offenders.append((f.name, sorted(keys - PUBLIC_KEYS)))
    assert not offenders, (
        f"{len(offenders)} public record(s) carry more than our own reading: "
        f"{offenders[:3]}. Anything in {sorted(FIGURE_KEYS)} is the vendor's.")


def test_no_served_file_carries_a_price_series():
    """A twelve-month series is the clearest single marker of a dataset: no
    page displays twelve numbers, so its presence in a file means the file is
    not there to render a page."""
    offenders = []
    for f in WEB.rglob("*.json"):
        txt = f.read_text(errors="replace")
        if re.search(r'"p"\s*:\s*\[\s*\d{4,}', txt) or "medianListPrice" in txt:
            offenders.append(str(f.relative_to(WEB)))
    assert not offenders, f"served files carry a price series: {offenders[:5]}"


def test_no_page_serves_more_than_one_zip_worth_of_figures():
    """Requirement: no route returns more than one page's figures per request.

    The metro tables are the case this is written for — many ZIPs per fetch,
    a numeric column each, and not shaped like a data file.
    """
    metro = WEB / "metro"
    if not metro.is_dir():
        pytest.skip("metro pages not built")
    offenders = []
    for f in sorted(metro.glob("*/index.html")):
        html = f.read_text()
        if 'class="zips"' not in html:
            continue
        table = html[html.index('<table class="zips"'):]
        table = table[:table.index("</table>")]
        rows = len(re.findall(r"<tr>", table))
        figures = len(re.findall(r'class="num', table))
        if rows > 1 and figures:
            offenders.append((f.parent.name, rows, figures))
    assert not offenders, (
        f"{len(offenders)} metro page(s) publish a figure per ZIP in one "
        f"fetch: {offenders[:3]}")


def test_the_state_hubs_list_ratings_not_figures():
    hubs = sorted((WEB / "zip").glob("*/index.html"))
    hubs = [h for h in hubs if len(h.parent.name) == 2]
    if not hubs:
        pytest.skip("state hubs not built")
    for f in hubs[:8]:
        html = f.read_text()
        assert not re.search(r'class="num[" ]', html), \
            f"{f.parent.name} hub publishes a figure column"


def test_the_endpoint_serves_one_zip_and_names_its_columns():
    """The republication boundary. One ZIP per request, no list form, and a
    named SELECT — raw_json must never appear."""
    src = (ROOT / "supabase" / "functions" / "market-reading" / "index.ts").read_text()
    # Strip comments first. The file's own header explains at length that
    # raw_json is never read, so a grep of the source finds the word and fails
    # on the documentation rather than on the behaviour.
    code = re.sub(r"//[^\n]*", "", src)
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    assert "raw_json" not in code, "the endpoint can reach the vendor payload"
    assert 'searchParams.get("zip")' in src
    assert re.search(r'/\^\\d\{5\}\$/', src), "the zip parameter is not pinned to one ZIP"
    for forbidden in ("select=*", "zip=in.", "&limit=1000", "zips="):
        assert forbidden not in src, f"the endpoint exposes a bulk form: {forbidden}"
    assert "rateAllowed(" in src, "no rate limit"
    assert "ALLOWED_ORIGINS" in src and "*" not in re.findall(
        r'"Access-Control-Allow-Origin":\s*([^,\n]+)', src)[0], "CORS wildcard"


def test_the_endpoint_explains_why_it_is_an_endpoint():
    """Required by the remediation: the file must say what the serving model
    is for, so the next person does not 'simplify' it back into a file."""
    src = (ROOT / "supabase" / "functions" / "market-reading" / "index.ts").read_text()
    assert "SERVING MODEL" in src.upper()
    assert "dataset" in src.lower()
