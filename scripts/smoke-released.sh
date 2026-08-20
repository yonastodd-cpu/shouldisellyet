#!/usr/bin/env bash
# Render and smoke-test the RELEASED paths, entirely offline.
#
#   ./scripts/smoke-released.sh
#
# Nothing is released in production, so `ok` and `insufficient_data` are
# unreachable in a normal build — which is why the sparkline returning one
# point instead of twelve survived every gate until someone released a ZIP by
# hand. This stages a release LOCALLY with fixture readings, builds those
# pages, runs the browser assertions against them, and puts everything back.
#
# It makes NO vendor call and writes NOTHING to the database. The fixture
# readings are synthetic numbers, not data from anywhere.
set -euo pipefail
cd "$(dirname "$0")/.."

OK_ZIP=20601      # a released ZIP with a full reading
THIN_ZIP=20602    # released, but its reading says it has too little data
TMP="$(mktemp -d)"
SRV=""
# Restore in the right order: put the file back BEFORE removing the directory
# it is saved in, and always kill the server. This staged a release in the
# working tree, so leaving it half-restored would leave two ZIPs released.
cleanup() {
  [ -n "$SRV" ] && kill "$SRV" 2>/dev/null || true
  if [ -f "$TMP/tranches.orig.json" ]; then
    cp "$TMP/tranches.orig.json" pipeline/tranches.json
  else
    git checkout -- pipeline/tranches.json 2>/dev/null || true
  fi
  rm -rf "$TMP"
  # Rebuild the two pages from the restored (unreleased) state so the working
  # tree does not keep a rendered release.
  python3 pipeline/provision_readings.py --no-readings >/dev/null 2>&1 || true
  python3 pipeline/build_pages.py --only "$OK_ZIP,$THIN_ZIP" >/dev/null 2>&1 || true
  echo "  restored: tranches.json and both pages back to unreleased"
}
trap cleanup EXIT

cp pipeline/tranches.json "$TMP/tranches.orig.json"

cat > "$TMP/tranches.json" <<JSON
{"basis":"active listings","tranches":[
 {"name":"__smoke","released_utc":"2026-08-20T00:00:00Z","basis":"active listings",
  "zips":["$OK_ZIP","$THIN_ZIP"]}]}
JSON

# Synthetic readings. The shape is verdict_v2.to_compact's, the numbers are
# invented — nothing here came from a vendor.
cat > "$TMP/fixture.json" <<JSON
{
 "$OK_ZIP": {"l":"red","s":3,"r":[["price_falling_fast",3,-0.0751]],
   "b":"active listings",
   "m":{"spy":-0.0751,"dom":52.0,"domy":-3.0,"invy":0.08,"inv":979},
   "h":{"s":"2025-09","p":[529000,520000,510000,505000,500000,498000,495000,492000,491000,490000,489500,489296],
        "d":[55,58,65,60,57,54,53,52,52,52,52,52]}},
 "$THIN_ZIP": {"l":"green","s":0,"r":[["insufficient_data",0,1]],
   "b":"active listings","m":{"spy":-0.03},"h":null}
}
JSON

cp "$TMP/tranches.json" pipeline/tranches.json
python3 pipeline/provision_readings.py --fixture "$TMP/fixture.json" >/dev/null
python3 pipeline/build_pages.py --only "$OK_ZIP,$THIN_ZIP,20603" >/dev/null

python3 -m http.server 5178 --directory web >/dev/null 2>&1 &
SRV=$!
for _ in $(seq 1 20); do curl -sf http://localhost:5178/ >/dev/null && break; sleep 0.5; done

# playwright is installed per-run in CI and may live elsewhere locally.
: "${NODE_PATH:=}"
export NODE_PATH
# The paused assertions need a ZIP that is NOT released — running them against
# the staged one fails on correct behaviour.
PAUSED_ZIP=20603
node scripts/smoke-browser.mjs http://localhost:5178 "$PAUSED_ZIP" --released "$OK_ZIP" --thin "$THIN_ZIP"
