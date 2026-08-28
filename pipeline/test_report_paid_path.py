"""The paid report page: the pull fires where the ZIP becomes known, the
waitlist is never the answer to a paying customer, and the report-build path
sends nothing but the ZIP (and the access token).

Source-level pins on web/my-report.html, the same idiom as
test_prior_vendor_serving_surfaces.py — this is a committed, hand-written
page no pipeline change ever reaches. Behind them is a real incident
(2026-08-28): a customer paid for ZIP 20005, the checkout's pull stored the
data at 21:50:56Z, and the report page refused them with waitlist copy
anyway, because their browser held the day-long cached miss from their
21:00 homepage check.

Run: python3 -m pytest pipeline/test_report_paid_path.py -q
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "web" / "my-report.html").read_text(encoding="utf-8")


def code(src):
    """Comment-stripped source — comments may state the rules they enforce.
    The line-comment strip spares protocol slashes (https://...): the page's
    endpoint constants are code, not commentary."""
    src = re.sub(r"<!--.*?-->", " ", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    return re.sub(r"(?<!:)//[^\n]*", " ", src)


CODE = code(SRC)


# ————— never the waitlist —————

def test_no_waitlist_copy_anywhere_on_the_paid_page():
    """gate B enforces the same rule in CI against the built tree; this is
    the fast local half. Comment-stripped: the comments explaining this rule
    are allowed to say the word."""
    assert not re.search(r"waitlist", CODE, re.I), \
        "waitlist copy is back on the paid report page"


def test_the_unpaid_fallback_does_not_dead_end_either():
    """The no-token preview gets pointed at the free check — factual, no
    waitlist framing, and only after the paid path was tried first."""
    assert "Run the free check on the homepage" in SRC


# ————— the pull fires where the ZIP becomes known —————

def test_the_paid_recovery_exists_and_uses_the_checkout_pull():
    """Same function, same floor, same ledger, same dedupe — the token makes
    it paid. Every paid path that can reach generate() with an uncovered ZIP
    (Stripe-direct, billing-ZIP row, mismatch pick, shared link) converges on
    this call."""
    assert "functions/v1/ondemand-pull" in CODE
    assert re.search(r"body: JSON\.stringify\(\{ zip: zip, token: TOKEN \}\)", CODE), \
        "the paid pull must send exactly zip + token"


def test_the_cached_miss_is_bypassed_before_declaring_no_reading():
    """The 20005 mechanism: the reading endpoint's misses are cacheable, and
    a pull can land between the homepage check and the report build. The
    recovery path must re-fetch past the browser cache."""
    assert '"reload"' in CODE, \
        "no cache-busted re-fetch — a cached miss can outlive a successful pull"


def test_the_recovery_only_runs_for_paid_visitors():
    assert re.search(r"isPaid = !!\(TOKEN && SUB_PLAN\) \|\| justPaid", CODE), \
        "the paid recovery must be gated on a verified token or a fresh checkout return"


def test_one_vendor_attempt_per_zip_per_page_load():
    """The cost-slider re-runs generate(); a still-uncovered ZIP must not
    turn slider drags into vendor calls."""
    assert "pullTried[zip]" in CODE


def test_the_progress_state_is_a_note_not_an_error():
    assert "Pulling fresh market data for " in SRC
    assert 'id="pull-note"' in SRC


# ————— the partial report, honestly —————

def test_the_paid_gap_state_exists_with_the_honest_copy():
    gap = re.search(r"gap:\{[\s\S]*?meaning:[^}]*\}", SRC)
    assert gap, "the gap KIND is gone from KINDS"
    blob = gap.group(0)
    assert "reply to your receipt email for a full refund" in blob
    assert "local reading" in blob
    # The vendor stays unnamed on customer surfaces (test_pause_leaks pins
    # the page-wide rule; this pins the copy that was most tempted to name it).
    assert "RentCast" not in blob


def test_the_gap_state_hides_the_dials_and_clears_the_cross_check():
    m = re.search(r"if \(paidGap\) \{(.*?)\} else \{", CODE, re.S)
    assert m, "the gap branch around the market renders is gone"
    assert '$("metrics").innerHTML = ""' in m.group(1)
    assert "xcheck" in m.group(1)


# ————— the privacy claim, made true and kept true —————

def test_the_privacy_copy_matches_what_the_page_actually_sends():
    """The old line ("Nothing you type here leaves your browser") was false:
    the address syncs to the account row and a saved alert sends the numbers
    it watches. The new copy scopes the promise to the report build and
    names both explicit sync actions."""
    assert "Nothing you type here leaves your browser" not in SRC
    assert "only your ZIP is sent" in SRC
    assert "any personal alert you turn on" in SRC


def test_the_report_build_path_sends_only_the_zip():
    """The promise, asserted. Every request the report BUILD can make —
    the reading fetch and the paid pull — carries the ZIP (plus the access
    token on the pull) and none of the intake fields. Address and calculator
    numbers travel only in pushAddress and saveWatch, both user actions."""
    reading = re.findall(r'MARKET_API \+ "\?zip=" \+ encodeURIComponent\(zip\)', CODE)
    assert reading, "the reading fetch no longer builds its URL from the ZIP alone"
    pull = re.search(r"ONDEMAND_FN, \{[^}]*\}[\s\S]*?JSON\.stringify\(\{ zip: zip, token: TOKEN \}\)", CODE)
    assert pull, "the paid pull body must be exactly { zip, token }"
    for field in ("in-val", "in-bal", "in-rate", "address_street", "calcInputs"):
        assert field not in (pull.group(0) if pull else ""), \
            f"the pull payload grew {field}"
    # And the only senders of intake data remain the two explicit actions.
    for fn, needle in (("pushAddress", "SAVE_ADDR_FN"), ("saveWatch", "SAVE_WATCH_FN")):
        assert needle in CODE, f"{fn} lost its endpoint — re-audit the privacy copy"
