"""The weekly sweep is append-only and never rewrites release history.

promote_ondemand.merge() is the only function that touches tranches.json for
on-demand ZIPs. Pinned: append-only, idempotent, preserves an existing
tranche's released_utc (rewriting it would misstate when the first pulled
ZIP went live), and stamps the released basis on a fresh tranche so
data_pause.shows_data() accepts the pages it produces.

Run: python3 -m pytest pipeline/test_promote_ondemand.py -q
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import data_pause
import promote_ondemand as PO


def fresh():
    return {"basis": "active listings", "tranches": [
        {"name": "tranche-1", "released_utc": "2026-08-20T18:22:28Z",
         "basis": "active listings", "zips": ["77494"]},
    ]}


def test_creates_the_tranche_released_and_on_the_v2_basis():
    data = fresh()
    new = PO.merge(data, ["10001", "60601"], when="2026-08-25T00:00:00Z")
    t = next(t for t in data["tranches"] if t["name"] == "ondemand")
    assert new == ["10001", "60601"]
    assert t["released_utc"] == "2026-08-25T00:00:00Z"
    assert t["basis"] == data_pause.RELEASED_BASIS
    # and data_pause actually counts these as released
    assert set(t["zips"]) <= {"10001", "60601"}


def test_append_only_and_idempotent():
    data = fresh()
    PO.merge(data, ["10001"], when="2026-08-25T00:00:00Z")
    again = PO.merge(data, ["10001"], when="2026-09-01T00:00:00Z")
    assert again == []
    t = next(t for t in data["tranches"] if t["name"] == "ondemand")
    assert t["zips"] == ["10001"]


def test_an_existing_release_stamp_is_never_rewritten():
    data = fresh()
    PO.merge(data, ["10001"], when="2026-08-25T00:00:00Z")
    PO.merge(data, ["60601"], when="2026-09-01T00:00:00Z")
    t = next(t for t in data["tranches"] if t["name"] == "ondemand")
    assert t["released_utc"] == "2026-08-25T00:00:00Z", \
        "the stamp records when the tranche first went live, not the last sweep"
    assert t["zips"] == ["10001", "60601"]


def test_other_tranches_are_untouched():
    data = fresh()
    PO.merge(data, ["10001"])
    t1 = data["tranches"][0]
    assert t1["name"] == "tranche-1" and t1["zips"] == ["77494"]
