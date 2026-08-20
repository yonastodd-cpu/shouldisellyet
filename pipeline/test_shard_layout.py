"""Every reader of the removed per-state layout must fail loudly.

On 2026-08-20 provisioning moved from web/data/zips/{STATE}.json to
web/data/z/{zip}.json. Eleven scripts still read the old path. Path.glob() on
a missing directory yields nothing and does not raise, so each of them returned
zero records and carried on — and the test suite never noticed, because the
tests that exercise them BUILD THE OLD LAYOUT THEMSELVES in a tmp_path fixture.
A fixture that preserves a layout production has deleted keeps a dead code path
permanently green.

Three of the eleven then did something with the emptiness:
  build_manifest  wrote a 16-byte header over the 26,588-row page_manifest.csv
  research        overwrote four tracked files, one of them (streaks.json)
                  unrecoverable by its own comment
  promote_tranche reported all 1,000 Tranche 1 candidates as "no reading at
                  all", which is why the site could not be un-paused

Run: python3 -m pytest pipeline/test_shard_layout.py -q
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from shard_layout import require_shards

ROOT = Path(__file__).resolve().parents[1]

# (module, callable name, how to call it with a directory)
READERS = [
    ("research", "load_shard_levels", lambda d: (d.parent,)),
    ("velocity", "load_entries", lambda d: (d.parent,)),
    ("growth_digest", "load_current", lambda d: (d.parent,)),
    ("build_manifest", "load_entries", lambda d: (d,)),
    ("calibrate_v2", "load_entries", lambda d: (d,)),
]


def test_require_shards_raises_on_a_missing_directory(tmp_path):
    with pytest.raises(SystemExit) as e:
        require_shards(tmp_path / "gone", "x.y")
    msg = str(e.value)
    assert "REFUSING TO RUN" in msg
    assert "web/data/z" in msg, "the message should name the current layout"


def test_require_shards_allows_an_empty_but_present_directory(tmp_path):
    """Callers legitimately pass one to mean 'no data this run'. Refusing to
    WRITE empty output is a separate guard, at the write."""
    d = tmp_path / "zips"
    d.mkdir()
    assert require_shards(d, "x.y") == d


@pytest.mark.parametrize("mod,fn,args", READERS)
def test_every_legacy_reader_refuses_rather_than_returning_nothing(mod, fn, args, tmp_path):
    m = __import__(mod)
    with pytest.raises(SystemExit) as e:
        getattr(m, fn)(*args(tmp_path / "zips"))
    assert "REFUSING TO RUN" in str(e.value), f"{mod}.{fn} returned quietly"


def test_build_manifest_refuses_to_write_an_empty_manifest(tmp_path):
    """The guard above covers the way it broke; this covers every other way of
    arriving at zero rows. The committed manifest is the frozen population."""
    import build_manifest as BM
    d = tmp_path / "zips"
    d.mkdir()                      # present but empty — passes require_shards
    out = tmp_path / "manifest.csv"
    out.write_text("zip,state,page\n20601,MD,1\n", encoding="utf-8")
    with pytest.raises(SystemExit) as e:
        BM.main(["--zips", str(d), "--out", str(out)])
    assert "refusing to write" in str(e.value).lower()
    assert out.read_text(encoding="utf-8") == "zip,state,page\n20601,MD,1\n", \
        "the committed manifest was modified despite the refusal"


def test_no_script_still_silently_globs_the_removed_directory():
    """A new caller must not reintroduce the pattern. Any read of the legacy
    path has to sit behind require_shards."""
    import re
    reads = re.compile(r'Path\([^)]*,\s*"zips"\)|/\s*"zips"|["\']data/zips'
                       r'|os\.path\.join\([^)]*"zips"')
    # rank_interim raises its own bespoke SystemExit (it needs a message about
    # paid-API spend that this module should not carry); fetch_data WRITES the
    # legacy tree rather than reading it, and test_artifact_leaks asserts that
    # tree never reappears under web/.
    # Each exemption names the guard that actually protects it, so an
    # exemption cannot outlive its reason.
    EXEMPT = {
        "rank_interim.py": "REFUSING TO RUN",   # its own message, about API spend
        "fetch_data.py": "guard_fetch",         # a WRITER, not a reader: the pause
                                                # blocks the fetch, and
                                                # test_artifact_leaks asserts the
                                                # legacy tree never reappears
    }
    offenders = []
    for path in sorted((ROOT / "pipeline").glob("*.py")):
        if path.name.startswith("test_") or path.name == "shard_layout.py":
            continue
        if path.name in EXEMPT:
            marker = EXEMPT[path.name]
            assert marker in path.read_text(encoding="utf-8"), (
                f"{path.name} is exempt from require_shards because of "
                f"{marker!r}, which is no longer there")
            continue
        src = path.read_text(encoding="utf-8")
        code = "\n".join(l for l in src.split("\n") if not l.strip().startswith("#"))
        if not reads.search(code):
            continue
        if "require_shards" not in src:
            offenders.append(path.name)
    assert not offenders, (
        f"these read the removed per-state layout with no guard: {offenders}. "
        "Add require_shards(), or repoint them at web/data/z/.")


def test_promote_tranche_does_not_ask_the_public_artifact(tmp_path):
    """It used to decide what may be RELEASED by reading what was PUBLISHED —
    asking the output whether the input exists. An unreleased record is
    {"st": "XX"} by construction, so the answer was always no."""
    import promote_tranche as PT
    src = (ROOT / "pipeline" / "promote_tranche.py").read_text()
    assert 'ap.add_argument("--zips", default=None' in src, \
        "the default basis source points at files again"
    assert "from rescore_v2 import db_rows" in src, \
        "promote_tranche no longer reads the private store"
    # the fixture reader still accepts BOTH layouts
    per_zip = tmp_path / "z"
    per_zip.mkdir()
    (per_zip / "20874.json").write_text('{"l":"red","b":"active listings","st":"MD"}')
    assert PT._readings_from_files(per_zip) == {"20874": "active listings"}
    per_state = tmp_path / "zips"
    per_state.mkdir()
    (per_state / "MD.json").write_text('{"20874":{"l":"red","b":"active listings"}}')
    assert PT._readings_from_files(per_state) == {"20874": "active listings"}
