"""The stale-data alert decides correctly and fails loudly, without a network.

Row 19a's fix is only as good as its decision line: an alert that fires a day
early trains the operator to delete it, one that fires late is the silence it
replaces. Everything network-shaped is stubbed; what is asserted is the
arithmetic, the threshold override, the recipient fallback, and that "cannot
check" is treated as a failure rather than a pass.

Run: python3 -m pytest pipeline/test_alert_stale_data.py -q
"""
from datetime import datetime, timezone

import pytest

import alert_stale_data as A
import refresh_pmms


NOW = datetime(2026, 8, 28, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def pmms_fresh(monkeypatch):
    """The PMMS leg runs first inside main(); pin it fresh so the market-data
    assertions below test one thing. Its own stale path has its own test."""
    monkeypatch.setattr(refresh_pmms, "check", lambda: 0)


def test_age_arithmetic_handles_both_iso_forms():
    assert A.days_old("2026-08-27T00:00:00Z", NOW) == 1
    assert A.days_old("2026-07-14T12:00:00+00:00", NOW) == 44
    # A naive timestamp (PostgREST can emit these) is read as UTC, not local.
    assert A.days_old("2026-08-14T00:00:00", NOW) == 14


def test_the_default_line_is_the_monthly_stall_alarm(monkeypatch):
    monkeypatch.delenv("STALE_ALERT_DAYS", raising=False)
    assert A.DEFAULT_STALE_DAYS == 45


def test_fresh_data_sends_nothing(monkeypatch):
    sent = []
    monkeypatch.setattr(A, "newest_retrieved_at", lambda: "2026-08-20T00:00:00Z")
    monkeypatch.setattr(A, "send", lambda *a: sent.append(a) or True)
    assert A.main([]) == 0
    assert not sent, "a fresh store must not email anyone"


def test_stale_data_alerts_and_the_threshold_is_overridable(monkeypatch):
    sent = []
    monkeypatch.setenv("STALE_ALERT_DAYS", "7")
    monkeypatch.setattr(A, "newest_retrieved_at", lambda: "2026-08-01T00:00:00Z")
    monkeypatch.setattr(A, "send", lambda subj, html: sent.append((subj, html)) or True)
    assert A.main([]) == 0
    assert len(sent) == 1
    assert "stale" in sent[0][0].lower()


def test_cannot_check_is_a_failure_not_a_pass(monkeypatch):
    """The query failing silently is the exact hole this file closes."""
    monkeypatch.setattr(A, "newest_retrieved_at", lambda: None)
    monkeypatch.setattr(A, "send", lambda *a: True)
    assert A.main([]) == 1


def test_a_failed_send_on_stale_data_exits_nonzero(monkeypatch):
    monkeypatch.setattr(A, "newest_retrieved_at", lambda: "2020-01-01T00:00:00Z")
    monkeypatch.setattr(A, "send", lambda *a: False)
    assert A.main([]) == 1


def test_recipient_fallback_is_a_real_mailbox(monkeypatch):
    """alerts@ was a sending identity, not a mailbox, and Resend suppressed it
    (match-request/index.ts tells that story). The fallback must receive."""
    monkeypatch.delenv("OPS_DIGEST_RECIPIENTS", raising=False)
    assert A.recipients() == ["hello@shouldisellyet.com"]
    monkeypatch.setenv("OPS_DIGEST_RECIPIENTS", "a@x.com, b@y.com")
    assert A.recipients() == ["a@x.com", "b@y.com"]


def test_a_stale_mortgage_rate_alerts_even_when_market_data_is_fresh(monkeypatch):
    """Item 7: the weekly PMMS refresh gets the same courtesy as the market
    store — a broken job emails, it doesn't wait to be noticed."""
    sent = []
    monkeypatch.setattr(refresh_pmms, "check", lambda: 1)
    monkeypatch.setattr(A, "newest_retrieved_at", lambda: "2026-08-27T00:00:00Z")
    monkeypatch.setattr(A, "send", lambda subj, html: sent.append(subj) or True)
    assert A.main([]) == 0
    assert len(sent) == 1 and "PMMS" in sent[0]


def test_the_test_mode_is_unmistakably_a_test(monkeypatch):
    sent = []
    monkeypatch.setattr(A, "send", lambda subj, html: sent.append((subj, html)) or True)
    assert A.main(["--test"]) == 0
    subj, html = sent[0]
    assert subj.startswith("[TEST]")
    assert "not being reported stale" in html
