"""What a provisioned record may contain, and the surface list that governs.

Run: python3 -m pytest pipeline/test_provisioning.py -q
"""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import provision_readings as PR
from build_manifest import read_manifest
from surfaces import SURFACES

ROOT = Path(__file__).resolve().parents[1]


def test_records_are_written_one_file_per_zip():
    """A state file made the browser download every record in the state to
    show one — 1,475 for California. Per-ZIP files end that, and a 404 is how
    the client learns a ZIP is not covered."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        PR.write(PR.build([("20814", "MD"), ("90210", "CA")], {}), d)
        names = sorted(p.name for p in Path(d).iterdir())
        assert names == ["20814.json", "90210.json"], names
        assert json.loads((Path(d) / "20814.json").read_text()) == {"st": "MD"}


def test_switching_shapes_clears_the_old_state_files():
    """The state shards were a public bulk endpoint. Leaving one behind after
    the switch would keep serving it."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "MD.json").write_text('{"20814":{"st":"MD","l":"red"}}')
        PR.write(PR.build([("20814", "MD")], {}), d)
        assert not (Path(d) / "MD.json").exists(), "a stale state shard survived"


def test_unreleased_records_carry_only_a_state():
    """The bulk file at /data/zips/{ST}.json ships in the artifact and is
    fetched by the browser, so it is a published surface whether or not any
    page links it. Before the quarantine it carried 33,426 records of vendor
    metrics plus 36 months of history."""
    by_state = PR.build(read_manifest(), {})
    keys = {k for recs in by_state.values() for r in recs.values() for k in r}
    assert keys == {"st"}, f"an unreleased record carries more than a state: {keys}"


def test_a_released_record_carries_its_reading_and_nothing_raw():
    reading = {"l": "red", "s": 3, "r": [], "b": "active listings",
               "m": {"spy": -0.07, "dom": 52.0}, "h": {"s": "2025-09", "p": [1], "d": [1]}}
    by_state = PR.build([("20601", "MD")], {"20601": reading})
    rec = by_state["MD"]["20601"]
    assert rec["l"] == "red" and rec["st"] == "MD"
    assert "raw_json" not in rec and "raw" not in rec


def test_every_manifest_row_gets_a_record():
    """Fewer records than manifest rows means fewer pages, and generated
    directories are rebuilt each deploy — so that deletes live URLs."""
    manifest = read_manifest()
    by_state = PR.build(manifest, {})
    assert sum(len(v) for v in by_state.values()) == len(manifest)


# ————— the meta-test —————

def test_every_surface_maps_to_a_test_that_exists():
    """The list in surfaces.py is the enumeration that makes forgetting a
    surface a build failure rather than a discovery. An entry whose test does
    not exist is worse than no entry: it reads as covered."""
    for surface, kind, ref in SURFACES:
        assert kind in ("page", "artifact", "runtime"), f"{surface}: bad kind {kind}"
        path, _, func = ref.partition("::")
        target = ROOT / path if path.startswith("scripts/") else ROOT / "pipeline" / path
        assert target.exists(), f"{surface}: {path} does not exist"
        if func:
            assert f"def {func}(" in target.read_text(), \
                f"{surface}: {path} has no {func}"


def test_the_runtime_surfaces_are_checked_by_the_browser_smoke():
    """A runtime surface cannot be asserted from static output — that is what
    makes it runtime. Nine surfaces were found by hand; the one that only
    failed when the page RAN was invisible to every other gate."""
    smoke = (ROOT / "scripts" / "smoke-browser.mjs").read_text()
    runtime = [s for s, kind, _ in SURFACES if kind == "runtime"]
    assert runtime, "no runtime surfaces listed — the crash class is unguarded"
    assert "zip lookup renders an answer" in smoke
    assert "pageerror" in smoke, "uncaught exceptions must be captured"


def test_the_browser_smoke_runs_before_the_artifact_is_uploaded():
    wf = (ROOT / ".github" / "workflows" / "update.yml").read_text()
    assert "Browser smoke test" in wf, "the browser gate is not wired into CI"
    assert wf.index("Browser smoke test") < wf.index("Upload site"), \
        "a browser failure must block the upload, not follow it"


def test_writing_elsewhere_does_not_touch_the_real_private_records(tmp_path):
    """A default argument pointing at shared state is a landmine.

    write(by_state, out=tmp) used to leave build_out at its repo-root default,
    so every test that wrote records rmtree'd the private set the build reads
    from. In CI — provision, then pytest, then build — that turned 5,000
    released pages dark while every test passed.
    """
    import provision_readings as PR
    real = PR.BUILD
    before = sorted(p.name for p in real.glob("*.json")) if real.is_dir() else None
    PR.write(PR.build([("20814", "MD")], {}), tmp_path / "pub")
    after = sorted(p.name for p in real.glob("*.json")) if real.is_dir() else None
    assert after == before, "writing to a temp directory disturbed the real records"
    assert (tmp_path / "_private_readings" / "20814.json").exists(), \
        "the private set did not follow the public one"
