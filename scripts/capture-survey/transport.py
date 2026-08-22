#!/usr/bin/env python3
"""The only file in this tree that can open a socket, and the gate in front.

TWO INDEPENDENT LOCKS, because one lock is an argument and two are a design.

  1. `ALLOW_NETWORK` is False at import. Only survey.py's --collect handler
     calls enable(), and it does so after parsing the flag, so a caller that
     imports this module and calls request() gets a refusal rather than a
     socket. It is a module attribute read through this module — the same
     pattern as data_pause.PAUSED and realtor_crosscheck.SHOW — so a test can
     monkeypatch it, and so nothing anywhere caches a copy of it.

  2. `import urllib.request` happens INSIDE request(), not at the top of the
     file. That is not stylistic. It means a plan-mode run never loads an HTTP
     client at all, and the test that proves "no code path reaches the network
     without an explicit flag" can assert something checkable and blunt:
     after a full default run, 'urllib.request' is not in sys.modules.
     scripts/audit-og.py is the cautionary example — it reaches into
     pipeline/fetch_data for an SSL context and pulls a network stack into a
     tool that only meant to read.

WHAT THIS WILL AND WILL NOT DO. GET only, and request() refuses anything else
before it looks at the gate. Every removal and re-scrape action the memo
contemplates is a POST or a form submission; sources.py registers one of them
so that its exclusion is documented rather than silent, and the refusal here
is what makes the registration safe. The removal procedures are
manual steps in CAPTURE_SURVEY_RUNBOOK.md, behind counsel sign-off.

A SURVEY IS ITSELF A TRACE. Every request identifies itself in User-Agent,
deliberately: a survey conducted behind an anonymous UA is a worse fact than
one conducted openly, and the archive's logs will hold the requests either
way. Counsel should decide the UA string, not this file — see the runbook.
"""

import time

import sources

ALLOW_NETWORK = False
_ENABLED_REASON = ""

# Identifies the requester. archive.org logs it; so would anyone else. Change
# it only with counsel's agreement — see the runbook's discoverability note.
USER_AGENT = "shouldisellyet-capture-survey (counsel-directed factual survey)"

# One request at a time, spaced. The interval is sources.REQUEST_INTERVAL_S —
# defined there, not here, so plan mode can quote the run time without
# importing this module. See that constant for the reasoning.
MIN_INTERVAL_S = sources.REQUEST_INTERVAL_S
TIMEOUT_S = 30

_last_request = 0.0


class NetworkRefused(RuntimeError):
    """Raised when something tried to fetch without the explicit flag."""


def enable(reason):
    """Open the gate. Called only from survey.py's --collect handler."""
    global ALLOW_NETWORK, _ENABLED_REASON
    ALLOW_NETWORK = True
    _ENABLED_REASON = reason


def enabled_reason():
    return _ENABLED_REASON


def request(url, *, method="GET"):
    """Fetch one URL. (status, body_text_or_None, error_or_empty).

    Never raises for a transport failure: a survey of 45,000 URLs will hit
    timeouts and 5xxs, and a run that aborts on the first one produces no
    exhibit. The failure lands in the row's `note` column instead, which is
    where a reader can see how much of the survey actually completed.
    """
    if method != "GET":
        # Not a guard against a mistake — a guard against the tool acquiring a
        # write verb later and nobody noticing. See the module docstring.
        raise NetworkRefused(f"this tool performs GET only; refused {method}")
    if not ALLOW_NETWORK:
        raise NetworkRefused(
            "network access is off. survey.py runs --plan by default and "
            "prints what it would query; pass --collect to perform requests.")

    global _last_request
    import urllib.error          # deferred on purpose — see the docstring
    import urllib.request

    wait = MIN_INTERVAL_S - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    _last_request = time.monotonic()

    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.status, r.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as e:
        # An HTTP error is data: a 404 from the archive means no capture, and
        # that is a finding, not a failure.
        return e.code, None, f"HTTP {e.code}"
    except Exception as e:                       # timeout, DNS, TLS, reset
        return 0, None, f"{type(e).__name__}: {e}"[:120]
