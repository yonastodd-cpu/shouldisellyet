"""FIGURES_KILL_SWITCH, server side: the copy of the flag that ships separately.

WHY THIS FILE IS SEPARATE FROM test_figures_switch.py. That file pins three
renderers that are all reached by a build — a Python module and two client
files the builders emit. This one pins a fourth copy that a build cannot reach
at all: supabase/functions/market-reading/index.ts runs on a server, deployed
on its own schedule, and served spy / dom / domy / inv / invy as named columns
to any browser while the static pages had already stopped drawing them. A flag
that reaches every surface except the live one is not a kill switch.

Two things are asserted here and they are different in kind:

  1. THE TWO LITERALS AGREE. Deno cannot import Python, so the flag is
     mirrored rather than shared, and a mirror nobody checks is how a switch
     gets flipped in three places out of four. Source-level, always runs.

  2. THE HANDLER ACTUALLY BEHAVES. Not "the file mentions the constant" —
     the endpoint's own request handler is executed in both states and its
     response body inspected. Source greps were what let the gap survive four
     audits: the endpoint never contained a vendor's name or a hard-coded
     number, and served every figure anyway.

HOW (2) IS POSSIBLE WITHOUT DENO. The handler is an ordinary function that
Deno.serve is handed. The harness below defines a Deno global, stubs fetch to
answer the three REST reads from fixtures, imports the function under Node's
type stripping, and calls the handler with a real Request. What this proves is
the handler's logic and its exact response bytes. What it does NOT prove is
anything about the Deno runtime itself, the deploy, or the CDN in front of it
— the cache note in index.ts is the honest statement of that last one.

Node runs .ts directly from 22.18 / 23.6 onward. Where it cannot, the
behavioural half skips with a reason and the source-level half still runs, so
an old runner degrades this file rather than silently passing it.

Run: python3 -m pytest pipeline/test_figures_switch_endpoint.py -q
"""

import json
import os
import re
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import figures_switch as FIG

ROOT = Path(__file__).resolve().parents[1]
FN = ROOT / "supabase" / "functions" / "market-reading" / "index.ts"
RATELIMIT = ROOT / "supabase" / "functions" / "_shared" / "ratelimit.ts"

# The literal as it must appear in the TypeScript. One pattern, used by every
# test here, so "the constant moved" is one failure rather than five.
DECL = re.compile(r"export\s+const\s+FIGURES_OFF\s*=\s*(true|false)\s*;")


# ————— fixtures the stubbed REST layer answers with —————
#
# One released ZIP with every figure populated — the worst case. The history
# is twelve ascending months because that is what market_history returns and
# because a twelve-point series IS the figure people forget.
FIXTURES = {
    "zip": "20601",
    "release": [{"zip": "20601", "basis": "active listings",
                 "released_at": "2026-08-20T00:00:00Z"}],
    "stats": [{"zip": "20601", "as_of_month": "2026-08",
               "retrieved_at": "2026-08-22T11:04:09Z",
               "list_median_price": 449900, "list_median_ppsf": 210.5,
               "active_dom": 57, "total_listings": 105,
               "new_listings": 33, "history_months": 12}],
    "history": [
        {"as_of_month": "2025-09", "median_list_price": 425000, "active_dom": 64, "total_listings": 66},
        {"as_of_month": "2025-10", "median_list_price": 435000, "active_dom": 57, "total_listings": 70},
        {"as_of_month": "2025-11", "median_list_price": 425000, "active_dom": 57, "total_listings": 74},
        {"as_of_month": "2025-12", "median_list_price": 415000, "active_dom": 61, "total_listings": 78},
        {"as_of_month": "2026-01", "median_list_price": 389000, "active_dom": 76, "total_listings": 81},
        {"as_of_month": "2026-02", "median_list_price": 389000, "active_dom": 81, "total_listings": 84},
        {"as_of_month": "2026-03", "median_list_price": 419000, "active_dom": 72, "total_listings": 88},
        {"as_of_month": "2026-04", "median_list_price": 455000, "active_dom": 64, "total_listings": 92},
        {"as_of_month": "2026-05", "median_list_price": 455000, "active_dom": 47, "total_listings": 95},
        {"as_of_month": "2026-06", "median_list_price": 420000, "active_dom": 42, "total_listings": 99},
        {"as_of_month": "2026-07", "median_list_price": 449900, "active_dom": 52, "total_listings": 102},
        {"as_of_month": "2026-08", "median_list_price": 449900, "active_dom": 57, "total_listings": 105},
    ],
}

