#!/usr/bin/env python3
"""Where the monthly research pipeline keeps its per-ZIP state.

levels-{month}.json and streaks.json are inputs to the next month's build:
research.load_levels(prev) reads the prior month to count how many ZIPs crossed
into WATCH or ACT. They were also committed to a PUBLIC repository, which
published ~25,000 ZIP-to-rating pairs a month — roughly 20,000 of them for
markets whose own pages decline to state a rating, while the release page said
"We do not publish the list". This module moves that state to the private store.

THE FAILURE THIS MODULE IS BUILT AROUND. If the prior month's levels cannot be
loaded, the flip count silently becomes zero: every ZIP looks new, nothing looks
like a crossing, and the release page publishes "0 ZIP markets moved" with no
error anywhere. That is worse than a crash, because it is publishable. So
load_levels raises unless the caller explicitly says a miss is acceptable —
which is only true for the very first month, where there is no prior.

ORDER OF PRECEDENCE. Store first, file second. During the migration both exist:
writes go to both, reads prefer the store, and the files stay committed until a
CI run has demonstrably written to the store. Only then do the files leave the
repo — removing them first would break the next build with no way to tell
whether the store path ever worked.

CREDENTIALS. SUPABASE_URL + SUPABASE_SERVICE_KEY, the same pair rescore_v2 uses.
Absent them every function returns None and the caller falls back to files, so a
local run with no credentials behaves exactly as it did before this module
existed.

Run: python3 -m pytest pipeline/test_research_store.py -q
"""

import json
import os
import urllib.error
import urllib.request

TABLE = "research_state"
TIMEOUT = 120


class StateUnavailable(RuntimeError):
    """Raised when state that the build REQUIRES cannot be read.

    Deliberately not caught anywhere in the build path. A missing prior month
    does not degrade the output, it falsifies it.
    """


def _creds():
    url = os.environ.get("SUPABASE_URL", "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    return (url, key) if url and key else (None, None)


def configured():
    return _creds() != (None, None)


def _request(method, path, body=None, extra_headers=None):
    url, key = _creds()
    if not url:
        return None
    headers = {"apikey": key, "Authorization": f"Bearer {key}",
               "Content-Type": "application/json"}
    headers.update(extra_headers or {})
    req = urllib.request.Request(
        f"{url}/rest/v1/{path}", method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers=headers)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        raw = r.read().decode()
    return json.loads(raw) if raw.strip() else []


def get(key):
    """Return the stored payload for `key`, or None if unset/unavailable."""
    if not configured():
        return None
    try:
        rows = _request("GET", f"{TABLE}?key=eq.{key}&select=payload,rows")
    except urllib.error.URLError:
        return None
    if not rows:
        return None
    payload, n = rows[0].get("payload"), rows[0].get("rows")
    # `rows` exists so a short write is visible without parsing the blob. A
    # levels file that arrived half-complete would understate the flip count and
    # nothing downstream would notice.
    if n is not None and payload is not None and len(payload) != n:
        raise StateUnavailable(
            f"{key}: stored row count {n} does not match payload length "
            f"{len(payload)} — refusing to build on a short read")
    return payload


def put(key, payload):
    """Upsert `payload` under `key`. Returns True on success, False if unset."""
    if not configured():
        return False
    _request("POST", f"{TABLE}?on_conflict=key",
             body={"key": key, "payload": payload, "rows": len(payload)},
             extra_headers={"Prefer": "resolution=merge-duplicates"})
    return True


def levels_key(month):
    return f"levels-{month}"


STREAKS_KEY = "streaks"
