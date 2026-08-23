"""The research state moved out of the public repo; these guard the move.

levels-*.json published ~25,000 ZIP-to-rating pairs a month, about 20,000 of
them for markets whose own pages decline to state a rating, while the release
page said "We do not publish the list". They could not just be deleted: the next
month's build reads the prior month to count crossings.

The dangerous failure is not a crash. It is load_levels returning None, every
ZIP looking new, no ZIP looking like a crossing, and "0 ZIP markets moved" going
out as a published figure with no error anywhere.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

# The committed levels files are being removed: the store is the source of truth
# and CI reads it. Tests that exercise the FILE fallback therefore skip where the
# files are absent instead of failing. They are not deleted, because the fallback
# still runs on any machine that has them and must keep being covered there.
_LEVELS = ROOT / "pipeline" / "research" / "levels-2026-07.json"
needs_committed_levels = pytest.mark.skipif(
    not _LEVELS.exists(),
    reason="committed levels files are gone (moved to the private store); "
           "this test covers the file-fallback path")
sys.path.insert(0, str(ROOT / "pipeline"))

import research as RS            # noqa: E402
import research_store as store   # noqa: E402


class FakeStore(dict):
    """Stands in for the private store without a network."""
    def get(self, key):
        return dict.get(self, key)

    def put(self, key, payload):
        self[key] = payload
        return True


@pytest.fixture
def fake(monkeypatch):
    f = FakeStore()
    monkeypatch.setattr(store, "configured", lambda: True)
    monkeypatch.setattr(store, "get", f.get)
    monkeypatch.setattr(store, "put", f.put)
    return f


def test_a_missing_prior_month_raises_rather_than_reporting_zero():
    with pytest.raises(store.StateUnavailable) as e:
        RS.load_levels("2099-01")
    assert "zero flips" in str(e.value), \
        "the error must say WHY a miss is not survivable, or someone will catch it"


def test_the_first_month_may_legitimately_have_no_prior():
    assert RS.load_levels("2099-01", required=False) is None


def test_the_store_is_preferred_over_the_committed_file(fake):
    fake.put(store.levels_key("2026-07"), {"99999": "red"})
    got = RS.load_levels("2026-07")
    assert got == {"99999": "red"}, "the file won over the store"


@needs_committed_levels
def test_the_file_still_works_when_the_store_is_empty(fake):
    got = RS.load_levels("2026-07")
    assert got and len(got) > 20000, "fallback to the committed file broke"


def test_a_short_read_is_refused_rather_than_silently_used(monkeypatch):
    """`rows` exists so a truncated payload is caught without parsing it.

    PostgREST has already returned a large result short once in this project —
    977 of 1,000 readings. A half-delivered levels map would understate the
    flip count and nothing else would notice.
    """
    monkeypatch.setattr(store, "_creds", lambda: ("https://x", "k"))
    monkeypatch.setattr(store, "_request",
                        lambda *a, **k: [{"payload": {"1": "red"}, "rows": 25372}])
    with pytest.raises(store.StateUnavailable) as e:
        store.get("levels-2026-07")
    assert "short read" in str(e.value)


def test_no_credentials_means_no_store_and_no_crash(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert store.configured() is False
    assert store.get("anything") is None
    assert store.put("anything", {}) is False


def test_seeding_refuses_without_credentials(monkeypatch, capsys):
    monkeypatch.setattr(store, "configured", lambda: False)
    rc = RS.seed_store()
    assert rc != 0, "a seed that wrote nothing must not exit 0"
    assert "Do NOT remove the committed files" in capsys.readouterr().out


@needs_committed_levels
def test_seeding_verifies_by_reading_back(fake, capsys):
    rc = RS.seed_store()
    assert rc == 0
    out = capsys.readouterr().out
    assert "read back" in out
    assert store.get(store.levels_key("2026-07")) is not None


@needs_committed_levels
def test_seeding_fails_when_the_write_cannot_be_read(monkeypatch, capsys):
    """An RLS mistake would write happily and read nothing. That must not exit 0."""
    monkeypatch.setattr(store, "configured", lambda: True)
    monkeypatch.setattr(store, "put", lambda k, v: True)
    monkeypatch.setattr(store, "get", lambda k: None)
    rc = RS.seed_store()
    assert rc != 0
    assert "COULD NOT READ BACK" in capsys.readouterr().out


def test_writes_go_to_both_during_the_migration(fake, tmp_path, monkeypatch):
    monkeypatch.setattr(RS, "RESEARCH_DIR", tmp_path)
    RS.save_levels("2026-99", {"12345": "green"})
    assert fake.get(store.levels_key("2026-99")) == {"12345": "green"}, "store write missing"
    assert (tmp_path / "levels-2026-99.json").exists(), "file write missing"
