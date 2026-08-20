"""Phase 4 — the tranche allowlist, and the trap it exists to avoid.

Releasing a ZIP is two conditions, not one. An allowlist that only asked "is
this ZIP in tranche 1?" would republish the vendor numbers Phase 0 took off
~23,000 pages, because the entries in web/data/zips are still Redfin-derived
and a released ZIP renders whatever its entry holds. Most of this file is
that second condition.

Run: python3 -m pytest pipeline/test_tranches.py -q
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import data_pause as PAUSE
import promote_tranche as PT

NEW = PAUSE.RELEASED_BASIS
OLD = PAUSE.LEGACY_BASIS


@pytest.fixture(autouse=True)
def clear_cache():
    PAUSE._allowlist = None
    yield
    PAUSE._allowlist = None


def tranche_file(tmp_path, zips, released=True, name="tranche-1"):
    p = tmp_path / "tranches.json"
    p.write_text(json.dumps({"tranches": [
        {"name": name, "released_utc": "2026-08-20T00:00:00Z" if released else None,
         "zips": zips}]}))
    return p


# ————— the allowlist —————

def test_missing_file_releases_nothing(tmp_path):
    """The safe default. A missing or unreadable ledger must pause
    everything, never publish everything."""
    assert PAUSE.released_zips(tmp_path / "absent.json") == set()


def test_unreadable_file_releases_nothing(tmp_path):
    p = tmp_path / "tranches.json"
    p.write_text("{ not json")
    assert PAUSE.released_zips(p) == set()


def test_staged_but_unreleased_tranche_is_not_live(tmp_path):
    """Staging writes the list; only released_utc makes it real."""
    p = tranche_file(tmp_path, ["20874"], released=False)
    assert PAUSE.released_zips(p) == set()


def test_released_tranche_is_live(tmp_path):
    p = tranche_file(tmp_path, ["20874", "20906"])
    assert PAUSE.released_zips(p) == {"20874", "20906"}


# ————— the two conditions —————

def test_unreleased_zip_shows_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(PAUSE, "TRANCHES", tranche_file(tmp_path, ["20874"]))
    assert PAUSE.shows_data("99999", NEW) is False


def test_released_zip_with_a_new_basis_shows_data(tmp_path, monkeypatch):
    monkeypatch.setattr(PAUSE, "TRANCHES", tranche_file(tmp_path, ["20874"]))
    assert PAUSE.shows_data("20874", NEW) is True


def test_released_zip_with_a_legacy_reading_stays_dark(tmp_path, monkeypatch):
    """THE TRAP. This ZIP is in a released tranche, but its reading is still
    the withdrawn vendor's. Publishing it would undo Phase 0."""
    monkeypatch.setattr(PAUSE, "TRANCHES", tranche_file(tmp_path, ["20874"]))
    assert PAUSE.shows_data("20874", OLD) is False
    assert PAUSE.wrongly_promoted("20874", OLD) is True


def test_wrongly_promoted_is_false_for_a_correct_release(tmp_path, monkeypatch):
    monkeypatch.setattr(PAUSE, "TRANCHES", tranche_file(tmp_path, ["20874"]))
    assert PAUSE.wrongly_promoted("20874", NEW) is False


def test_wrongly_promoted_is_false_for_an_unreleased_zip(tmp_path, monkeypatch):
    """An unreleased legacy ZIP is the normal paused state, not a mistake."""
    monkeypatch.setattr(PAUSE, "TRANCHES", tranche_file(tmp_path, ["20874"]))
    assert PAUSE.wrongly_promoted("99999", OLD) is False


def test_callers_passing_no_basis_get_the_allowlist_check_alone(tmp_path, monkeypatch):
    """Surfaces deciding layout rather than rendering a number."""
    monkeypatch.setattr(PAUSE, "TRANCHES", tranche_file(tmp_path, ["20874"]))
    assert PAUSE.shows_data("20874") is True
    assert PAUSE.shows_data() is False


# ————— noindex follows the release —————

def test_noindex_is_dropped_only_for_released_zips(tmp_path, monkeypatch):
    monkeypatch.setattr(PAUSE, "TRANCHES", tranche_file(tmp_path, ["20874"]))
    assert PAUSE.robots_meta("20874") == ""
    assert "noindex" in PAUSE.robots_meta("99999")
    assert "noindex" in PAUSE.robots_meta()      # global surfaces unchanged


