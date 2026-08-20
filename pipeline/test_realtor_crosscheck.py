"""The Realtor.com kill switch, exercised in both positions.

A switch nobody has flipped is a switch nobody knows works. These run the OFF
path as well as the ON path, because the whole point of building it before the
licence answer arrives is that flipping it later is not an experiment.

The requirement is absence, not concealment: when the switch is off no
Realtor-derived value may be fetched, written into web/, or credited to a
reader. Hiding the strip with CSS while the figures still ship inside the
per-ZIP record would satisfy a screenshot and nothing else.

Run: python3 -m pytest pipeline/test_realtor_crosscheck.py -q
"""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import realtor_crosscheck as RDC

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setattr(RDC, "SHOW", False)
    return RDC


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setattr(RDC, "SHOW", True)
    return RDC


def test_the_switch_defaults_to_on():
    """Current behaviour unchanged unless someone sets the variable."""
    import os
    assert "SHOW_REALTOR_CROSSCHECK" not in os.environ or RDC.SHOW in (True, False)
    src = (ROOT / "pipeline" / "realtor_crosscheck.py").read_text()
    assert 'os.environ.get("SHOW_REALTOR_CROSSCHECK", "1")' in src, \
        "the default is no longer ON"


@pytest.mark.parametrize("value,expected", [
    ("0", False), ("false", False), ("FALSE", False), ("off", False),
    ("no", False), ("", False),
    ("1", True), ("true", True), ("yes", True), ("anything", True),
])
def test_the_variable_is_read_the_way_a_human_would_write_it(value, expected, monkeypatch):
    monkeypatch.setenv("SHOW_REALTOR_CROSSCHECK", value)
    import importlib
    reloaded = importlib.reload(RDC)
    try:
        assert reloaded.SHOW is expected, f"{value!r} should mean {expected}"
    finally:
        monkeypatch.delenv("SHOW_REALTOR_CROSSCHECK", raising=False)
        importlib.reload(RDC)


def test_off_removes_the_crosscheck_from_a_public_record(off):
    rec = {"l": "green", "s": 0, "m": {"spy": 0.01}, "x": {"inv": 211, "dom": 38}, "st": "MD"}
    out = off.strip(rec)
    assert "x" not in out, "the cross-check still ships inside the record"
    assert out["l"] == "green" and out["st"] == "MD", "strip took more than it should"


def test_on_leaves_the_record_untouched(on):
    rec = {"l": "green", "x": {"inv": 211}, "st": "MD"}
    assert on.strip(rec) == rec


def test_off_removes_the_vendor_from_the_credit(off):
    for text in ("Data provided by Redfin · Listing data from Realtor.com® Economic Research · Place names",
                 "Data provided by Redfin · Listing data from Realtor.com&reg; Economic Research · Place names"):
        out = off.credit(text)
        assert "Realtor" not in out, f"credit still names the vendor: {out}"
        assert "Data provided by Redfin" in out and "Place names" in out, \
            "credit lost more than the Realtor clause"


def test_the_off_line_does_not_name_the_vendor():
    """A surface that has stopped showing a source should not still name it —
    the same rule data_pause applies to the paused market-data credit."""
    assert "Realtor" not in RDC.OFF_LINE
    assert RDC.OFF_LINE == "Independent cross-check temporarily unavailable."


# ————— the switch has to reach every producer and writer —————

def test_the_producer_is_gated_not_just_the_display():
    """Off means the Realtor download does not happen, so no request leaves
    this machine — not that it happens and the result is discarded."""
    src = (ROOT / "pipeline" / "fetch_data.py").read_text()
    assert "if (args.rdc and RDC.shows_crosscheck())" in src, \
        "fetch_data would still download Realtor data with the switch off"
    assert "rdc.get(zip_code) if RDC.shows_crosscheck() else None" in src, \
        "fetch_data would still attach the cross-check to a public record"


def test_the_writer_strips_anything_that_reaches_it():
    """provision_readings builds each record as {**reading, "st": state} —
    every key copied through unfiltered. A cross-check block that reached a
    reading would ship without anyone deciding to publish it."""
    src = (ROOT / "pipeline" / "provision_readings.py").read_text()
    assert "RDC.strip(" in src, "provisioning does not enforce the switch"


def test_every_shipped_credit_is_gated():
    """The research footer renders on the hub, the methodology page and every
    release; llms.txt is read by the crawlers robots.txt invites. Both ship on
    each deploy, so a credit left in either outlives one on a rendered page."""
    assert "CITE = RDC.credit(" in (ROOT / "pipeline" / "build_research.py").read_text(), \
        "the research footer credit is not gated"
    pages = (ROOT / "pipeline" / "build_pages.py").read_text()
    assert "if RDC.shows_crosscheck() else \"\"" in pages, \
        "the llms.txt credit is not gated"


def test_the_client_says_so_rather_than_vanishing():
    """Hiding the strip reads as a rendering bug and changes the page's shape.
    The switch is enforced server-side, so the client only ever sees absence."""
    js = (ROOT / "web" / "market-render.js").read_text()
    assert RDC.OFF_LINE in js, "the client has no quiet line to render"
    assert 'el.style.display = "none"; return;' not in js, \
        "the cross-check strip still vanishes silently"


def test_no_public_artifact_carries_a_realtor_figure_today():
    """Absence in the built artifact, not just in the code path."""
    z = ROOT / "web" / "data" / "z"
    if not z.is_dir():
        pytest.skip("per-ZIP records not built")
    offenders = [p.name for p in list(z.glob("*.json"))[:2000]
                 if '"x"' in p.read_text(encoding="utf-8")]
    assert not offenders, f"records ship a cross-check block: {offenders[:5]}"


def test_the_committed_tier_file_carries_no_vendor_column():
    """tier_interim.csv is committed and public, and its `listings` column was
    Realtor.com active_listing_count. Nothing reads it — fetch_rentcast and
    promote_tranche take only `zip` and `tier`, in row order."""
    header = (ROOT / "pipeline" / "tier_interim.csv").read_text().split("\n")[0]
    assert "listings" not in header, \
        "the public tier file still carries the Realtor-derived column"
    for needed in ("rank", "tier", "zip"):
        assert needed in header, f"the tier file lost {needed!r}"


def test_every_file_that_uses_the_switch_imports_it():
    """Wiring the switch into fetch_data.py, I added four RDC.* call sites and
    no import. Nothing caught it until the end-to-end test ran the module as a
    subprocess and it died on NameError — the unit tests never import that file
    at all, and a grep for the flag name found it 'wired' everywhere.
    """
    for path in sorted((ROOT / "pipeline").glob("*.py")):
        if path.name.startswith("test_") or path.name == "realtor_crosscheck.py":
            continue
        src = path.read_text(encoding="utf-8")
        if re.search(r"\bRDC\.", src):
            assert "import realtor_crosscheck as RDC" in src, (
                f"{path.name} calls RDC.* but never imports it — it will die "
                "with NameError the first time that line runs")
