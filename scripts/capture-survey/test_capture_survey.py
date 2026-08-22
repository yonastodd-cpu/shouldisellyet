#!/usr/bin/env python3
"""Tests for the capture survey.

    python3 -m pytest scripts/capture-survey/ -q

THE FOUR THAT MATTER are the ones proving the safety claims, because those are
the claims the task was written around and the ones a reader has to be able to
check without reading every line:

    test_plan_is_the_default_mode
    test_a_default_run_never_loads_an_http_client
    test_transport_refuses_without_the_explicit_flag
    test_no_credential_or_token_is_wired_in

They are written to fail loudly if someone later adds a convenience: an HTTP
client imported at module scope, a token read from the environment, a --collect
that defaults to on. Each of those is a one-line change that would pass every
other test in this file.

The rest cover the schema and the parsers, which is the half of the tool that
must be right on the day counsel says yes — because on that day the only
untested new thing should be the socket.
"""

import io
import json
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))

import collect          # noqa: E402
import detect           # noqa: E402
import sources          # noqa: E402
import survey           # noqa: E402
import targets          # noqa: E402
import windows          # noqa: E402
import writer           # noqa: E402

MODULES = ("collect", "detect", "sources", "survey", "targets", "transport",
           "windows", "writer")

# Run in a clean interpreter by test_a_default_run_never_loads_an_http_client.
# pytest itself imports urllib.request for unrelated reasons, so asserting on
# this process's sys.modules would pass for the wrong reason and keep passing
# after someone put an HTTP client back at module scope.
_NO_CLIENT_SCRIPT = """
import sys, io, contextlib
sys.path.insert(0, %r)
import survey
with contextlib.redirect_stdout(io.StringIO()):
    survey.main(['--scope', 'all', '--max-print', '0'])
clients = ('urllib.request', 'http.client', 'socket', 'ssl', 'requests', 'httpx')
sys.stdout.write('LOADED:' + ','.join(m for m in clients if m in sys.modules))
"""

# The companion check. Plan mode never imports transport at all, so the script
# above cannot see a client added at the top of transport.py — this one can.
_TRANSPORT_IMPORT_SCRIPT = """
import sys
sys.path.insert(0, %r)
import transport
clients = ('urllib.request', 'http.client', 'socket', 'ssl', 'requests', 'httpx')
sys.stdout.write('LOADED:' + ','.join(m for m in clients if m in sys.modules))
"""


# ————— the safety claims —————

def test_plan_is_the_default_mode():
    """No arguments must mean no requests. A --dry-run is a flag people forget."""
    args = survey._parser().parse_args([])
    assert args.collect is False
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert survey.main(["--scope", "core", "--max-print", "0"]) == 0
    assert "PLAN ONLY" in buf.getvalue()
    assert "no network request was made." in buf.getvalue()


def test_a_default_run_never_loads_an_http_client():
    """The blunt check: after a full default run, no HTTP client is imported.

    A subprocess, not an import here, because pytest's own machinery pulls
    urllib.request in for unrelated reasons and would make this pass for the
    wrong reason. transport.py defers `import urllib.request` into the request
    body precisely so this assertion is available.
    """
    script = _NO_CLIENT_SCRIPT % str(HERE)
    out = subprocess.run([sys.executable, "-c", script], capture_output=True,
                         text=True, timeout=300)
    assert out.returncode == 0, out.stderr[-2000:]
    assert "LOADED:" in out.stdout
    assert out.stdout.strip().endswith("LOADED:"), (
        "a plan-only run loaded a network client: " + out.stdout.strip())


