"""Drift guard for the analytics event enum.

The allowed-event list lives in three places that cannot import each other:
the SQL check constraint (schema-v11.sql), the track edge function's EVENTS
set, and the literals pages actually send. A rename that misses one place
fails silently in production — the event just stops counting — so this test
makes the drift loud instead.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _sql_enum() -> set:
    sql = (ROOT / "supabase" / "schema-v11.sql").read_text(encoding="utf-8")
    m = re.search(r"event in\s*\(([^)]+)\)", sql)
    assert m, "schema-v11.sql: event check constraint not found"
    return set(re.findall(r"'([a-z_]+)'", m.group(1)))


def _fn_enum() -> set:
    ts = (ROOT / "supabase" / "functions" / "track" / "index.ts").read_text(encoding="utf-8")
    m = re.search(r"EVENTS = new Set\(\[(.*?)\]\)", ts, re.S)
    assert m, "track/index.ts: EVENTS set not found"
    return set(re.findall(r'"([a-z_]+)"', m.group(1)))


def _used_literals() -> set:
    used = set()
    # data-track attributes across pages and the generated-page template.
    sources = list((ROOT / "web").glob("*.html")) + [ROOT / "pipeline" / "build_pages.py"]
    for p in sources:
        text = p.read_text(encoding="utf-8", errors="replace")
        used |= set(re.findall(r'data-track="([a-z_]+)"', text))
        # SISY.track("name" | 'name') — first argument only. The subscribe page
        # picks between two literals with a ternary; the regex sees both.
        used |= set(re.findall(r'SISY\.track\(\s*"([a-z_]+)"', text))
        used |= set(re.findall(r"SISY\.track\(\s*'([a-z_]+)'", text))
        used |= set(re.findall(r'"((?:purchase_click_[a-z]+))"', text))
    js = (ROOT / "web" / "track.js").read_text(encoding="utf-8")
    used |= set(re.findall(r'send\("([a-z_]+)"', js))
    return {u for u in used if u}


def test_sql_and_function_enums_match():
    assert _sql_enum() == _fn_enum(), (
        f"SQL {sorted(_sql_enum())} != function {sorted(_fn_enum())}"
    )


def test_every_sent_event_is_allowed():
    unknown = _used_literals() - _sql_enum()
    assert not unknown, f"pages send events the enum rejects: {sorted(unknown)}"


def test_page_view_is_sent():
    # The funnel's top stage — if track.js ever stops sending it, every
    # downstream conversion percentage silently becomes garbage.
    assert "page_view" in _used_literals()
