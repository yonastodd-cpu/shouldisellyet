"""The purchase-time pull function: order of operations IS the product.

Source-level guards on supabase/functions/ondemand-pull/index.ts, same idiom
as test_market_reading_fn.py. Each pin has a specific failure behind it:

  * The store must be consulted BEFORE the vendor — dedupe is the cost
    model. A pulled ZIP is live for a month; buyer #2 must cost $0.
  * The ceiling must be counted BEFORE the vendor call — at capacity the
    answer is "at_capacity", never a silent overage.
  * Validation must precede storage-as-released: a ZIP below the quality
    floor must never gain a zip_release row, because that row is what makes
    the API serve it.
  * The engine constants are a MIRROR of verdict_v2.SPEC. A recalibration
    that edits one and not the other sells a reading the site would not
    publish.
  * raw_json goes INTO the store here (acquisition) and never back out.

Run: python3 -m pytest pipeline/test_ondemand_pull_fn.py -q
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import verdict_v2

ROOT = Path(__file__).resolve().parents[1]
FN = ROOT / "supabase" / "functions" / "ondemand-pull" / "index.ts"
SRC = FN.read_text()
CODE = "\n".join(l for l in SRC.splitlines() if not l.strip().startswith("//"))
BODY = CODE[CODE.index("Deno.serve"):]


def test_the_function_exists_where_the_deploy_expects_it():
    assert FN.exists()


# ————— the SPEC mirror —————

def _ts_spec():
    block = re.search(r"const SPEC = \{(.*?)\};", CODE, re.S).group(1)
    out = {}
    for m in re.finditer(r"(\w+):\s*(-?[\d.]+|\"[^\"]*\")", block):
        k, v = m.group(1), m.group(2)
        out[k] = v.strip('"') if v.startswith('"') else float(v)
    return out


def test_the_engine_constants_mirror_verdict_v2():
    ts = _ts_spec()
    keys = ("basis", "price_fast", "price_slow", "dom_stretch",
            "inventory_surge", "red", "yellow", "price_surge", "dom_shrink",
            "inventory_drop", "strong_min", "min_known")
    for k in keys:
        assert k in ts, f"SPEC mirror is missing {k}"
        want = verdict_v2.SPEC[k]
        got = ts[k]
        if isinstance(want, (int, float)):
            assert float(got) == float(want), (
                f"SPEC.{k}: function says {got}, verdict_v2 says {want} — "
                f"recalibrating means editing BOTH and redeploying the function")
        else:
            assert got == want, f"SPEC.{k}: {got!r} != {want!r}"


def test_the_basis_written_is_the_released_basis():
    """zip_release/zip_readings rows must carry the same basis literal the
    rest of the release machinery uses (data_pause.RELEASED_BASIS)."""
    import data_pause
    assert _ts_spec()["basis"] == data_pause.RELEASED_BASIS


# ————— order of operations —————

def test_the_store_is_checked_before_the_vendor_is_called():
    assert "market_stats" in BODY and "api.rentcast.io" in BODY
    assert BODY.index("market_stats") < BODY.index("api.rentcast.io"), \
        "dedupe requires the private store to answer before money is spent"


def test_the_ceiling_is_counted_before_the_vendor_is_called():
    assert "ondemand_pulls" in BODY
    assert BODY.index("ondemand_pulls") < BODY.index("api.rentcast.io"), \
        "the ceiling gates the vendor call, not the other way round"


def test_an_uncountable_ceiling_refuses_to_spend():
    """If the count query fails we cannot prove we are under the ceiling, and
    the honest degrade is at_capacity — never a silent overage."""
    assert "at_capacity" in BODY
    assert BODY.count("at_capacity") >= 2


def test_validation_gates_the_release_row():
    """A ZIP below the floor must never become released/servable."""
    gate = BODY.index("min_known")
    release_write = BODY.index("zip_release?on_conflict")
    # the SECOND zip_release write (the post-pull one) must follow validation;
    # the first is the store-heal path which only fires when data exists.
    second = BODY.index("zip_release?on_conflict", release_write + 1)
    assert gate < second, "the quality floor must precede the release insert"


def test_the_release_insert_never_relabels_a_tranche_row():
    assert "ignore-duplicates" in BODY, \
        "zip_release upserts must ignore existing rows, not overwrite tranche"


def test_zip_is_shape_checked_before_any_query():
    assert r"^\d{5}$" in BODY
    assert BODY.index("test(zip)") < BODY.index("await rest(")


def test_the_endpoint_is_rate_limited_with_windows():
    calls = re.findall(r"rateAllowed\(([^)]*)\)", BODY)
    assert len(calls) >= 2, "both the endpoint and the vendor path need caps"
    for call in calls:
        args = [a.strip() for a in call.split(",")]
        assert len(args) >= 4 and args[3].isdigit(), f"window required: {args}"
    # the vendor path's cap is the farm-guard on the pre-payment pull: tight.
    vendor_cap = int([a.strip() for a in calls[-1].split(",")][2])
    assert vendor_cap <= 5, f"{vendor_cap}/h lets one IP farm paid pulls"


# ————— the boundary —————

def test_no_select_list_reads_the_raw_vendor_payload():
    for s in re.findall(r"select=([a-zA-Z0-9_,\.]+)", CODE):
        assert "raw_json" not in s, f"raw_json read back out of the store: {s}"


def test_the_response_carries_no_vendor_measurement():
    """ok/served/reason only — the checkout page needs a yes or a no, and a
    response carrying figures would be a second reading endpoint with none
    of market-reading's guards."""
    for m in re.finditer(r"json\(\{ ok: true[^}]*\}", BODY):
        blob = m.group(0)
        for field in ("metrics", "priceHistory", "medianPrice", "reasons"):
            assert field not in blob, f"success response leaks {field}"


