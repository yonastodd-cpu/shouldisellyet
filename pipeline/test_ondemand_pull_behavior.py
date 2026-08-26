"""The pull handler, actually executed — because the source pins can't count.

test_ondemand_pull_fn.py pins ORDER in the source. This file runs the real
handler (same Node harness idiom as test_figures_switch_endpoint.py) and
asserts the four behaviours that cost money or sell falsehoods if wrong:

  1. A ZIP already in the store answers ok WITHOUT a vendor call — the
     dedupe that makes buyer #2 free.
  2. At the ceiling, the answer is at_capacity and the vendor is not called.
  3. A thin payload (too little history to know two signals) is refused:
     no charge-enabling ok, and — critically — NO zip_release row, because
     that row is what makes the API serve the ZIP.
  4. A good payload stores everything the batch loader would have
     (market_stats with raw_json, history, the reading in named columns,
     the release row) and the computed reading matches verdict_v2 run on
     the same numbers.

Skips with a reason where node cannot run TypeScript, like its sibling.

Run: python3 -m pytest pipeline/test_ondemand_pull_behavior.py -q
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import verdict_v2
from test_figures_switch_endpoint import _node_runs_typescript

ROOT = Path(__file__).resolve().parents[1]
FN = ROOT / "supabase" / "functions" / "ondemand-pull" / "index.ts"
RATELIMIT = ROOT / "supabase" / "functions" / "_shared" / "ratelimit.ts"

needs_node = pytest.mark.skipif(
    _node_runs_typescript() is not None,
    reason=_node_runs_typescript() or "",
)


def _history(months):
    """month → record, oldest first, prices falling hard year over year."""
    out = {}
    prices = {0: 450000, 12: 400000}     # oldest vs newest: −11.1% YoY
    dom = {0: 50, 12: 60}                # +20% YoY
    listings = {0: 80, 12: 100}          # +25% YoY (below the surge line)
    for i in range(months):
        ym = f"{2025 + (8 + i) // 12}-{(8 + i) % 12 + 1:02d}"
        out[ym] = {
            "medianPrice": prices.get(i, 420000),
            "averageDaysOnMarket": dom.get(i, 55),
            "totalListings": listings.get(i, 90),
        }
    return out


def vendor_payload(months=13):
    hist = _history(months)
    newest = hist[sorted(hist)[-1]]
    return {
        "zipCode": "30349",
        "saleData": {
            "lastUpdatedDate": sorted(hist)[-1] + "-15T00:00:00Z",
            "medianPrice": newest["medianPrice"],
            "averagePrice": 410000,
            "medianPricePerSquareFoot": 190.5,
            "averageDaysOnMarket": newest["averageDaysOnMarket"],
            "totalListings": newest["totalListings"],
            "newListings": 20,
            "history": hist,
        },
    }


HARNESS = r"""
const out = (o) => process.stdout.write(JSON.stringify(o) + "\n");
try {
  const FX = JSON.parse(process.env.SISY_FIXTURES);
  let handler = null;
  globalThis.Deno = {
    env: { get: (k) => ({
      SUPABASE_URL: "https://stub.invalid",
      SUPABASE_SERVICE_ROLE_KEY: "service-role-key-0123456789abcdef0123456789",
      RENTCAST_API_KEY: FX.apiKey || undefined,
    }[k]) },
    serve: (h) => { handler = h; },
  };
  const writes = [];      // {url, method, prefer, body}
  let vendorCalls = 0;
  globalThis.fetch = async (url, init) => {
    const u = String(url);
    const method = (init && init.method) || "GET";
    if (u.includes("api.rentcast.io")) {
      vendorCalls++;
      return new Response(JSON.stringify(FX.vendor), { status: FX.vendorStatus });
    }
    if (method === "POST" || method === "PATCH") {
      const h = init && init.headers ? init.headers : {};
      writes.push({ url: u, method,
                    prefer: h["Prefer"] || h["prefer"] || "",
                    body: init.body ? JSON.parse(init.body) : null });
      return new Response("", { status: 201 });
    }
    const headers = new Headers({ "content-type": "application/json" });
    let body = null;
    if (u.includes("rate_limit_hit")) body = true;
    else if (u.includes("zip_release")) body = FX.release;
    else if (u.includes("market_stats")) body = FX.stats;
    else if (u.includes("ondemand_pulls")) {
      body = [];
      headers.set("content-range", "0-0/" + FX.used);
      return new Response(JSON.stringify(body), { status: 206, headers });
    }
    if (body === null) throw new Error("no stub route for " + u);
    return new Response(JSON.stringify(body), { status: 200, headers });
  };
  await import(process.env.SISY_MODULE);
  if (!handler) throw new Error("the module never called Deno.serve");
  const res = await handler(new Request("https://stub.invalid/ondemand-pull", {
    method: "POST",
    headers: { origin: "https://shouldisellyet.com" },
    body: JSON.stringify({ zip: FX.zip }),
  }));
  out({ ok: true, status: res.status, body: await res.text(),
        vendorCalls, writes });
} catch (e) {
  out({ ok: false, error: String((e && e.stack) || e) });
}
"""


def run_handler(tmp_path, **fx):
    src = FN.read_text().replace(
        '"../_shared/ratelimit.ts"', f'"{RATELIMIT.as_uri()}"')
    mod = tmp_path / "fn.ts"
    mod.write_text(src)
    harness = tmp_path / "harness.mjs"
    harness.write_text(HARNESS)
    fixtures = {"zip": "30349", "apiKey": "test-key", "used": 0,
                "release": [], "stats": [], "vendor": None,
                "vendorStatus": 200}
    fixtures.update(fx)
    env = dict(os.environ, SISY_FIXTURES=json.dumps(fixtures),
               SISY_MODULE=mod.as_uri())
    r = subprocess.run(["node", str(harness)], env=env, capture_output=True,
                       text=True, timeout=120)
    assert r.stdout.strip(), f"harness produced nothing: {r.stderr[-800:]}"
    res = json.loads(r.stdout.strip().splitlines()[-1])
    assert res["ok"], res.get("error")
    res["parsed"] = json.loads(res["body"])
    return res


def _wrote(res, fragment):
    return [w for w in res["writes"] if fragment in w["url"]]


@needs_node
def test_a_stored_zip_answers_without_spending(tmp_path):
    res = run_handler(
        tmp_path,
        release=[{"zip": "30349", "basis": "active listings"}],
        stats=[{"zip": "30349", "retrieved_at": "2026-08-20T00:00:00Z"}])
    assert res["parsed"] == {"ok": True, "served": "store"}
    assert res["vendorCalls"] == 0, "buyer #2 must cost $0"


@needs_node
def test_at_the_ceiling_the_vendor_is_not_called(tmp_path):
    res = run_handler(tmp_path, used=99999)
    assert res["parsed"] == {"ok": False, "reason": "at_capacity"}
    assert res["vendorCalls"] == 0
    # and the turnaway is a demand data point
    logged = _wrote(res, "zip_lookups")
    assert logged and logged[0]["body"]["outcome"] == "pull_capacity"


@needs_node
def test_no_api_key_degrades_to_capacity(tmp_path):
    res = run_handler(tmp_path, apiKey="")
    assert res["parsed"] == {"ok": False, "reason": "at_capacity"}
    assert res["vendorCalls"] == 0


@needs_node
def test_a_thin_payload_is_refused_and_never_released(tmp_path):
    res = run_handler(tmp_path, vendor=vendor_payload(months=3))
    assert res["parsed"] == {"ok": False, "reason": "no_data"}
    assert not _wrote(res, "zip_release"), \
        "a ZIP below the floor must never become API-servable"
    assert not _wrote(res, "zip_readings")
    pulls = _wrote(res, "ondemand_pulls")
    assert pulls and pulls[0]["body"]["status"] == "no_data", \
        "the failed call still spent quota and must be counted"
    logged = _wrote(res, "zip_lookups")
    assert logged and logged[0]["body"]["outcome"] == "pull_failed"


@needs_node
def test_vendor_404_is_no_data_not_error(tmp_path):
    res = run_handler(tmp_path, vendor=None, vendorStatus=404)
    assert res["parsed"] == {"ok": False, "reason": "no_data"}


@needs_node
def test_a_good_payload_stores_everything_and_scores_like_the_engine(tmp_path):
    payload = vendor_payload(months=13)
    res = run_handler(tmp_path, vendor=payload)
    assert res["parsed"] == {"ok": True, "served": "pull"}
    assert res["vendorCalls"] == 1

    stats = _wrote(res, "market_stats")
    assert stats, "the acquisition must be kept"
    row = stats[0]["body"][0]
    assert row["raw_json"] == payload, "the durable copy is raw_json"
    assert row["source"] == "rentcast" and row["retrieved_at"]

    hist = _wrote(res, "market_history")
    assert hist and len(hist[0]["body"]) == 12

    release = _wrote(res, "zip_release")
    assert release and "ignore-duplicates" in release[0]["prefer"], \
        "the release insert must never relabel a tranche row"
    assert release[0]["body"][0]["tranche"] == "ondemand"

    # The reading matches verdict_v2 run over the same numbers.
    sale = payload["saleData"]
    market = verdict_v2.from_market_stats(
        {"zip": "30349", "as_of_month": row["as_of_month"],
         "list_median_price": sale["medianPrice"],
         "active_dom": sale["averageDaysOnMarket"],
         "total_listings": sale["totalListings"],
         "list_median_ppsf": sale["medianPricePerSquareFoot"],
         "new_listings": sale["newListings"]},
        sale["history"])
    want = verdict_v2.evaluate(market)
    reading = _wrote(res, "zip_readings")[0]["body"][0]
    assert reading["level"] == want.level, \
        f"function scored {reading['level']}, verdict_v2 scored {want.level}"
    assert reading["score"] == want.score
    assert reading["basis"] == want.basis

    pulls = _wrote(res, "ondemand_pulls")
    assert pulls and pulls[0]["body"]["status"] == "pulled"