# Every figure the fixtures can produce, as the response serialises it, plus
# the two selected columns the payload has never carried (ppsf, new listings).
# Substrings, because a leak that rounds differently is still a leak. None of
# these collides with a value that legitimately survives — zip, as-of month
# and retrieved-at timestamp — and test_the_leak_list_cannot_pass_by_accident
# is what keeps that true.
FIGURES = ("449900", "425000", "435000", "415000", "389000", "419000",
           "455000", "420000", "0.0585", "0.5909", "210.5", "33",
           "57", "105", "64", "76", "81", "72", "47", "42", "52", "-7",
           "61", "66", "70", "74", "78", "84", "88", "92", "95", "99", "102")

# The exact bytes this endpoint returned before the switch reached it,
# captured 2026-08-24 from the function as it then stood. Requirement: with
# the switch OFF the response must be byte-identical to that, because a
# contingency control that changes the resting behaviour is one nobody will
# leave installed. Compared as a string, not as parsed JSON: key ORDER and
# number FORMATTING are part of "identical", and both are things an innocent
# refactor moves.
GOLDEN_OFF_BODY = (
    '{"zip":"20601","state":null,"reading":null,"asOf":"2026-08",'
    '"lastUpdated":"2026-08-22T11:04:09Z",'
    '"metrics":{"spy":0.05858823529411765,"dom":57,"domy":-7,"inv":105,'
    '"invy":0.5909090909090909},'
    '"priceHistory":['
    '{"month":"2025-09","medianListPrice":425000,"daysOnMarket":64},'
    '{"month":"2025-10","medianListPrice":435000,"daysOnMarket":57},'
    '{"month":"2025-11","medianListPrice":425000,"daysOnMarket":57},'
    '{"month":"2025-12","medianListPrice":415000,"daysOnMarket":61},'
    '{"month":"2026-01","medianListPrice":389000,"daysOnMarket":76},'
    '{"month":"2026-02","medianListPrice":389000,"daysOnMarket":81},'
    '{"month":"2026-03","medianListPrice":419000,"daysOnMarket":72},'
    '{"month":"2026-04","medianListPrice":455000,"daysOnMarket":64},'
    '{"month":"2026-05","medianListPrice":455000,"daysOnMarket":47},'
    '{"month":"2026-06","medianListPrice":420000,"daysOnMarket":42},'
    '{"month":"2026-07","medianListPrice":449900,"daysOnMarket":52},'
    '{"month":"2026-08","medianListPrice":449900,"daysOnMarket":57}'
    '],'
    '"dataStatus":"ok"}'
)

CACHE_OFF = "public, max-age=86400, stale-while-revalidate=604800"

HARNESS = r"""
// Runs supabase/functions/market-reading's handler outside Deno.
//
// Always writes exactly one JSON line to stdout, including on failure, so the
// caller can tell "this environment cannot run TypeScript" (no stdout at all)
// from "the handler threw" (stdout with ok:false). A skip and a bug must not
// look alike.
const out = (o) => process.stdout.write(JSON.stringify(o) + "\n");

try {
  const FX = JSON.parse(process.env.SISY_FIXTURES);
  let handler = null;

  // The two globals the function and its rate limiter reach for. env values
  // are shaped like the real ones and point nowhere: every fetch is stubbed,
  // so a missed route fails loudly instead of leaving the machine.
  globalThis.Deno = {
    env: {
      get: (k) => ({
        SUPABASE_URL: "https://stub.invalid",
        SUPABASE_SERVICE_ROLE_KEY: "service-role-key-0123456789abcdef0123456789",
      }[k]),
    },
    serve: (h) => { handler = h; },
  };

  // Which tables were actually read. The switch is supposed to skip the
  // history query entirely, and "was it fetched" is not visible in the body.
  const queried = [];
  globalThis.fetch = async (url) => {
    const u = String(url);
    queried.push(u);
    const body =
      u.includes("rate_limit_hit") ? true :
      u.includes("zip_release") ? FX.release :
      u.includes("market_history") ? FX.history :
      u.includes("market_stats") ? FX.stats :
      null;
    if (body === null) throw new Error("no stub route for " + u);
    return new Response(JSON.stringify(body), {
      status: 200, headers: { "content-type": "application/json" },
    });
  };

  const mod = await import(process.env.SISY_MODULE);
  if (!handler) throw new Error("the module never called Deno.serve");

  const res = await handler(new Request(
    "https://stub.invalid/market-reading?zip=" + FX.zip,
    { headers: { origin: "https://shouldisellyet.com" } },
  ));
  out({
    ok: true,
    status: res.status,
    cacheControl: res.headers.get("cache-control"),
    body: await res.text(),
    figuresOff: mod.FIGURES_OFF,
    queried,
  });
} catch (e) {
  out({ ok: false, error: String((e && e.stack) || e) });
}
"""

PROBE_TS = "export const n: number = 1;\n"
PROBE_MJS = 'const m = await import("./probe.ts");\nprocess.stdout.write("ok" + m.n);\n'