def test_importing_transport_does_not_load_an_http_client():
    """transport.py's second lock: the client is imported inside request().

    Without this, merely importing the module — which any future caller might
    do to read USER_AGENT — would load a network stack into a process that
    only meant to plan.
    """
    out = subprocess.run([sys.executable, "-c", _TRANSPORT_IMPORT_SCRIPT % str(HERE)],
                         capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr[-2000:]
    assert out.stdout.strip() == "LOADED:", (
        "importing transport loaded a network client: " + out.stdout.strip())


def test_transport_refuses_without_the_explicit_flag():
    import transport
    assert transport.ALLOW_NETWORK is False, "the gate must be shut at import"
    with pytest.raises(transport.NetworkRefused):
        transport.request("https://example.invalid/")


def test_transport_has_no_write_verb():
    """Every removal action the memo contemplates is a POST. Refuse the verb."""
    import transport
    transport.enable("test")
    try:
        with pytest.raises(transport.NetworkRefused):
            transport.request("https://example.invalid/", method="POST")
    finally:
        transport.ALLOW_NETWORK = False


def test_no_credential_or_token_is_wired_in():
    """Nothing here can read a secret, and the check is blunt on purpose.

    Every searchcache and socialpreview mechanism needs a credential, which
    makes "just read it from the environment" the obvious next commit. It is
    not a small change: it converts a tool that provably cannot reach a
    platform into one that can, and it would not otherwise fail a single test
    in this file.

    So: no module in this tree imports `os`, reads an environment variable, or
    builds an Authorization header. Wanting a filesystem path is not a reason
    to reach for `os` — pathlib is already imported everywhere here. If a
    future change genuinely needs a credential, it should have to delete this
    test and explain itself in the commit message.
    """
    banned = ("os.environ", "os.getenv", "getenv(", "Authorization",
              "client_secret", "credentials.json", "Bearer ")
    for name in MODULES:
        src = (HERE / f"{name}.py").read_text()
        code = "\n".join(l for l in src.splitlines()
                         if not l.lstrip().startswith("#"))
        for line in code.splitlines():
            stripped = line.strip()
            assert stripped not in ("import os", "import os.path"), \
                f"{name}.py imports os"
            assert not stripped.startswith("from os "), f"{name}.py imports os"
        for token in banned:
            assert token not in code, f"{name}.py contains {token!r}"


def test_mutating_mechanisms_are_never_planned():
    """scrape=true is the remedy, not the measurement. It must not be emitted."""
    mutating = [m for m in sources.MECHANISMS if m.mutating]
    assert mutating, "the registry must keep the mutating mechanisms on record"
    t = targets.SINGLETONS[0]
    for src in sources.SOURCES:
        ids = {q.mechanism.id for q in sources.plan_for(t, src)}
        assert not ids & {m.id for m in mutating}


def test_the_tree_imports_nothing_from_pipeline():
    """See targets.py, THE IMPORT RULE. audit-og.py is the cautionary case."""
    for name in MODULES:
        src = (HERE / f"{name}.py").read_text()
        for line in src.splitlines():
            s = line.strip()
            if s.startswith(("import ", "from ")):
                assert "pipeline" not in s, f"{name}.py: {s}"


# ————— the target set —————

def test_every_one_off_page_still_corresponds_to_something_in_the_repo():
    """Six URLs are written by hand. Each must still be a real surface.

    A hand-typed URL that quietly stopped existing is a row counsel cannot
    check, and the failure is silent — the archive simply returns no captures,
    which looks exactly like a clean result.
    """
    surface_list = (ROOT / "pipeline" / "surfaces.py").read_text()
    for t in targets.SINGLETONS:
        path = t.url.replace(targets.SITE, "").lstrip("/")
        # Either the file is in the checkout, or the surface it represents is
        # named in the surface list. Both halves are needed: /llms.txt and
        # /zip/ are generated at deploy time and absent from a fresh clone,
        # while a committed static page may predate the surface list.
        exists = ((ROOT / "web" / path).exists()
                  or (ROOT / "web" / path / "index.html").exists()
                  or path == "")
        named = t.surface in surface_list
        assert exists or named, (
            f"{t.url} is neither present under web/ nor named in "
            f"pipeline/surfaces.py")


def test_the_state_hubs_come_from_the_manifest_not_a_typed_list():
    assert len(targets.states()) == 51, "50 states plus DC"
    hubs = {t.url for t in targets.state_hub_targets()}
    assert f"{targets.SITE}/zip/DC/" in hubs
    assert len(hubs) == 51


def test_share_stubs_are_queried_under_both_spellings():
    """A capture of /s/77494 is invisible to an exact query for /s/77494/."""
    stub = [t for t in targets.zip_targets(["77494"], "priority")
            if "/s/" in t.url][0]
    assert stub.variants == (f"{targets.SITE}/s/77494/",
                             f"{targets.SITE}/s/77494")


def test_the_withdrawn_research_files_are_targeted_for_every_released_month():
    months = targets.research_months()
    assert months, "the release JSONs must drive this, not a typed list"
    urls = {t.url for t in targets.research_targets()}
    for m in months:
        assert f"{targets.SITE}/research/{m}/zip-flips-{m}.csv" in urls


def test_scopes_are_nested_and_all_covers_every_paged_zip():
    core = {t.url for t in targets.build("core")}
    priority = {t.url for t in targets.build("priority")}
    every = {t.url for t in targets.build("all")}
    assert core < priority < every
    assert len(every) == len(core) + 2 * len(targets.paged_zips())


# ————— the windows —————

def test_a_capture_inside_the_window_is_in_and_one_after_is_out():
    before = windows.parse_cdx("20260818120000")
    after = windows.parse_cdx("20260822120000")
    assert windows.contains("consumer_figures", before)
    assert not windows.contains("consumer_figures", after)


def test_the_research_file_window_closes_to_the_second():
    """03:22:25Z is the recorded moment. A capture at 03:22:26 is out."""
    assert windows.contains("research_zip_file", windows.parse_cdx("20260821032225"))
    assert not windows.contains("research_zip_file", windows.parse_cdx("20260821032226"))


def test_a_malformed_capture_timestamp_raises_rather_than_defaulting():
    """Defaulting to now() would mark every capture out-of-window — a clean
    survey produced by a parsing bug, which is the one wrong answer here."""
    with pytest.raises(ValueError):
        windows.parse_cdx("2026-08-21")


def test_a_capture_between_the_two_ends_matches_only_the_credits_window():
    when = windows.parse_cdx("20260821100000")
    t = targets.SINGLETONS[0]
    assert windows.matched(t.windows, when) == ("vendor_credits",)


# ————— the detector —————

def test_a_withdrawn_reading_in_share_metadata_is_found():
    html = ('<title>Austin TX 78660 — WATCH</title>'
            '<meta property="og:description" content="Homes take 61 days to sell">'
            '<body><p>nothing here</p></body>')
    verdict, evidence = detect.classify(html, "https://shouldisellyet.com/zip/78660/")
    assert verdict == detect.FIGURES_VISIBLE
    assert "61 days" in evidence


def test_naming_the_rating_vocabulary_on_the_press_page_is_not_a_leak():
    html = "<body>HOLD / WATCH / ACT verdicts for 22,874 U.S. ZIP codes</body>"
    verdict, _ = detect.classify(html, "https://shouldisellyet.com/press.html")
    assert verdict == detect.VOCABULARY_ONLY


def test_a_rating_on_a_zip_page_is_a_leak_even_with_no_figure():
    html = "<title>x</title><body>Your market: WATCH</body>"
    verdict, _ = detect.classify(html, "https://shouldisellyet.com/zip/78660/")
    assert verdict == detect.RATING_VISIBLE


def test_the_published_danger_lines_are_not_counted_as_a_leak():
    """Disclosure is not a leak — the thresholds are ours and are on every page."""
    html = ("<body>We watch the year-over-year price trend (−2%) and how long "
            "homes take to sell (+30% year over year).</body>")
    verdict, _ = detect.classify(html, "https://shouldisellyet.com/zip/78660/")
    assert verdict == detect.CLEAN


def test_the_refresh_notice_reads_clean():
    html = ('<title>Austin, TX housing market — reading being refreshed</title>'
            '<body>We are rebuilding this market reading on a new data '
            'engine.</body>')
    verdict, _ = detect.classify(html, "https://shouldisellyet.com/zip/78660/")
    assert verdict == detect.CLEAN


def test_a_withdrawn_ratings_csv_reads_as_withdrawn():
    """The tag strippers are no-ops on a CSV, so it goes down the same path.

    It lands as rating_visible rather than figures_visible, and that is right:
    what this file published was 2,403 RATINGS, one per ZIP. The bare numbers
    in it are supply values without units, which no reader would call a market
    figure. Both verdicts answer the memo's column with "yes"; the distinction
    is the argument behind the yes, which is why the detector keeps them apart.
    """
    csv_body = ("zip,state,reading,months_of_supply\n"
                "78660,TX,WATCH,5.2\n20601,MD,ACT,6.1\n")
    verdict, _ = detect.classify(
        csv_body, "https://shouldisellyet.com/research/2026-07/zip-flips-2026-07.csv")
    assert verdict == detect.RATING_VISIBLE
    assert writer._VISIBLE[verdict] == "yes"


def test_an_unfetched_body_is_unknown_not_clean():
    assert detect.classify(None, "x")[0] == detect.NOT_FETCHED
    assert writer._VISIBLE[detect.NOT_FETCHED] == "unknown"


# ————— the collector, driven by a fake fetch —————

CDX_HEADER = ["timestamp", "original", "statuscode", "digest", "mimetype", "length"]


def _cdx(*rows):
    return json.dumps([CDX_HEADER] + [list(r) for r in rows])


def _fake_fetch(index_payload, body_by_timestamp):
    calls = []

    def fetch(url):
        calls.append(url)
        if "/cdx/search/cdx" in url:
            return 200, index_payload, ""
        for ts, body in body_by_timestamp.items():
            if f"/web/{ts}id_/" in url:
                return 200, body, ""
        return 404, None, "HTTP 404"

    return fetch, calls


def test_an_in_window_capture_showing_a_figure_produces_the_row_counsel_wants():
    target = targets.SINGLETONS[0]
    payload = _cdx(
        ("20260818094500", target.url, "200", "AAA", "text/html", "12000"),
        ("20260825094500", target.url, "200", "BBB", "text/html", "9000"))
    fetch, _ = _fake_fetch(payload, {
        "20260818094500": "<title>WATCH</title><body>61 days to sell</body>",
        "20260825094500": "<title>reading being refreshed</title><body>ok</body>",
    })
    rows = collect.webarchive_rows(target, fetch)
    leaking = [r for r in rows if r["in_window"] == "yes"]
    assert leaking, "the 18 August capture must be in-window"
    r = leaking[0]
    assert r["capture_utc"] == "2026-08-18T09:45:00Z"
    assert r["figures_visible"] == "yes"
    assert "61 days" in r["evidence"]
    assert r["retrieval_url"].startswith("https://web.archive.org/web/20260818094500id_/")
    after = [x for x in rows if x["in_window"] == "no"]
    assert after and after[0]["figures_visible"] == "no", (
        "the first capture after the window is the control and must be fetched")


def test_a_url_with_no_captures_still_produces_a_row():
    """An absent row is indistinguishable from a URL nobody checked."""
    target = targets.SINGLETONS[2]
    fetch, _ = _fake_fetch("[]", {})
    rows = collect.webarchive_rows(target, fetch)
    assert rows and all(r["capture_utc"] == "" for r in rows)
    assert "no captures held" in rows[0]["note"]


def test_the_cdx_header_row_is_not_treated_as_a_capture():
    assert collect.parse_cdx(json.dumps([CDX_HEADER])) == []
    assert collect.parse_cdx("") == []
    assert collect.parse_cdx("[]") == []


def test_hitting_the_index_row_cap_is_reported_not_swallowed():
    """Silence here would understate exposure."""
    target = targets.SINGLETONS[2]
    rows_in = [("2026081809450" + str(i % 10), target.url, "200", f"D{i}",
                "text/html", "1") for i in range(3)]
    fetch, _ = _fake_fetch(_cdx(*rows_in), {})
    rows = collect.webarchive_rows(target, fetch, body_policy="none", limit=3)
    assert any("TRUNCATED" in r["note"] for r in rows)


def test_bodies_are_not_fetched_when_the_policy_says_none():
    target = targets.SINGLETONS[2]
    payload = _cdx(("20260818094500", target.url, "200", "AAA", "text/html", "1"))
    fetch, calls = _fake_fetch(payload, {})
    collect.webarchive_rows(target, fetch, body_policy="none")
    assert not any("id_/" in c for c in calls)


def test_an_unrunnable_mechanism_still_produces_a_row_saying_why():
    target = targets.SINGLETONS[0]
    rows = collect.blocked_rows(target, sources.SOCIALPREVIEW)
    ids = {r["mechanism"] for r in rows}
    assert "facebook_graph_read" in ids and "x_card_validator" in ids
    assert "facebook_scrape_again" not in ids, "a mutation is not a survey row"
    assert all(r["figures_visible"] == "unknown" for r in rows)
    assert all(r["note"].startswith("not checked — ") for r in rows)


# ————— the writer —————

def test_the_writer_refuses_to_overwrite(tmp_path):
    writer.write(tmp_path, "a.csv", writer.PLAN_HEADER, [])
    with pytest.raises(SystemExit):
        writer.write(tmp_path, "a.csv", writer.PLAN_HEADER, [])


def test_the_writer_refuses_an_output_path_inside_the_public_repo():
    with pytest.raises(SystemExit):
        writer.resolve_outdir(ROOT / "survey-out")
    assert not (ROOT / "survey-out").exists(), "and it must not create it either"


def test_every_row_the_collector_builds_matches_the_published_schema():
    target = targets.SINGLETONS[0]
    payload = _cdx(("20260818094500", target.url, "200", "A", "text/html", "1"))
    fetch, _ = _fake_fetch(payload, {"20260818094500": "<body>ok</body>"})
    for row in collect.webarchive_rows(target, fetch):
        assert list(row) == writer.SURVEY_HEADER


def test_the_plan_csv_matches_its_published_schema():
    q = sources.plan_for(targets.SINGLETONS[0], sources.WEBARCHIVE)[0]
    assert list(writer.plan_row(q)) == writer.PLAN_HEADER
