"""The advisory invariant, as a test: performance data may produce SENTENCES,
never behaviour.

The marketing queue reads its own results — checks and clicks per post — and
says things about them ("increase rotation", "consider dropping"). The line
this file defends is that those are the last stop: a human reads them and
decides. If someone later makes the leaderboard writable, teaches the nightly
join to touch a priority, or has a pipeline module branch on an advisory
string, this fails before a reviewer has to notice.

These are structural tests over the settled DDL and the shipped source, not
behaviour tests — the RPCs themselves are only provable against production
(see the (LIVE) rows in the acceptance checklist). Everything here runs
offline, in milliseconds, with no Supabase and no network.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import marketing_perf

ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "supabase" / "schema-v23.sql").read_text(encoding="utf-8")


def _body(fn):
    """The plpgsql body of a function, between its $$ markers."""
    m = re.search(rf"create or replace function public\.{fn}.*?\$\$(.*?)\$\$;", SQL, re.S)
    assert m, f"{fn} not found in schema-v23.sql"
    return m.group(1)


def test_leaderboard_is_stable_hence_readonly():
    """STABLE is not documentation here — Postgres refuses writes inside a
    stable function at runtime, so the function that composes the advisory
    sentences is physically incapable of changing a priority or a schedule."""
    m = re.search(r"function public\.admin_marketing_leaderboard.*?language plpgsql (\w+)",
                  SQL, re.S)
    assert m and m.group(1) == "stable", \
        "admin_marketing_leaderboard must stay STABLE — stable functions cannot write"


def test_perf_refresh_touches_only_perf_columns():
    """The nightly join measures. It does not schedule, re-prioritise, or
    change a status — and the UPDATE's own SET list is where that is true."""
    body = _body(r"marketing_perf_refresh\(p_days")
    sets = re.findall(r"set\s+(.*?)\s+from", body, re.S)[0]
    cols = set(re.findall(r"(\w+)\s*=", sets))
    assert cols == {"perf_checks", "perf_clicks", "perf_checked_at"}, \
        f"perf refresh writes {sorted(cols)} — it may only write measurement columns"


def test_advisory_strings_are_not_consumed_anywhere():
    """Advisories are terminal strings: composed in SQL, rendered as text by
    the Marketing tab, parsed by nothing. A pipeline module that matched on
    one would be automation wearing a sentence as a disguise."""
    phrases = ("increase rotation", "consider dropping")
    for phrase in phrases:      # anchored: the sentences really do exist in the DDL
        assert phrase in SQL, f"advisory {phrase!r} is gone from schema-v23.sql"
    for p in sorted((ROOT / "pipeline").glob("*.py")):
        if p.name.startswith("test_"):
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        for phrase in phrases:
            assert phrase not in text, (
                f"{p.name} references advisory text {phrase!r} — advisories are "
                "sentences for a human, never an input to code")


def test_campaign_regex_is_identical_in_every_layer():
    """The token's shape is written four times — twice in the DDL, once in
    web/track.js, once in the track edge function — because each layer has to
    refuse a bad token on its own. Matched pair, guarded: a widened browser
    regex would send tokens the column rejects, and the whole insert (every
    pageview in that request) would fail on a mangled share link."""
    pats = re.findall(r"utm_campaign ~ '([^']+)'", SQL)
    assert len(pats) == 2 and len(set(pats)) == 1, \
        f"schema-v23 declares {len(set(pats))} campaign shapes, expected one"
    pat = pats[0]
    for rel in ("web/track.js", "supabase/functions/track/index.ts"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert f"/{pat}/" in text, f"{rel} does not carry the DDL's campaign regex {pat}"


def test_perf_job_without_config_exits_zero(monkeypatch, capsys):
    """House rule: missing config prints and exits 0. A fork without secrets
    must not turn this nightly workflow red forever."""
    monkeypatch.setitem(os.environ, "SUPABASE_URL", "")
    monkeypatch.setitem(os.environ, "SUPABASE_SERVICE_KEY", "")
    assert marketing_perf.main() == 0
    assert "not configured" in capsys.readouterr().out