@lru_cache(maxsize=1)
def _node_runs_typescript():
    """Can this machine execute the function at all? Probed with a trivial
    module rather than inferred from a version string, because the answer
    depends on the runtime's flags as much as its version."""
    import tempfile
    try:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "probe.ts").write_text(PROBE_TS)
            (Path(d) / "probe.mjs").write_text(PROBE_MJS)
            r = subprocess.run(["node", "probe.mjs"], cwd=d, timeout=60,
                               capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip() == "ok1":
            return None
        return f"node cannot run TypeScript here: {r.stderr.strip()[:200]}"
    except (OSError, subprocess.SubprocessError) as e:
        return f"node unavailable: {e}"


needs_node = pytest.mark.skipif(
    _node_runs_typescript() is not None,
    reason=_node_runs_typescript() or "",
)


def run_handler(tmp_path, figures_off):
    """Execute the real handler with the switch forced to `figures_off`.

    The flag is a literal in the source, so the ON state is produced by
    copying the file and rewriting that one declaration — the same move
    monkeypatching makes on the Python side. The copy is verified to have
    changed and the module's exported value is checked against what was asked
    for, because a rewrite that silently matched nothing would run the OFF
    build through every ON assertion and pass.
    """
    src = FN.read_text()
    # The import is relative to the function directory; the copy is not, so
    # point it at the real shared module by absolute URL (as_uri escapes the
    # space in the checkout path — a bare path here fails only on this
    # machine's directory layout, which is a miserable way to find out).
    src = src.replace('"../_shared/ratelimit.ts"', f'"{RATELIMIT.as_uri()}"')
    if figures_off:
        src, n = DECL.subn("export const FIGURES_OFF = true;", src)
        assert n == 1, "the switch declaration was not rewritten — see DECL"

    mod = tmp_path / ("fn_on.ts" if figures_off else "fn_off.ts")
    mod.write_text(src)
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS)

    env = dict(os.environ,
               SISY_FIXTURES=json.dumps(FIXTURES),
               SISY_MODULE=mod.as_uri())
    r = subprocess.run(["node", str(harness)], env=env, capture_output=True,
                       text=True, timeout=120)
    assert r.stdout.strip(), f"harness produced nothing: {r.stderr[-800:]}"
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res["ok"], res.get("error")
    assert res["figuresOff"] is figures_off, (
        f"asked for FIGURES_OFF={figures_off}, the module reports "
        f"{res['figuresOff']} — the harness tested the wrong build")
    return res


# ————— the two literals are one switch —————

def test_the_endpoint_declares_the_switch():
    """Not a comment about the switch — a declaration the handler can read.
    The file documented the Python flag's existence for weeks while doing
    nothing about it, which is the state this test exists to make impossible."""
    assert DECL.search(FN.read_text()), \
        "market-reading/index.ts has no FIGURES_OFF declaration"


def test_the_endpoint_and_the_python_flag_agree():
    """The mirror. Deno cannot import figures_switch.py and a build cannot
    reach a running server, so these two values can only be kept equal by
    hand — and by this."""
    m = DECL.search(FN.read_text())
    assert m, "no FIGURES_OFF declaration to compare"
    ts = m.group(1) == "true"
    assert ts == FIG.FIGURES_OFF, (
        f"market-reading/index.ts says FIGURES_OFF={m.group(1)} while "
        f"pipeline/figures_switch.py says {FIG.FIGURES_OFF} — the switch is "
        f"not one switch")


def test_the_python_module_admits_the_endpoint_is_a_mirror():
    """The docstring is the only place the pairing is explained to whoever
    flips this under pressure. It named the endpoint as OUT of reach; if it
    goes back to claiming reach without naming the deploy, the next person
    flips one flag and believes they are done."""
    doc = FIG.__doc__ or ""
    assert "market-reading" in doc, \
        "figures_switch.py no longer tells the reader the endpoint mirrors it"
    assert "deploy" in doc.lower(), \
        "the endpoint copy takes effect on a deploy and the docstring must say so"


def test_the_switch_is_never_answered_by_the_caller():
    """A query parameter that turns figures back on is not a kill switch. The
    only accepted parameter stays `zip`, and the flag is a literal rather than
    an environment read — the same reason figures_switch.py gives for its
    own."""
    src = FN.read_text()
    params = re.findall(r'searchParams\.get\("([^"]+)"\)', src)
    assert params == ["zip"], f"the only accepted parameter is zip, got {params}"
    m = DECL.search(src)
    assert "Deno.env" not in m.group(0), "the switch reads the environment"


