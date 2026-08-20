"""The rebuilt paid-call ranking.

rank_interim.py excluded a ZIP from ever being bought if Realtor.com did not
carry it or had flagged it. That dropped 20874 Germantown MD (14,842
owner-occupied homes, a standing page, an FHFA index, everything else passing)
and 20906 Silver Spring — the ZIP the site's own sample report is written
about. Its neighbour 20878 ranked 170th. Nationally the gate cost 8,529 ZIPs.

This ranks from committed public-domain inputs only, which is also why it still
runs: rank_interim's Redfin-era inputs were withdrawn and it now refuses to
start.

Run: python3 -m pytest pipeline/test_rank_v2.py -q
"""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import rank_v2 as R

ROOT = Path(__file__).resolve().parents[1]


def _rows():
    p = ROOT / "pipeline" / "tier_v2.csv"
    if not p.exists():
        pytest.skip("tier_v2.csv not built")
    return list(csv.DictReader(open(p, encoding="utf-8")))


def test_it_reads_no_vendor_data():
    """The whole point. A ranking that consumes a vendor's coverage inherits
    that vendor's blind spots, and this one decides real spend."""
    # Parse it rather than grepping it. The module docstring names all three
    # vendors on purpose — it exists to explain which gates were removed and
    # why — so a text search finds them and proves nothing. What matters is
    # whether any of them appears in code that runs.
    import ast
    tree = ast.parse((ROOT / "pipeline" / "rank_v2.py").read_text())
    tree.body = [n for n in tree.body
                 if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                         and isinstance(n.value.value, str))]
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                node.body = node.body[1:] or [ast.Pass()]
    code = ast.unparse(ast.fix_missing_locations(tree)).lower()
    for vendor in ("rdc", "realtor", "redfin", "rentcast"):
        assert vendor not in code, f"the ranking reads {vendor} data"
    # and it only opens files that are committed
    for name in ("page_manifest.csv", "acs_zip.csv", "fhfa_zip.csv", "zip_places.csv"):
        assert (ROOT / "pipeline" / "data" / name).exists() or \
               (ROOT / "pipeline" / name).exists(), f"{name} is not committed"


def test_the_zips_the_realtor_gate_excluded_are_ranked_now():
    by_zip = {r["zip"]: r for r in _rows()}
    for z, place in (("20874", "Germantown MD"), ("20906", "Silver Spring MD")):
        assert z in by_zip, f"{z} ({place}) is still unranked"
        assert by_zip[z]["tier"] == "A", \
            f"{z} ranks {by_zip[z]['rank']} — expected tier A on owner-occupied homes"


def test_nothing_already_bought_fell_out_of_the_ranking():
    """Re-ranking must not orphan a ZIP that has been paid for."""
    acq = ROOT / "pipeline" / "tier_interim.csv"
    bought_tiers = {r["zip"] for r in csv.DictReader(open(acq, encoding="utf-8"))
                    if r["tier"] in ("A", "B")}
    ranked = {r["zip"] for r in _rows()}
    orphaned = bought_tiers - ranked
    assert not orphaned, \
        f"{len(orphaned)} purchased ZIP(s) are no longer ranked: {sorted(orphaned)[:5]}"


def test_the_ordering_is_deterministic_and_needs_no_vendor():
    rows = _rows()
    keys = [(-int(r["owner"]), -int(r["units"]), r["zip"]) for r in rows]
    assert keys == sorted(keys), "the file is not in its own sort order"
    assert [int(r["rank"]) for r in rows] == list(range(1, len(rows) + 1))


def test_fhfa_is_recorded_but_never_gated_on():
    """The old ranking dropped 1,856 ZIPs for lacking a price anchor — a fair
    argument about where to spend the FIRST dollars, and a poor one for
    excluding a market permanently."""
    rows = _rows()
    assert any(r["has_fhfa"] == "0" for r in rows), \
        "no ZIP without an FHFA index survived — it is being gated on"
    src = (ROOT / "pipeline" / "rank_v2.py").read_text()
    assert "no_fhfa" not in src.split('"""')[2], "no_fhfa is back as a gate"


def test_it_refuses_to_write_an_empty_ranking(tmp_path):
    out = tmp_path / "tier.csv"
    out.write_text("rank,tier,zip\n1,A,20601\n", encoding="utf-8")
    empty = tmp_path / "manifest.csv"
    empty.write_text("zip,state,page\n", encoding="utf-8")
    with pytest.raises(SystemExit):
        R.build(R.load_manifest(empty), {}, set(), set())
    assert out.read_text(encoding="utf-8") == "rank,tier,zip\n1,A,20601\n"


def test_the_acquisition_record_does_not_move_with_the_ranking():
    """market_jobs.tier records what a ZIP was bought AS. job_rows() rebuilds
    every row from the ledger, so pointing it at a regenerated ranking would
    rewrite the history the column exists to keep."""
    src = (ROOT / "pipeline" / "load_market_stats.py").read_text()
    assert "ACQUIRED_TIERS" in src and "tier_interim.csv" in src, \
        "the acquisition record follows the current ranking"