# ————— the promotion tool —————

def test_promotion_refuses_a_zip_with_no_v2_reading():
    eligible, blocked = PT.partition(["11111"], {"11111": OLD}, set())
    assert eligible == [] and "legacy" in blocked["11111"]


def test_promotion_accepts_a_zip_with_a_v2_reading():
    eligible, blocked = PT.partition(["11111"], {"11111": NEW}, set())
    assert eligible == ["11111"] and blocked == {}


def test_promotion_refuses_a_zip_with_no_reading_at_all():
    eligible, blocked = PT.partition(["11111"], {}, set())
    assert eligible == [] and blocked["11111"] == "no reading at all"


def test_promotion_never_double_stages_a_zip():
    eligible, blocked = PT.partition(["11111"], {"11111": NEW}, {"11111"})
    assert eligible == [] and "already" in blocked["11111"]


def test_release_requires_an_existing_tranche(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"tranches": []}))
    with pytest.raises(SystemExit, match="stage it first"):
        PT.main(["--name", "tranche-1", "--release", "--file", str(f)])


def test_release_refuses_an_empty_tranche(tmp_path):
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"tranches": [{"name": "t1", "zips": []}]}))
    with pytest.raises(SystemExit, match="empty"):
        PT.main(["--name", "t1", "--release", "--file", str(f)])


def test_staging_then_releasing_is_two_steps(tmp_path, monkeypatch, capsys):
    """Staging changes nothing on the site; the release stamp is the only
    thing data_pause reads."""
    zips_dir = tmp_path / "zips"
    zips_dir.mkdir()
    (zips_dir / "MD.json").write_text(json.dumps({"20874": {"l": "red", "b": NEW}}))
    tiers = tmp_path / "tier.csv"
    tiers.write_text("rank,tier,zip\n1,A,20874\n")
    f = tmp_path / "t.json"

    assert PT.main(["--name", "t1", "--tier", "A", "--file", str(f),
                    "--zips", str(zips_dir), "--tiers-file", str(tiers)]) == 0
    assert PAUSE.released_zips(f) == set()          # staged, not live

    assert PT.main(["--name", "t1", "--release", "--file", str(f)]) == 0
    assert PAUSE.released_zips(f) == {"20874"}


def test_staging_a_legacy_only_tier_stages_nothing_and_says_why(tmp_path, monkeypatch, capsys):
    """The expected state before acquisition has run."""
    zips_dir = tmp_path / "zips"
    zips_dir.mkdir()
    (zips_dir / "MD.json").write_text(json.dumps({"20874": {"l": "red"}}))
    tiers = tmp_path / "tier.csv"
    tiers.write_text("rank,tier,zip\n1,A,20874\n")
    code = PT.main(["--name", "t1", "--tier", "A", "--file", str(tmp_path / "t.json"),
                    "--zips", str(zips_dir), "--tiers-file", str(tiers)])
    assert code == 1
    assert "republish the numbers Phase 0 withdrew" in capsys.readouterr().out


def test_the_shipped_tranches_file_is_internally_coherent():
    """Was: the shipped file releases nothing.

    True until 2026-08-20 and worth having until then; it asserts a moment,
    not a rule, so it expired the moment tranche-1 was released. What is worth
    guarding permanently is that the file cannot say two things at once — a
    released tranche must carry a stamp, a basis, and ZIPs that look like ZIPs,
    and released_zips() must agree with the entries it was derived from.
    """
    import json
    doc = json.loads(Path(PAUSE.TRANCHES).read_text())
    assert doc.get("basis") == PAUSE.RELEASED_BASIS

    expected = set()
    for t in doc.get("tranches", []):
        assert t.get("name"), "a tranche with no name cannot be released by name"
        assert t.get("zips"), f"{t.get('name')}: staged with no ZIPs"
        assert all(str(z).isdigit() and len(str(z)) == 5 for z in t["zips"]), \
            f"{t['name']}: a ZIP that is not five digits"
        assert len(set(t["zips"])) == len(t["zips"]), f"{t['name']}: duplicate ZIPs"
        if t.get("released_utc"):
            assert t.get("basis") == PAUSE.RELEASED_BASIS, \
                f"{t['name']}: released on a basis the site does not publish"
            expected |= {str(z) for z in t["zips"]}

    assert PAUSE.released_zips(PAUSE.TRANCHES) == expected, \
        "released_zips() disagrees with the stamped entries it reads"
