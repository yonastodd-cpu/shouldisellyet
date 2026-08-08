"""Unit tests for the verdict engine + pipeline parsing. Run: pytest -q"""

import gzip
import os
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
    best, hist = fetch_data.latest_by_zip(fetch_data.load_rows(str(f)))
    assert list(best) == ["60616"]
    m = fetch_data.row_to_metrics("60616", *best["60616"][0:2], best["60616"][2])
    assert m.months_of_supply == 3.0 and m.state == "IL"


# ——— Strong seller's-market verdict ———

def test_strong_market_three_of_four_is_strong_act():
    # supply tight + prices surging + homes selling faster (price cuts unknown)
    v = evaluate(ZipMetrics("67208", months_of_supply=0.4,
                            median_sale_price_yoy=0.064,
                            median_dom=15.0, median_dom_yoy=-15.5))
    assert v.level == "strong" and v.word == "ACT"
    assert {c for c, _, _ in v.reasons} == {
        "supply_tight", "prices_surging", "homes_selling_fast"}


def test_strong_needs_at_least_three_signals():
    # only supply + prices met, DOM flat, cuts unknown → plain green
    v = evaluate(ZipMetrics("00010", months_of_supply=1.5,
                            median_sale_price_yoy=0.08,
                            median_dom=30.0, median_dom_yoy=0.0))
    assert v.level == "green" and v.word == "HOLD"


def test_any_danger_flag_beats_strong():
    # 36% price cuts = a 1-point danger flag → still green score 1, never strong,
    # even though supply/prices/DOM would all qualify as strong
    v = evaluate(ZipMetrics("00011", months_of_supply=1.0,
                            median_sale_price_yoy=0.10,
                            median_dom=20.0, median_dom_yoy=-10.0,
                            price_drop_share=0.36))
    assert v.level == "green" and v.score == 1
    assert any(c == "price_cuts_widespread" for c, _, _ in v.reasons)


def test_strong_with_price_cuts_signal_present():
    v = evaluate(ZipMetrics("00012", months_of_supply=2.0,
                            median_sale_price_yoy=0.06,
                            median_dom=40.0, median_dom_yoy=2.0,   # DOM not qualifying
                            price_drop_share=0.10))                # cuts qualifying
    assert v.level == "strong"


def test_strong_thresholds_are_exclusive_at_the_line():
    # exactly at the lines: mos 2.5 and pd 0.20 do NOT qualify; spy 0.05 does
    v = evaluate(ZipMetrics("00013", months_of_supply=2.5,
                            median_sale_price_yoy=0.05,
                            median_dom=30.0, median_dom_yoy=-1.0,
                            price_drop_share=0.20))
    assert v.level == "green"


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
        env={**os.environ, "SISY_SKIP_MORTGAGE": "1", "SISY_SKIP_RDC": "1",
             "SISY_SKIP_PD": "1"},  # no network in unit tests
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


# ——— mortgage-rate source parsers (fetch_data) ———

def test_mortgage_parsers_and_selection():
    import fetch_data as fd

    fred = "DATE,MORTGAGE30US\n" + "\n".join(
        f"2025-{m:02d}-01,{6.0 + m/100}" for m in range(1, 13)) + \
        "\n2026-01-01,.\n" + "\n".join(
        f"2026-{m:02d}-01,{6.5 + m/100}" for m in range(2, 8))
    vals = fd.parse_fred_csv(fred)
    assert all(v[1] > 0 for v in vals)
    assert not any(v[1] is None for v in vals)          # '.' rows dropped
    assert vals[-1][0] == "2026-07-01"

    pmms = "date,pmms30,pmms15\n" + "\n".join(
        f"{m}/2/2026,{6.6 + m/100},5.9" for m in range(1, 8))
    pvals = fd.parse_pmms_csv(pmms)
    assert pvals[-1] == ("2026-07-02", 6.67)
    assert pvals[0][0] == "2026-01-02"                  # M/D/YYYY → ISO

    # too-short series is rejected rather than trusted
    assert fd._rates_from_weekly(pvals) is None
    long = [(f"2025-{i:02d}", 6.0) for i in range(1, 10)] * 8
    r = fd._rates_from_weekly(long)
    assert r and set(r) == {"now", "year_ago", "asof"}


# ——— Realtor.com RDC cross-check loader ———

RDC_FIXTURE = """month_date_yyyymm,postal_code,zip_name,median_listing_price,median_listing_price_mm,median_listing_price_yy,active_listing_count,active_listing_count_mm,active_listing_count_yy,median_days_on_market,median_days_on_market_mm,median_days_on_market_yy,new_listing_count,new_listing_count_mm,new_listing_count_yy,price_increased_count,price_increased_count_mm,price_increased_count_yy,price_increased_share,price_increased_share_mm,price_increased_share_yy,price_reduced_count,price_reduced_count_mm,price_reduced_count_yy,price_reduced_share,price_reduced_share_mm,price_reduced_share_yy,pending_listing_count,pending_listing_count_mm,pending_listing_count_yy,median_listing_price_per_square_foot,median_listing_price_per_square_foot_mm,median_listing_price_per_square_foot_yy,median_square_feet,median_square_feet_mm,median_square_feet_yy,average_listing_price,average_listing_price_mm,average_listing_price_yy,total_listing_count,total_listing_count_mm,total_listing_count_yy,pending_ratio,pending_ratio_mm,pending_ratio_yy,quality_flag
202606,20874,"germantown, md",520000.0,0.01,0.03,119,0.02,0.05,33.0,0.1,-0.06,50,0.04,-0.07,4,0.0,,0.02,0.0,0.02,23.0,0.0,-0.09,0.147,0.04,-0.04,59.0,-0.08,0.31,610.0,-0.01,0.04,1712.0,0.0,-0.07,540000.0,0.02,-0.03,155,0.02,0.21,0.62,-0.07,0.09,0
202606,2138,"cambridge, ma",1200000.0,0.0,0.05,42,0.0,0.1,25.0,0.0,0.0,20,0.0,0.0,1,,,0.01,0.0,0.0,5.0,0.0,0.0,0.119,0.0,0.0,30.0,0.0,0.0,900.0,0.0,0.0,1500.0,0.0,0.0,1400000.0,0.0,0.0,70,0.0,0.0,0.7,0.0,0.0,0
202606,90210,"beverly hills, ca",5000000.0,0.0,0.0,200,0.0,0.0,60.0,0.0,0.0,80,0.0,0.0,2,,,0.01,0.0,0.0,50.0,0.0,0.0,0.25,0.0,0.0,40.0,0.0,0.0,2000.0,0.0,0.0,3000.0,0.0,0.0,6000000.0,0.0,0.0,260,0.0,0.0,0.2,0.0,0.0,1
"""


