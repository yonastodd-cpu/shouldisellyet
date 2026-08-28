"""The demand log stays a counter, not a tracker — and its enums can't drift.

supabase/functions/demand/index.ts writes public.zip_lookups (schema-v41).
Three properties pinned here, each with a failure behind it:

  * The outcome enums must match the schema's CHECK constraint — a drifted
    enum silently drops the very rows the funnel exists to measure (the
    lesson test_track_events.py already encodes for events).
  * Browsers may log only the three lookup outcomes. The two pull_* outcomes
    are server-written by ondemand-pull; a browser that could log them could
    fabricate coverage-gap data.
  * Privacy posture identical to track: hour-truncated timestamps, no PII
    columns in the table, rate-limited, origin-allowlisted.

Run: python3 -m pytest pipeline/test_demand_fn.py -q
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FN = (ROOT / "supabase" / "functions" / "demand" / "index.ts").read_text()
PULL = (ROOT / "supabase" / "functions" / "ondemand-pull" / "index.ts").read_text()
# v42 re-states the outcome CHECK (adding paid_coverage_gap) and is what is
# applied to production — the authority for what may be written.
SQL = (ROOT / "supabase" / "schema-v42.sql").read_text()


def _schema_outcomes():
    m = re.search(r"zip_lookups_outcome_check check \(outcome in\s*\(([^)]+)\)",
                  SQL, re.S)
    assert m, "zip_lookups outcome CHECK not found in schema-v42"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def _fn_outcomes():
    m = re.search(r"const OUTCOMES = new Set\(\[(.*?)\]\)", FN, re.S)
    assert m, "OUTCOMES set not found in demand/index.ts"
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def test_browser_outcomes_are_the_three_lookup_ones_only():
    assert _fn_outcomes() == {"reading_shown", "notice_shown", "invalid_zip"}, \
        "pull_* outcomes are server-written; a browser must not log them"


def test_every_outcome_written_anywhere_is_in_the_schema():
    schema = _schema_outcomes()
    assert _fn_outcomes() <= schema
    for server_only in ("pull_failed", "pull_capacity", "paid_coverage_gap"):
        assert server_only in schema
        assert f'"{server_only}"' in PULL, \
            f"{server_only} is in the schema but nothing writes it"


def test_timestamps_are_hour_truncated():
    assert "3600000) * 3600000" in FN, \
        "the demand log keeps the events posture: hourly, never precise"


def test_the_function_is_rate_limited_with_a_window():
    m = re.search(r"rateAllowed\(([^)]*)\)", FN)
    assert m, "a public write endpoint must be rate limited"
    args = [a.strip() for a in m.group(1).split(",")]
    assert len(args) >= 4 and args[3].isdigit()


def test_origins_are_allowlisted_not_reflected():
    assert "ORIGINS = new Set" in FN
    assert '"*"' not in FN


def test_the_table_stores_no_identifier():
    """The columns ARE the privacy policy. No email, no IP, no user agent —
    and the id is a client-random UUID, constrained to name a lookup.
    The column list lives in v41's CREATE TABLE (v42 only restates the
    outcome CHECK), so this reads v41."""
    v41 = (ROOT / "supabase" / "schema-v41.sql").read_text()
    block = v41[v41.index("create table if not exists public.zip_lookups"):
                v41.index("alter table public.zip_lookups")]
    for pii in (r"\bemail\b", r"\bip\b", r"\buser_agent\b",
                r"\breferrer\b", r"\bsession\b"):
        assert not re.search(pii, block), f"zip_lookups grew a {pii} column"


def test_follow_can_only_set_a_boolean_true():
    """The PATCH body must be exactly one followed_* flag — a widened update
    would let any holder of a UUID rewrite the row."""
    m = re.search(r'"PATCH", \{ \[col\]: true \}', FN)
    assert m, "the follow update must set one boolean and nothing else"


def test_errors_do_not_echo_the_upstream_failure():
    tail = FN[FN.index("catch"):]
    for leak in ("e.message", "String(e)", "${e}"):
        assert leak not in tail