def test_errors_do_not_echo_the_upstream_failure():
    tail = SRC[SRC.index("catch"):]
    for leak in ("e.message", "String(e)", "${e}", "err.message"):
        assert leak not in tail


def test_cors_is_not_a_wildcard():
    assert '"*"' not in SRC


def test_missing_api_key_degrades_to_capacity_not_error():
    """No key = nothing can be pulled = sell nothing. The message must be the
    capacity one (honest, actionable) and the store-served path must still
    work — pinned by the key check sitting on the vendor path, after the
    store check."""
    assert "RENTCAST_KEY" in BODY
    assert BODY.index("market_stats") < BODY.index("!RENTCAST_KEY")


def test_the_schema_side_is_private():
    sql = (ROOT / "supabase" / "schema-v41.sql").read_text()
    for table in ("ondemand_pulls", "zip_readings", "zip_lookups"):
        assert f"create table if not exists public.{table}" in sql
        assert f"revoke all on table public.{table} from anon, authenticated" in sql


# ————— the paid path (2026-08-28, the paid-report dead end) —————
# A verified access token makes the pull revenue-backed: it runs even at the
# monthly ceiling, and its floor-failure is a paid_coverage_gap — a person to
# follow up with, not an anonymous data point.

def test_the_token_is_verified_against_the_row_never_trusted():
    """paid=true only after a subscribers lookup by access_token with an
    active status filter — a body field alone must never buy priority."""
    assert re.search(r"access_token=eq\.\$\{token\}&status=in\.\(active,report\)", BODY), \
        "the paid flag is not grounded in a server-side subscriber lookup"
    assert "paid = Array.isArray(sub) && sub.length > 0" in BODY, \
        "paid must be derived from the lookup result"


def test_the_token_is_shape_checked_before_the_lookup():
    """Same uuid discipline as verify-access: garbage never reaches a query."""
    assert re.search(r"\[0-9a-f\]\{8\}.*test\(token\)", BODY), \
        "token must be shape-checked before any subscriber query"


def test_the_store_still_answers_first_for_paid_callers():
    """Dedupe precedes everything, including payment status: buyer #2 in the
    freshness window costs $0 whether or not they carry a token. Pinned by
    order — the store check sits before the token has any effect (the
    ceiling block)."""
    assert BODY.index("market_stats") < BODY.index("if (!paid)"), \
        "the store-first dedupe must not depend on payment status"


def test_the_ceiling_gates_only_the_free_path():
    """The monthly ceiling count sits inside the !paid branch: a paid pull
    proceeds at the ceiling (the purchase already funds the call), and free
    CTAs degrade first because paid pulls still consume the shared count."""
    gate = re.search(r"if \(!paid\) \{(.*?)\n    \}", BODY, re.S)
    assert gate, "the free-path ceiling branch is gone"
    assert "ondemand_pulls?month=" in gate.group(1), \
        "the ceiling count must live inside the free-path branch"
    assert "used >= ceiling()" in gate.group(1)


def test_a_missing_vendor_key_stops_paid_pulls_too():
    """Revenue-backed is not key-less: with no RENTCAST_KEY nothing can pull,
    and the paid caller gets the same honest at_capacity — plus the operator
    email, because a paid customer just hit a wall we built."""
    key_gate = BODY.index("if (!RENTCAST_KEY)")
    assert key_gate < BODY.index("if (!paid)"), \
        "the key check must precede (and apply to) both paths"
    blob = BODY[key_gate:key_gate + 400]
    assert "paid_coverage_gap" in blob and "alertPaidGap" in blob


def test_every_pull_still_writes_a_ledger_row():
    """recordPull is called on pulled/no_data/error regardless of payment
    status — the ledger is the cost model and paid calls cost the same."""
    for status in ('"pulled"', '"no_data"', '"error"'):
        assert f"recordPull(zip, {status}" in BODY.replace("await recordPull", "recordPull"), \
            f"ledger row missing for {status}"


def test_a_paid_floor_failure_is_a_paid_coverage_gap_and_an_email():
    """Both vendor-404 and below-floor: the demand row says paid_coverage_gap
    and the operator is emailed. The free path keeps pull_failed."""
    assert BODY.count('paid ? "paid_coverage_gap" : "pull_failed"') == 2, \
        "both no_data sites must branch the demand outcome on payment status"
    assert BODY.count("alertPaidGap") >= 3, \
        "the operator email must fire on no_vendor_key, vendor_404 and below_floor"


def test_the_paid_gap_email_is_best_effort_and_unkeyed_is_silent():
    """The customer's answer never waits on Resend, and a missing key is a
    no-op rather than an error."""
    fn = SRC[SRC.index("async function alertPaidGap"):]
    fn = fn[:fn.index("\n}")]
    assert "if (!RESEND_KEY) return;" in fn
    assert "catch" in fn