def test_both_figure_paths_are_behind_the_switch():
    """Comments stripped first, so documenting the switch cannot be mistaken
    for honouring it — the trap test_threshold_disclosure hit when a note
    string passed for a threshold."""
    code = re.sub(r"//[^\n]*", "", FN.read_text())
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    assert re.search(r"function metricsFor[^{]*\{\s*return FIGURES_OFF \? \{\}", code), \
        "the metrics block is built without asking the switch"
    assert re.search(r"function series[^{]*\{\s*return FIGURES_OFF \? \[\]", code), \
        "the twelve-month series is built without asking the switch"
    assert re.search(r"const hist = FIGURES_OFF \? \[\] : await rest\(", code), \
        "the history is still fetched when its values may not be served"
    assert "metrics: metricsFor(" in code and "priceHistory: series(" in code, \
        "the response bypasses the guards it defines"


@pytest.mark.skipif(FIG.FIGURES_OFF,
                    reason="the switch is on — this checks the resting state")
def test_the_resting_state_is_the_switch_off():
    """Someone must be able to deploy this and see no difference. Skipped
    rather than inverted once the switch is thrown, for the reason
    test_figures_switch.py gives: flipping a kill switch during an incident
    must not also require editing a test to make CI green."""
    assert DECL.search(FN.read_text()).group(1) == "false", \
        "the endpoint does not ship the switch off"


def test_the_leak_list_cannot_pass_by_accident():
    """Every FIGURES entry must be a string that WOULD appear if it leaked.
    A leak list containing a substring of the ZIP or the as-of month is a list
    that fails on a clean response, and the fix under time pressure is to
    delete the entry rather than the collision."""
    survive = ("20601", "2026-08", "2026-08-22T11:04:09Z")
    for v in FIGURES:
        for s in survive:
            assert v not in s, f"{v!r} collides with the surviving value {s!r}"


# ————— the handler, actually executed —————

@needs_node
def test_the_switch_off_is_byte_for_byte_what_it_served_before(tmp_path):
    got = run_handler(tmp_path, figures_off=False)
    assert got["body"] == GOLDEN_OFF_BODY, "the resting response changed"
    assert got["status"] == 200
    assert got["cacheControl"] == CACHE_OFF, \
        "the resting response stopped being cacheable"


@needs_node
def test_no_figure_reaches_the_response_when_the_switch_is_on(tmp_path):
    got = run_handler(tmp_path, figures_off=True)
    body = got["body"]
    for v in FIGURES:
        assert v not in body, f"{v!r} still served with figures withheld"
    parsed = json.loads(body)
    assert parsed["metrics"] == {}, "the metrics block survived the switch"
    assert parsed["priceHistory"] == [], "the twelve-month series survived"


@needs_node
def test_the_reading_survives_when_the_switch_is_on(tmp_path):
    """The whole claim: the word is ours and separable. A switch that took the
    reading with it would withhold our own output to protect a vendor's."""
    parsed = json.loads(run_handler(tmp_path, figures_off=True)["body"])
    assert parsed["dataStatus"] == "ok", \
        "a reading with withheld figures is claiming to be a paused reading"
    assert parsed["zip"] == "20601"
    assert parsed["asOf"] == "2026-08", \
        "a page showing a reading has to be able to say which month it read"
    assert parsed["lastUpdated"] == "2026-08-22T11:04:09Z"
    assert "reading" in parsed, "the reading field left the contract entirely"
    assert parsed["figuresWithheld"] is True, \
        "nothing tells the client this is withholding rather than missing data"
    assert parsed["notice"] == FIG.WITHHELD_LINE, \
        "the endpoint's notice has drifted from figures_switch.WITHHELD_LINE"


@needs_node
def test_the_withheld_response_carries_no_field_we_did_not_intend(tmp_path):
    """Pin the whole key set. A future field carrying a figure fails here even
    if its name and formatting defeat every substring in FIGURES."""
    parsed = json.loads(run_handler(tmp_path, figures_off=True)["body"])
    assert set(parsed) == {
        "zip", "state", "reading", "asOf", "lastUpdated", "metrics",
        "priceHistory", "dataStatus", "figuresWithheld", "notice",
    }, f"unexpected fields in the withheld response: {sorted(parsed)}"


@needs_node
def test_the_series_is_not_even_fetched_when_the_switch_is_on(tmp_path):
    """Dropping a value on the way out and never reading it are different
    postures, and only the second is true of the history here."""
    on = run_handler(tmp_path, figures_off=True)
    assert not any("market_history" in u for u in on["queried"]), \
        "the history was queried even though none of it may be served"
    off = run_handler(tmp_path, figures_off=False)
    assert any("market_history" in u for u in off["queried"]), \
        "the history stopped being read with the switch OFF"


@needs_node
def test_the_withheld_response_is_not_cached(tmp_path):
    """A withheld response stored for the stale window would outlive turning
    the switch back off. The reverse — responses cached BEFORE the flip — no
    code here can fix, which is why index.ts says a flip means purging the
    CDN and not only deploying the function."""
    got = run_handler(tmp_path, figures_off=True)
    assert got["cacheControl"] == "no-store", \
        f"withheld response is cacheable: {got['cacheControl']}"
