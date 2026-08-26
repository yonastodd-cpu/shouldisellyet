"""FAIL never creates a charge — pinned where the charge actually happens.

There is no server-side charge in this architecture: the charge IS the
browser navigating to the Stripe Payment Link. So the integration property
"a failed pull never creates a charge" is a property of web/subscribe.html's
go() — the pull must be awaited before the redirect statement, and every
ok:false answer must return out of go() before reaching it. These are
source-order guards, same idiom as the edge-function tests.

Run: python3 -m pytest pipeline/test_ondemand_checkout.py -q
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUB = (ROOT / "web" / "subscribe.html").read_text()
IDX = (ROOT / "web" / "index.html").read_text()


def _go_body():
    body = SUB[SUB.index("async function go()"):]
    # strip line comments so prose can't satisfy an order check
    return "\n".join(l for l in body.splitlines()
                     if not l.strip().startswith("//"))


def test_the_pull_precedes_the_stripe_redirect():
    body = _go_body()
    assert "ondemand-pull" in body, "checkout must call the pull function"
    assert "window.location.href = link" in body
    assert body.index("ondemand-pull") < body.index("window.location.href = link"), \
        "the pull must be awaited BEFORE the buyer is handed to Stripe"


def test_the_pull_is_awaited_not_fire_and_forget():
    body = _go_body()
    call = body[body.index("ondemand-pull") - 200:body.index("ondemand-pull") + 200]
    assert "await fetch" in call, "a fire-and-forget pull gates nothing"


def test_every_failure_answer_returns_before_the_redirect():
    body = _go_body()
    gate = body[body.index("pull.ok === false"):body.index("window.location.href")]
    assert gate.count("return fail(") >= 2, \
        "both no_data and at_capacity must return out of go()"


def test_the_buyer_is_told_they_were_not_charged():
    assert SUB.count("haven't been charged") >= 2, \
        "both failure messages must say, plainly, that no charge happened"


def test_a_disabled_server_falls_back_rather_than_blocking():
    """If the deployed function says disabled while the page copy says ON
    (the one mismatch the mirror test cannot prevent mid-deploy), checkout
    must proceed on the old coverage-check behaviour, not refuse service."""
    assert 'pull.reason !== "disabled"' in SUB


def test_no_failure_message_names_the_vendor():
    """The vendor's licence bars use of its name in commercial surfaces —
    the same rule that keeps it off the verdict card (see index.html's
    v-stamp comment). The failure copy says 'our data provider'."""
    gate = SUB[SUB.index("ondemand-pull"):SUB.index("window.location.href")]
    assert "RentCast" not in gate
    assert "data provider" in gate


def test_the_notice_branch_carries_the_ondemand_cta():
    assert 'id="v-ondemand"' in IDX
    assert 'id="cta-ondemand-report"' in IDX
    # and the CTA is wired inside the no-reading branch, gated by the switch
    branch = IDX[IDX.index("if (!hasReading)"):]
    assert "ONDEMAND_ENABLED" in branch[:3000]


def test_the_notice_branch_captures_notify_me():
    """Every notice render shows the capture card with the goes-live copy."""
    branch = IDX[IDX.index("if (!hasReading)"):IDX.index("reading_shown")]
    assert "wl-title" in branch and "waitcard" in branch
    assert "goes live" in branch
    assert 'wlSource = "notice"' in branch


def test_demand_outcomes_are_logged_on_all_three_branches():
    for outcome in ("invalid_zip", "notice_shown", "reading_shown"):
        assert f'SISY.demand(zip, "{outcome}")' in IDX, f"missing {outcome} log"


def test_follows_are_marked_where_they_happen():
    assert 'SISY.follow(zip, "notify")' in IDX
    assert 'SISY.follow(pfZip, "purchase")' in SUB
