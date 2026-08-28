"""VELOCITY_ENABLED is one switch, and it actually stops the read.

The panel this guards is the only surface in DERIVED_USE_INVENTORY.md that was
SELLING frozen vendor-derived figures: `verify-access` joined `zip_velocity`
— 27,405 rows, every one `source='redfin'` since schema-v34 — on every valid
purchase token, and `web/my-report.html` rendered the result as a section of
the paid report.

Three failure modes, one per group of tests below:

  * THE FLAG SPLITS. Three copies in three languages (Python here, a Deno
    constant, a browser constant) and no import between them. Flipping one is
    a fix that reads as done and is not; test_all_three_copies catches it.
  * THE GUARD IS DECORATIVE. A constant declared and then not consulted, or
    consulted after the fetch — which would still pull the rows across the
    wire. The structural tests walk braces rather than grepping, because
    "the guard appears somewhere in the file" is not the property that matters.
  * THE COPY LIES. renderVelocity's pre-existing empty-row branch says the
    number is "computed on the next data refresh — check back shortly". True
    of an unseeded ZIP, false here, and the difference is what a paying
    customer is owed: this is a rebuild on a new source, not a late job.

Run: python3 -m pytest pipeline/test_velocity_switch.py -q
"""

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "pipeline"))

import velocity_switch as VEL

REPORT_SRC = (REPO / "web" / "my-report.html").read_text()
VERIFY_SRC = (REPO / "supabase" / "functions" / "verify-access" / "index.ts").read_text()

LITERAL = re.compile(r"const\s+VELOCITY_ENABLED\s*=\s*(true|false)\s*;")


def code(src):
    """Source with comments stripped.

    test_figures_switch's reason, which cost it a bug once: a switch that is
    documented in a comment and not honoured in the code reads identically to
    grep. Everything asserted below is asserted against code only.
    """
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S)
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def block_after(src, opener):
    """The brace-balanced block introduced by `opener`, e.g. an if-statement.

    Returns the text between its `{` and the matching `}`. Used instead of an
    index comparison because "the fetch appears after the guard" is satisfied
    by a fetch that sits after the guard's closing brace — which is exactly
    the unguarded read this file exists to prevent.
    """
    i = src.index(opener)
    j = src.index("{", i)
    depth, k = 0, j
    while k < len(src):
        if src[k] == "{":
            depth += 1
        elif src[k] == "}":
            depth -= 1
            if depth == 0:
                return src[j + 1:k]
        k += 1
    raise AssertionError(f"unbalanced braces after {opener!r}")


# ————— the module, in both states —————

def test_the_committed_state_is_off():
    """A deliberate tripwire, and the one test here that is SUPPOSED to go red
    when the panel is re-enabled.

    Re-enabling means republishing figures to paying customers, so it should
    not be possible to do it and have a green suite without touching a test
    that says so out loud. Deleting this assertion is a legitimate part of the
    re-enable change — after the two steps in velocity_switch.py's docstring
    (upsert_velocity.py writes an explicit `source`; the table is refreshed),
    not before. Every other test in this file passes in both states.
    """
    assert VEL.VELOCITY_ENABLED is False, (
        "velocity is enabled. If that is intentional, confirm "
        "pipeline/upsert_velocity.py now writes an explicit `source` — the "
        "zip_velocity column default is 'redfin', so rebuilt rows inherit the "
        "outgoing vendor's tag — then retire this assertion in the same change.")


@pytest.fixture
def velocity_on(monkeypatch):
    monkeypatch.setattr(VEL, "VELOCITY_ENABLED", True)


@pytest.fixture
def velocity_off(monkeypatch):
    monkeypatch.setattr(VEL, "VELOCITY_ENABLED", False)


def test_shows_velocity_is_false_while_the_switch_is_off(velocity_off):
    assert VEL.shows_velocity() is False


def test_shows_velocity_is_true_when_the_switch_is_flipped(velocity_on):
    assert VEL.shows_velocity() is True


def test_the_notice_renders_while_the_switch_is_off(velocity_off):
    html = VEL.notice_html()
    assert VEL.NOTICE_TITLE in html and VEL.NOTICE_BODY in html
    assert 'role="status"' in html


