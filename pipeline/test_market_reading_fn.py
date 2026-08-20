"""The reading endpoint's SELECT list is the republication boundary.

This function is the one place that decides what leaves the private store for
a reader. It is TypeScript, so these are source-level guards rather than
behavioural tests — but the properties they pin are the ones that would be
expensive to get wrong, and each has a specific failure behind it:

  * raw_json is the untouched vendor payload. Passing it through would
    republish wholesale exactly what the migration removed from the repo.
  * The released check must read the database, not the request. "May this ZIP
    be shown" is the question a caller must not answer.
  * A per-ZIP endpoint over 22,874 keys is enumerable by construction, so the
    rate limiter is not optional.
  * Errors must not echo REST failures, which carry column names and row
    fragments.

Run: python3 -m pytest pipeline/test_market_reading_fn.py -q
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FN = ROOT / "supabase" / "functions" / "market-reading" / "index.ts"
SRC = FN.read_text()

# The handler body with comments stripped. Several of these checks are about
# ORDER — does the released check gate the reading? — and the header comment
# names both tables, so a naive index() on the whole file compares against
# prose rather than code.
CODE = "\n".join(l for l in SRC.splitlines() if not l.strip().startswith("//"))
BODY = CODE[CODE.index("Deno.serve"):]

# Every `select=` list, which is the full set of fields that can reach a
# reader. The lists are built by string concatenation across lines, so a
# fragment can end mid-list — join the pieces and drop the empties rather
# than treating a trailing comma as a field named "".
SELECTS = [s for s in re.findall(r"select=([a-zA-Z0-9_,\.]+)", CODE)]


def test_the_function_exists_where_the_deploy_expects_it():
    assert FN.exists(), "supabase/functions/market-reading/index.ts"


def test_no_select_list_requests_the_raw_vendor_payload():
    for s in SELECTS:
        assert "raw_json" not in s, f"raw_json in a select list: {s}"


def test_raw_json_appears_only_in_prose():
    """It is named in the comments deliberately — the warning is the point —
    but it must never appear in code."""
    for line in SRC.splitlines():
        if "raw_json" in line:
            stripped = line.strip()
            assert stripped.startswith("//"), f"raw_json in code: {stripped[:80]}"


def test_every_selected_field_is_one_we_intend_to_publish():
    """A field added to a SELECT is a field published to the world. Pin the
    whole set so widening it is a deliberate edit to this list."""
    allowed = {
        "zip", "basis", "released_at", "as_of_month", "retrieved_at",
        "list_median_price", "list_median_ppsf", "active_dom",
        "total_listings", "new_listings", "history_months",
    }
    for s in SELECTS:
        for field in s.split(","):
            if not field:
                continue          # a list continued on the next source line
            assert field in allowed, f"unexpected field published: {field!r}"


def test_the_released_check_reads_the_database():
    assert "zip_release" in BODY, "the allowlist table must be consulted"
    # and it must happen before market_stats is read — checked in the handler
    # body, since the header comment names both tables in the other order.
    assert BODY.index("zip_release") < BODY.index("market_stats"), \
        "the released check must gate the reading, not follow it"


def test_release_state_is_never_taken_from_the_request():
    params = re.findall(r"searchParams\.get\(\"([^\"]+)\"\)", SRC)
    assert params == ["zip"], f"the only accepted parameter is zip, got {params}"


def test_the_endpoint_is_rate_limited():
    assert "rateAllowed" in SRC, "a 22,874-key endpoint must be rate limited"


def test_errors_do_not_echo_the_upstream_failure():
    tail = SRC[SRC.index("catch"):]
    for leak in ("e.message", "String(e)", "${e}", "err.message"):
        assert leak not in tail, f"error path echoes upstream detail: {leak}"


def test_zip_is_shape_checked_before_any_query():
    assert r"^\d{5}$" in BODY, "zip must be shape-checked"
    # against the first CALL to rest(), not its definition further up the file
    assert BODY.index("test(zip)") < BODY.index("await rest("), \
        "shape check must precede the first query"


def test_cors_is_the_site_origin_not_a_wildcard():
    assert '"Access-Control-Allow-Origin": "https://shouldisellyet.com"' in SRC
    assert '"*"' not in SRC.split("const CORS")[1].split("}")[0]


def test_unreleased_and_unknown_zips_are_indistinguishable():
    """Telling a caller which ZIPs exist but are unreleased maps the release
    plan before it ships."""
    assert SRC.count('"pending_migration"') >= 2, \
        "the not-released and error paths should both return pending_migration"


def test_the_three_data_statuses_are_all_reachable():
    for status in ("ok", "insufficient_data", "pending_migration"):
        assert f'"{status}"' in SRC, f"dataStatus {status} is never returned"


def test_responses_are_cacheable():
    assert "max-age" in SRC and "stale-while-revalidate" in SRC


# ————— the schema half —————

def test_the_allowlist_table_is_private():
    sql = (ROOT / "supabase" / "schema-v36.sql").read_text()
    assert "create table if not exists public.zip_release" in sql
    assert "enable row level security" in sql
    assert "revoke all on table public.zip_release from anon, authenticated" in sql


def test_the_release_tool_writes_both_sides():
    """tranches.json drives the build, zip_release drives the API. A ZIP in
    one and not the other renders a reading the API will not serve."""
    src = (ROOT / "pipeline" / "promote_tranche.py").read_text()
    assert "zip_release" in src, "releasing must update the server-side allowlist"
    assert "def sync_release" in src
    # and a failure to write it must be loud, not silent
    assert "::warning::" in src or "WARNING" in src
