"""The 2026-08-28 paid-report fixes: dial calibration, velocity lineage,
scenario/footnote agreement, the reconciliation line, and the distribution.

Source-level pins plus one real computation (write_distribution). Each test
names the defect behind it.

Run: python3 -m pytest pipeline/test_report_fixes.py -q
"""

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

ROOT = Path(__file__).resolve().parents[1]
REPORT = (ROOT / "web" / "my-report.html").read_text()
RENDER = (ROOT / "web" / "market-render.js").read_text()


# ————— item 3: the dials' ticks sit where the colors flip —————

def test_every_dial_tick_matches_its_fill_at_the_danger_value():
    """The tick (th) and the color flip must be the same value pushed through
    the same fill formula — the TIME ON MARKET tick was drawn at +40% y/y
    while the color flipped at +10%, so a dial could run amber with its dot
    still left of its own danger line."""
    checks = [
        # (danger value through fill formula, expected th, dial)
        ((4.0/8)*100, 50, "months of supply"),
        ((0.12-(-0.02))/0.24*100, 58.3, "prices y/y"),
        ((0.10*100+50)/150*100, 40, "time on market"),
        ((0.30*100+20)/120*100, 41.7, "new supply"),
        ((0.35/0.7)*100, 50, "price cuts"),
    ]
    for computed, coded, name in checks:
        assert abs(computed - coded) < 0.5, \
            f"{name}: danger value lands at {computed:.1f}% but th is {coded}"
    for th in ("th:strong?20:40", "th:41.7"):
        assert th in RENDER, f"corrected tick {th!r} missing from buildMetricRows"


def test_the_dials_survive_print_as_text():
    """PDF/print output must carry value + danger line + pass/fail even where
    backgrounds are stripped: the .pf restatement plus forced color-adjust."""
    assert 'class="pf"' in RENDER, "renderMetrics lost the print restatement"
    assert "print-color-adjust:exact" in REPORT
    assert ".metric .pf{display:block!important}" in REPORT


# ————— item 4: velocity computes from the record, asserts its lineage —————

def test_velocity_lines_mirror_the_spec():
    import verdict_v2
    m = re.search(r"VEL_LINES = \{[^}]*spy: \{ line: (-?[\d.]+)[^}]*\}[^}]*"
                  r"dom: \{ line: ([\d.]+)", REPORT, re.S)
    assert m, "VEL_LINES gone from my-report"
    assert float(m.group(1)) == verdict_v2.SPEC["price_slow"]
    assert float(m.group(2)) == verdict_v2.SPEC["dom_stretch"]


def test_the_rebuild_notice_is_gone_and_the_panel_computes():
    assert "being rebuilt on a new data source" not in REPORT, \
        "the rebuild notice outlived the rebuild"
    assert "velFromHistory" in REPORT and "velCalc" in REPORT


# ————— items 2 & 5: stress table honesty —————

def test_the_trend_row_no_longer_depends_on_the_trend_chart():
    """mom12 came from y12v, a side-effect of section 02's render — hide that
    section and the scenario silently vanished while the footnote went on
    describing it. Now it reads the record's history directly and the
    footnote is composed from the rows that actually rendered."""
    assert "mom12 = y12v" not in REPORT
    assert re.search(r"let mom12 = null;\s*\n\s*if \(h && h\.p\)", REPORT), \
        "the trend scenario no longer computes from the record's history"
    assert 'id="stress-foot"' in REPORT
    assert "$(\"stress-foot\").textContent" in REPORT, \
        "the stress footnote is static again — it must describe the rendered rows"


def test_the_reconciliation_line_exists_and_only_renders_on_divergence():
    assert 'id="reconcile"' in REPORT
    body = REPORT[REPORT.index("const lvl = d.l, rec = $(\"reconcile\")"):]
    body = body[:body.index("$(\"stress-test\").style.display")]
    assert "severe && margin > 0.25" in body
    assert "calm && margin < 0.10" in body
    assert 'rec.style.display = "none"' in body, \
        "the reconciliation line renders even when reading and cushion agree"


# ————— item 6: the live distribution —————

def test_write_distribution_computes_shares_and_quantiles(tmp_path):
    from provision_readings import write_distribution
    readings = {}
    for i in range(60):
        lvl = "green" if i < 40 else "yellow" if i < 55 else "red"
        readings[f"{10000+i}"] = {"l": lvl, "p": "2026-08",
                                  "m": {"spy": -0.06 + i*0.002, "dom": 60 + i,
                                        "domy": 5, "invy": -0.2 + i*0.01}}
    out = tmp_path / "distribution.json"
    write_distribution(readings, out)
    d = json.loads(out.read_text())
    assert d["n"] == 60 and d["period"] == "2026-08"
    assert d["counts"] == {"green": 40, "yellow": 15, "red": 5}
    assert len(d["q"]["spy"]) == 101
    assert d["q"]["spy"][0] <= d["q"]["spy"][50] <= d["q"]["spy"][100]
    # quantiles refuse a sample too thin to mean anything
    thin = {f"{20000+i}": {"l": "green", "m": {"spy": 0.01}} for i in range(5)}
    write_distribution(thin, out)
    assert json.loads(out.read_text())["q"]["spy"] is None


def test_the_context_box_reads_the_distribution_not_prior_deciles():
    assert "setDistribution" in RENDER and "distribution.json" in REPORT
    assert "spy_deciles" not in RENDER


# ————— item 7: the rate refresh —————

def test_the_pmms_workflow_and_check_exist():
    wf = (ROOT / ".github" / "workflows" / "pmms-weekly.yml").read_text()
    assert "refresh_pmms.py" in wf and "workflow run update.yml" in wf
    import refresh_pmms
    assert refresh_pmms.STALE_DAYS == 10
    alert = (ROOT / "pipeline" / "alert_stale_data.py").read_text()
    assert "refresh_pmms" in alert, \
        "a broken weekly rate refresh would go unnoticed — the alert must check it"


# ————— items 1 & 9: copy placement —————

def test_the_bottom_line_translates_rather_than_prescribes():
    """The gate owns the forbidden list; this pins the subtitle change and
    that the meanings survived de-prescription with their translations."""
    assert "One paragraph, plain English." in REPORT
    assert "One paragraph, no hedging." not in REPORT
    # Comment-stripped, same as the gate: a comment may quote the rule it
    # explains without becoming the violation it forbids.
    src = re.sub(r"<!--.*?-->", " ", REPORT, flags=re.S)
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"(?<!:)//[^\n]*", " ", src)
    for phrase in ("act on a plan now", "sooner beats later", "not next spring"):
        assert phrase not in src, f"prescriptive urgency back: {phrase!r}"


def test_the_upsell_sits_below_the_verdict_and_the_brand_is_defined():
    head = REPORT.index('id="r-head"')
    assert REPORT.index('id="upgrade-band"') > head, \
        "the upsell banner is above the verdict block again"
    assert "MyMarketCheckup</b> is our monitoring service" in REPORT, \
        "the brand's first mention lost its one-line definition"