def test_the_notice_is_empty_when_the_switch_is_flipped(velocity_on):
    """Empty, not hidden. A notice that ships with display:none is a notice
    somebody un-hides by accident."""
    assert VEL.notice_html() == ""


def test_the_notice_names_no_vendor_and_does_not_call_the_number_late():
    """Both halves of the standing rebuild wording, pinned.

    Naming the outgoing vendor on a serving surface is the thing the whole
    sweep is about. Saying "check back shortly" is the subtler failure: it
    tells a customer a number is coming tomorrow when what is actually
    happening is a rebuild on a different source.
    """
    text = (VEL.NOTICE_TITLE + " " + VEL.NOTICE_BODY).lower()
    for bad in VEL.NOTICE_FORBIDDEN:
        assert bad not in text, f"the rebuild notice says {bad!r}"
    assert "rebuilt" in text and "new data source" in text, \
        "the notice must say what is actually happening"
    assert "will return" in text, "the notice must say the section comes back"


# ————— one switch, three copies —————

def test_all_three_copies_carry_the_same_switch():
    """Python cannot reach a browser or a Deno isolate, so the flag exists
    three times. This test is the only thing that makes that one switch: flip
    the module and forget verify-access and the paid endpoint keeps reading
    the frozen table while the report that displays it goes quiet."""
    for rel in VEL.MIRRORS:
        src = (REPO / rel).read_text()
        m = LITERAL.search(src)
        assert m, f"{rel} has no {VEL.JS_CONST} literal"
        assert (m.group(1) == "true") is VEL.VELOCITY_ENABLED, (
            f"{rel} says {VEL.JS_CONST}={m.group(1)} while "
            f"pipeline/velocity_switch.py says {VEL.VELOCITY_ENABLED} — "
            f"the switch is not one switch")


def test_the_sync_check_would_actually_catch_a_split():
    """A test of the test. An agreement check that cannot fail is worse than
    none, because it is evidence of a property nobody verified."""
    flipped = "false" if VEL.VELOCITY_ENABLED else "true"
    split = LITERAL.sub(f"const VELOCITY_ENABLED = {flipped};", VERIFY_SRC, count=1)
    m = LITERAL.search(split)
    assert m and m.group(1) == flipped, "the literal did not flip"
    assert (m.group(1) == "true") is not VEL.VELOCITY_ENABLED, \
        "the mirror check cannot distinguish the two states"


def test_the_mirror_declares_the_flag_before_it_uses_it():
    """A `const` read before its declaration line has run throws. Since
    2026-08-28 verify-access is the only mirror — the report page computes
    velocity from its own record history and declares no switch at all
    (asserted separately below)."""
    src = code(VERIFY_SRC)
    decl = LITERAL.search(src)
    first_use = re.search(r"\(!?VELOCITY_ENABLED\)", src)
    assert decl and first_use
    assert decl.start() < first_use.start(), \
        f"{VEL.MIRRORS[0]} reads {VEL.JS_CONST} before declaring it"


# ————— verify-access: the read itself is guarded —————

@pytest.mark.skipif(VEL.VELOCITY_ENABLED,
                    reason="only meaningful while velocity is suppressed")
def test_verify_access_cannot_reach_zip_velocity_while_the_switch_is_off():
    """The FETCH is inside the guard, not the response field.

    Filtering after the read still pulls the rows across the wire and into the
    isolate. The whole claim being made to counsel is that the paid endpoint
    does not read the table — not that it reads it and discards the result.
    """
    body = block_after(code(VERIFY_SRC), "if (VELOCITY_ENABLED)")
    assert "zip_velocity" in body, \
        "the zip_velocity fetch is not inside the VELOCITY_ENABLED guard"
    outside = code(VERIFY_SRC).replace(body, "")
    assert "zip_velocity" not in outside, \
        "there is a second, unguarded zip_velocity read in verify-access"


def test_verify_access_still_answers_with_a_velocity_field():
    """`velocity: null` is a shape the report has always handled — it is what
    an unscored ZIP has always produced. Dropping the key instead would make
    the suppressed state a new code path on the client, exercised for the
    first time in production."""
    assert re.search(r"let velocity = null;", code(VERIFY_SRC))
    assert "velocity });" in code(VERIFY_SRC), \
        "the response no longer carries the velocity field"