def test_load_rdc(tmp_path):
    import fetch_data as fd
    f = tmp_path / "rdc.csv"
    f.write_text(RDC_FIXTURE)
    out = fd.load_rdc(str(f))
    # quality_flag=1 row (90210) keeps counts, loses yy comparisons
    assert set(out) == {"20874", "02138", "90210"}
    q = out["90210"]
    assert q["q"] == 1 and q["inv"] == 200 and q["pdn"] == 50
    assert "domy" not in q and "invy" not in q
    e = out["20874"]
    assert e["p"] == "2026-06"
    assert e["inv"] == 119 and e["pdn"] == 23 and e["dom"] == 33
    assert e["pd"] == 0.147 and e["domy"] == -0.06     # yy fields stay fractions
    # leading-zero ZIP restored
    assert out["02138"]["inv"] == 42


def test_rdc_never_touches_verdict(tmp_path):
    """The cross-check is additive: entries gain `x` but l/s/r/m are
    byte-identical with and without the RDC feed."""
    import fetch_data as fd
    fixture = tmp_path / "fix.tsv.gz"
    with gzip.open(fixture, "wt") as f:
        f.write(FIXTURE_HEADER + FIXTURE_ROWS)
    rdcf = tmp_path / "rdc.csv"
    rdcf.write_text(RDC_FIXTURE)

    def run(rdc_arg, outdir):
        repo = tmp_path / outdir
        (repo / "pipeline").mkdir(parents=True)
        for name in ("fetch_data.py", "verdict.py"):
            (repo / "pipeline" / name).write_text((HERE / name).read_text())
        subprocess.run(
            [sys.executable, str(repo / "pipeline" / "fetch_data.py"),
             "--input", str(fixture), "--rdc", rdc_arg],
            check=True, capture_output=True,
            env={**os.environ, "SISY_SKIP_MORTGAGE": "1", "SISY_SKIP_PD": "1"},
        )
        return json.loads((repo / "web" / "data" / "zips" / "MD.json").read_text())

    with_rdc = run(str(rdcf), "repo_a")
    without = run("", "repo_b")
    assert "x" in with_rdc["20874"] and with_rdc["20874"]["x"]["inv"] == 119
    assert "x" not in without["20874"]
    for k in ("l", "s", "r", "m"):
        assert with_rdc["20874"][k] == without["20874"][k]


# ——— FHFA benchmark + backtest merge (fetch_data) ———

def test_load_fhfa_compact_and_backtest(tmp_path):
    import fetch_data as fd

    fhfa = tmp_path / "fhfa_zip.csv"
    fhfa.write_text("zip,thru,a1,a3\n20874,2023,8.89,9.56\nbadzip,x,y,z\n")
    bt = tmp_path / "backtest_results.json"
    bt.write_text(json.dumps({
        "redfin_years": [2012, 2026], "fhfa_thru": 2023, "n_pairs": 150000,
        "signals": {
            "mos": {"crossed": {"n": 900, "decline_pct": 41.0, "median_chg": 0.4},
                     "clear":   {"n": 90000, "decline_pct": 12.0, "median_chg": 5.1}},
            "cuts": {"crossed": None, "clear": {"n": 5, "decline_pct": 0.0, "median_chg": 4.0}},
        },
    }))
    out = fd.load_fhfa_compact(base=tmp_path)
    assert out == {"20874": {"y": 2023, "a1": 8.89, "a3": 9.56}}

    meta_bt = fd.load_backtest(base=tmp_path)
    assert meta_bt["y0"] == 2012 and meta_bt["fhfa"] == 2023
    assert meta_bt["sig"]["mos"] == {"x": 41.0, "c": 12.0, "n": 900}
    assert "cuts" not in meta_bt["sig"]  # one-sided data never ships


def test_verdict_copy_map_is_complete():
    """Every verdict level carries the full key set, including the qa answer.

    The ZIP-page generator formats vc["qa"] unconditionally (build_pages.py),
    so a level missing a key fails only at deploy time without this. The qa
    text must also agree with the level's own verdict word — the answer
    sentence and the FAQ answer land on the same page, and an engine lifting
    both must not read two different verdicts.
    """
    import json
    from pathlib import Path
    from verdict_copy import COPY, STATES

    required = {"word", "translation", "short", "emoji", "qa"}
    for level in STATES:
        assert level in COPY, f"verdict_copy.json missing level {level}"
        missing = required - set(COPY[level])
        assert not missing, f"{level} missing keys: {missing}"
        assert "{city}" in COPY[level]["qa"], f"{level}.qa lost its city placeholder"
        assert COPY[level]["word"] in COPY[level]["qa"], (
            f"{level}.qa never states its own verdict word "
            f"{COPY[level]['word']!r} — answer sentence and FAQ would disagree")
