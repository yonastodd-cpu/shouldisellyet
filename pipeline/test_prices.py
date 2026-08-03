"""Price-drift guard.

web/prices.js is the single source of truth for consumer pricing, and most
surfaces render from it at runtime via data-price attributes. Three places
can't:

  * terms.html / refunds.html — legal text must be correct with JavaScript
    off and in any archived copy, so those prices stay literal.
  * supabase/functions/stripe-webhook — a Deno edge function can't import a
    file served from the website's origin, so it mirrors the numbers.

Literal copies drift silently: nothing breaks, the page just quietly quotes a
price we no longer charge — in the two documents that define the contract.
This test parses prices.js and fails if any of those copies disagree.

Run: python3 -m pytest pipeline/test_prices.py -q
"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
FUNCS = ROOT / "supabase" / "functions"


def prices():
    """The PRICES object literal out of web/prices.js, as a dict."""
    src = (WEB / "prices.js").read_text()
    body = re.search(r"const PRICES = \{(.*?)\n\};", src, re.S).group(1)
    out = {}
    for k, v in re.findall(r"(\w+):\s*([\d.]+)", body):
        out[k] = float(v)
    return out


def usd(n):
    """Mirror of usd() in prices.js: '$29' for whole dollars, '$5.99' otherwise."""
    return "$" + (str(int(n)) if float(n).is_integer() else f"{n:.2f}")


P = prices()
REPORT, MONTHLY = usd(P["REPORT"]), usd(P["MONTHLY"])
ANNUAL, UPGRADE = usd(P["ANNUAL"]), usd(P["UPGRADE"])


def test_constants_are_the_expected_shape():
    """Catches a typo that would otherwise make every assertion below vacuous
    (e.g. a missing key parsing as 0 and matching nothing)."""
    assert set(P) == {"ANNUAL", "MONTHLY", "REPORT", "UPGRADE", "UPGRADE_WINDOW_DAYS"}
    assert all(v > 0 for v in P.values())
    # The upgrade credit is the annual price less the report price, rounded to
    # a whole dollar. If someone changes one without the other, say so here
    # rather than letting the checkout quote an arithmetic that doesn't work.
    assert P["UPGRADE"] == round(P["ANNUAL"] - P["REPORT"]), (
        f"upgrade {UPGRADE} should be {ANNUAL} − {REPORT} rounded"
    )


def test_terms_quotes_current_prices():
    t = (WEB / "terms.html").read_text()
    for want in (f"reports ({REPORT})", f"({ANNUAL}/year billed annually",
                 f"or {MONTHLY}/month billed monthly",
                 f"first year {UPGRADE} instead of {ANNUAL}"):
        assert want in t, f"terms.html is missing {want!r} — legal text has drifted"


def test_refunds_quotes_current_prices():
    t = (WEB / "refunds.html").read_text()
    assert f"One-time reports ({REPORT})" in t
    assert f"Monitoring subscriptions ({ANNUAL}/year, or {MONTHLY}/month)" in t


def test_webhook_mirror_matches():
    """The edge function's PRICES block must equal prices.js exactly."""
    src = (FUNCS / "stripe-webhook" / "index.ts").read_text()
    body = re.search(r"const PRICES = \{(.*?)\n\};", src, re.S).group(1)
    mirror = {k: float(v) for k, v in re.findall(r"(\w+):\s*([\d.]+)", body)}
    assert mirror == P, (
        "stripe-webhook's PRICES mirror has drifted from web/prices.js:\n"
        f"  webhook:   {mirror}\n  prices.js: {P}"
    )


def _customer_visible(html):
    """Page text minus the parts only a developer reads.

    Strips HTML comments and `//` JS comments — both are where we deliberately
    document the OLD amounts (the stale Stripe links in subscribe.html, the
    legacy checkout constant in index.html), and flagging those would train
    everyone to ignore this test. Live script string literals stay in scope: a
    price hardcoded into rendered JS reaches the customer just as surely as one
    in the markup.

    The lookbehind keeps `https://…` from being read as a comment.
    """
    html = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r"(?<![:/])//[^\n]*", "", html)


def test_no_stale_amounts_left_in_consumer_copy():
    """Old prices, in the surfaces a customer reads.

    partners.html is excluded by name: it sells ZIP sponsorship to agents at
    $39/mo, a price that has nothing to do with the consumer ladder and must
    NOT move with it. This is the exact trap a global find-and-replace falls
    into, so the exclusion is deliberate rather than incidental.
    """
    stale = {"$9.99", "$39/yr", "$39/year", "$5.99/mo", "$5.99/month"}
    current = {REPORT, MONTHLY, ANNUAL, UPGRADE}
    hits = []
    for p in sorted(WEB.glob("*.html")):
        if p.name == "partners.html":
            continue
        text = _customer_visible(p.read_text())
        for s in sorted(stale):
            # Only flag prices we no longer charge. "$5.99" alone is now the
            # report price and appears legitimately; only its /mo forms are stale.
            if s in text and s not in current:
                hits.append(f"{p.name}: {s}")
    assert not hits, "stale prices in consumer copy: " + json.dumps(hits, indent=2)