def test_the_query_survives_for_the_rebuild():
    """Guarded, not deleted. The table is under LEGAL_HOLD.md and the panel is
    coming back; deleting the code path would make its return an archaeology
    exercise over git history — the failure data_pause.py was written to
    avoid."""
    assert "rest/v1/zip_velocity?select=period,payload" in VERIFY_SRC, \
        "the zip_velocity query was removed rather than guarded"


def test_nothing_in_the_serving_layer_writes_to_the_stored_rows():
    """LEGAL_HOLD.md: this is a serving-layer change. Neither file may delete,
    patch or update a stored row — the suppression is what renders, never what
    is held."""
    for rel, src in (("web/my-report.html", code(REPORT_SRC)),
                     ("supabase/functions/verify-access/index.ts", code(VERIFY_SRC))):
        for verb in ('"DELETE"', '"PATCH"', '"PUT"'):
            assert not re.search(verb + r"[^\n]*zip_velocity", src), rel
        assert "zip_velocity" not in src or "method: \"DELETE\"" not in src, rel


# ————— my-report.html: the panel does not render —————
#
# REWRITTEN 2026-08-28. The panel was rebuilt: my-report computes approach
# velocity CLIENT-SIDE from the record's own current-basis history
# (velFromHistory), so the page no longer declares the switch, reads the
# verify-access velocity payload, or renders anything derived from
# zip_velocity. The property counsel cares about got stronger — there is no
# renderer for the frozen table left to guard — and these pins keep it true.

def test_the_report_page_never_reads_the_velocity_payload():
    """No __velocity global, no access.velocity read, no v.sig consumer: the
    zip_velocity payload has NO consumer on this page. The rebuild notice and
    its constants went with the renderer they explained."""
    src = code(REPORT_SRC)
    for needle in ("__velocity", "access.velocity", "VEL_REBUILD"):
        assert needle not in src, \
            f"my-report consumes the zip_velocity payload again ({needle!r})"
    # renderVelocity's `v` must be the page's own computation, not an argument
    # something could feed the server payload through.
    body = block_after(src, "function renderVelocity(d)")
    assert "velFromHistory(d)" in body, \
        "renderVelocity no longer derives its rows from the record's history"
    assert not LITERAL.search(src), \
        "my-report declares VELOCITY_ENABLED again — it left the mirror list " \
        "when the panel stopped rendering zip_velocity (velocity_switch.MIRRORS)"


def test_the_rebuilt_panel_asserts_its_lineage_before_computing():
    """velFromHistory refuses anything that is not the released current
    basis: the basis literal is checked before a single number is computed,
    which is what makes 'computed from the pull's history' an assertion
    rather than an assumption."""
    body = block_after(code(REPORT_SRC), "function velFromHistory(d)")
    guard = body.index('d.b !== "active listings"')
    for token in ("velCalc(", "d.h.p", "d.h.d"):
        assert body.index(token) > guard, \
            f"{token} runs before the basis assertion in velFromHistory"


def test_the_rebuilt_panel_estimates_nothing_it_cannot_compute():
    """Inventory has no monthly series in the record, so its row must be the
    pending one — a missing number is shown as missing, never estimated —
    and a thin series must yield pending, not a confident month count."""
    src = code(REPORT_SRC)
    assert "invy: { pending: true }" in src, \
        "the inventory row invents a velocity it has no history for"
    body = block_after(src, "function velCalc(levels, currentYoy, line, dangerDown)")
    assert "pending: true" in body, "velCalc lost its thin-series refusal"


def test_the_months_to_line_display_is_capped():
    """Past two years a straight-line pace is a guess wearing a number —
    the display says '>24 mo' rather than printing it."""
    assert ">24 mo" in REPORT_SRC


def test_the_velocity_watch_toggle_is_not_offered():
    """The escalation alert compared server-side states from the frozen
    rows; until a server-side recompute exists on the current basis there is
    nothing honest for the toggle to promise. save-watch still accepts the
    metric, so the page must simply not offer it."""
    src = code(REPORT_SRC)
    assert "toggleVelWatch" not in src, \
        "the velocity watch toggle is back without a current-basis recompute behind it"
