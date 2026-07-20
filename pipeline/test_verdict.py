"""Unit tests for the verdict engine + pipeline parsing. Run: pytest -q"""

import gzip
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from verdict import ZipMetrics, evaluate

HERE = Path(__file__).parent


# ——— Engine ———

def test_healthy_market_is_green():
    v = evaluate(ZipMetrics("20874", months_of_supply=2.6,
                            median_sale_price_yoy=0.02, median_dom_yoy=0.38))
    assert v.level == "green" and v.word == "HOLD" and v.score == 0


def test_single_warning_is_yellow():
    v = evaluate(ZipMetrics("00001", months_of_supply=4.5,
                            median_sale_price_yoy=0.01))
    assert v.level == "yellow" and v.word == "WATCH"
    assert any(c == "supply_high" for c, _, _ in v.reasons)


def test_moderate_price_decline_is_yellow():
    v = evaluate(ZipMetrics("00002", months_of_supply=3.0,
                            median_sale_price_yoy=-0.03))
    assert v.level == "yellow"


def test_multiple_signals_is_red():
    v = evaluate(ZipMetrics("00003", months_of_supply=5.0,
                            median_sale_price_yoy=-0.06, price_drop_share=0.40))
    assert v.level == "red" and v.word == "ACT" and v.score >= 4


def test_severe_supply_alone_reaches_red_only_with_company():
    # 6.5 months alone = 3 points → still yellow; needs a second signal for red
    v = evaluate(ZipMetrics("00004", months_of_supply=6.5,
                            median_sale_price_yoy=0.0))
    assert v.level == "yellow"
    v2 = evaluate(ZipMetrics("00005", months_of_supply=6.5,
                             median_sale_price_yoy=0.0, inventory_yoy=0.6))
    assert v2.level == "red"


def test_insufficient_data_defaults_green_flagged():
    v = evaluate(ZipMetrics("00006", months_of_supply=9.9))
    assert v.level == "green"
    assert v.reasons[0][0] == "insufficient_data"


def test_20906_style_mix_shift_is_yellow_not_red():
    # Headline price down 7% but nothing else tripped → yellow (mix-shift case)
    v = evaluate(ZipMetrics("20906", months_of_supply=2.8,
                            median_sale_price_yoy=-0.072,
                            price_drop_share=0.22, median_dom_yoy=0.26))
    assert v.level == "yellow"


def test_dom_yoy_is_days_not_fraction():
    """Regression: Redfin MEDIAN_DOM_YOY is days (found in production: 46 dom, +12 days)."""
    # 34 → 46 days = +35% — should NOT flag
    v = evaluate(ZipMetrics("20906", months_of_supply=1.0,
                            median_sale_price_yoy=-0.071,
                            median_dom=46.0, median_dom_yoy=12.0))
    assert not any(c == "dom_stretching" for c, _, _ in v.reasons)
    assert v.level == "yellow"          # price alone = 3 points
    # 30 → 50 days = +67% — SHOULD flag
    v2 = evaluate(ZipMetrics("00007", months_of_supply=1.0,
                             median_sale_price_yoy=0.0,
                             median_dom=50.0, median_dom_yoy=20.0))
    assert any(c == "dom_stretching" for c, _, _ in v2.reasons)


def test_uppercase_headers_like_real_redfin_file(tmp_path):
    """Regression: Redfin ships UPPERCASE column names (found in production)."""
    import fetch_data
    header = ("PERIOD_BEGIN\tPERIOD_END\tREGION\tSTATE_CODE\tIS_SEASONALLY_ADJUSTED\t"
              "PROPERTY_TYPE\tMEDIAN_SALE_PRICE_YOY\tHOMES_SOLD\tINVENTORY\t"
              "INVENTORY_YOY\tMONTHS_OF_SUPPLY\tMEDIAN_DOM\tMEDIAN_DOM_YOY\tPRICE_DROPS\n")
    rows = ("2026-05-01\t2026-05-31\tZip Code: 60616\tIL\tfalse\tAll Residential\t"
            "0.01\t40\t120\t0.1\t3.0\t30\t0.05\t0.2\n"
            # seasonally adjusted duplicate must be ignored
            "2026-05-01\t2026-05-31\tZip Code: 60616\tIL\ttrue\tAll Residential\t"
            "0.99\t40\t120\t0.1\t9.9\t30\t0.05\t0.2\n"
            # non-residential property type must be ignored
            "2026-05-01\t2026-05-31\tZip Code: 60616\tIL\tfalse\tTownhouse\t"
            "0.99\t40\t120\t0.1\t9.9\t30\t0.05\t0.2\n")
    f = tmp_path / "upper.tsv"
    f.write_text(header + rows)
    best = fetch_data.latest_by_zip(fetch_data.load_rows(str(f)))
    assert list(best) == ["60616"]
    m = fetch_data.row_to_metrics("60616", *best["60616"][0:2], best["60616"][2])
    assert m.months_of_supply == 3.0 and m.state == "IL"


# ——— Pipeline on fixture TSV ———

FIXTURE_HEADER = (
    "period_begin\tperiod_end\tregion\tstate_code\tproperty_type\t"
    "median_sale_price\tmedian_sale_price_yoy\thomes_sold\tinventory\t"
    "inventory_yoy\tmonths_of_supply\tmedian_dom\tmedian_dom_yoy\tprice_drops\n"
)
FIXTURE_ROWS = (
    # healthy ZIP, two periods (newest must win)
    "2026-04-01\t2026-04-30\tZip Code: 20874\tMD\tAll Residential\t455000\t0.01\t50\t130\t0.2\t2.6\t23\t0.1\t0.25\n"
    "2026-05-01\t2026-05-31\tZip Code: 20874\tMD\tAll Residential\t465000\t0.02\t55\t140\t0.2\t2.5\t23\t0.1\t0.25\n"
    # distressed ZIP
    "2026-05-01\t2026-05-31\tZip Code: 99901\tAK\tAll Residential\t300000\t-0.08\t10\t60\t0.7\t6.0\t80\t0.6\t0.45\n"
    # junk row (bad zip) should be skipped
    "2026-05-01\t2026-05-31\tZip Code: ABCDE\tMD\tAll Residential\t1\t\t\t\t\t\t\t\t\n"
)


def test_pipeline_end_to_end(tmp_path):
    fixture = tmp_path / "fixture.tsv.gz"
    with gzip.open(fixture, "wt") as f:
        f.write(FIXTURE_HEADER + FIXTURE_ROWS)

    # run pipeline against fixture, writing into a temp copy of the repo layout
    repo = tmp_path / "repo"
    (repo / "pipeline").mkdir(parents=True)
    for name in ("fetch_data.py", "verdict.py"):
        (repo / "pipeline" / name).write_text((HERE / name).read_text())

    subprocess.run(
        [sys.executable, str(repo / "pipeline" / "fetch_data.py"),
         "--input", str(fixture)],
        check=True, capture_output=True,
    )

    data_dir = repo / "web" / "data"
    index = json.loads((data_dir / "index.json").read_text())
    assert index["208"] == "MD" and index["999"] == "AK"

    md = json.loads((data_dir / "zips" / "MD.json").read_text())
    assert md["20874"]["l"] == "green"
    assert md["20874"]["m"]["spy"] == 0.02          # newest period won

    ak = json.loads((data_dir / "zips" / "AK.json").read_text())
    assert ak["99901"]["l"] == "red"

    meta = json.loads((data_dir / "meta.json").read_text())
    assert meta["period"] == "2026-05"
    assert "Redfin" in meta["attribution"]
