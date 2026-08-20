#!/usr/bin/env python3
"""Generate web/data/zips/ from the manifest, plus readings for released ZIPs.

    python3 pipeline/provision_readings.py                 # from the private store
    python3 pipeline/provision_readings.py --no-readings   # manifest only, offline

Every ZIP in pipeline/data/page_manifest.csv gets a record. A ZIP that is NOT
in a released tranche gets `{"st": "MD"}` and nothing else — enough for the
page to exist, for the state hub to list it, and for the browser lookup to
know it is a real ZIP, and containing no measurement of any kind. A released
ZIP additionally gets its reading, scored by verdict_v2 from the private
store.

WHY THE OUTPUT IS GENERATED AND NOT COMMITTED. web/data/zips used to be
committed source carrying a vendor's figures for 28,000+ ZIPs, and the whole
of web/ is uploaded as the deployed artifact — so those files were also a
public bulk-download endpoint, independent of any page linking them. Now they
are build output like web/zip/, web/og/ and web/stories/ already are.

THE FAILURE THAT MATTERS. If this writes fewer records than the manifest has
rows, build_pages emits fewer pages, and because generated directories are
rebuilt each deploy that DELETES live URLs. So the record count is asserted
against the manifest before anything is written, and a provisioning run that
cannot reach the store still writes every manifest record — losing readings
degrades a page to its notice, losing pages destroys URLs, and those are not
the same size of mistake.
"""

import argparse
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
import realtor_crosscheck as RDC

sys.path.insert(0, str(Path(__file__).parent))
import verdict_v2 as v2
from build_manifest import read_manifest
from rescore_v2 import compact, db_rows

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "web" / "data" / "z"     # one file per ZIP; see write()
TRANCHES = Path(__file__).parent / "tranches.json"


def released(path=TRANCHES):
    """ZIPs in a tranche that has actually been released."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return set()
    out = set()
    for t in data.get("tranches", []):
        if t.get("released_utc"):
            out.update(str(z) for z in t.get("zips", []))
    return out


def readings_for(zips, source="rentcast"):
    """{zip: reading} for the given ZIPs, scored from the private store.

    Returns {} on any failure. That is deliberate: a store outage should
    publish the notice, not remove pages.
    """
    if not zips:
        return {}
    try:
        rows = db_rows(source)
    except SystemExit as e:
        print(f"provision: store unavailable ({e}) — every page falls back to "
              f"the notice, no page is lost")
        return {}
    out = {}
    for row, hist in rows:
        z = row.get("zip")
        if z in zips:
            scored, _ = compact(v2.from_market_stats(row, hist), row, hist)
            out[z] = scored
    return out


def build(manifest, readings):
    """{state: {zip: record}} — one record per manifest row, always."""
    by_state = defaultdict(dict)
    for zip_code, state in manifest:
        record = {"st": state}
        reading = readings.get(zip_code)
        if reading:
            # {**reading} copies every key through unfiltered, so a cross-check
            # block that reached a reading would ship without anyone deciding
            # to publish it. The switch is enforced where data leaves.
            record = RDC.strip({**reading, "st": state})
        by_state[state][zip_code] = record
    return by_state


def write(by_state, out=OUT):
    """ONE FILE PER ZIP, not one per state.

    A state file made the browser download every record in the state to
    display one — 382 for Maryland, 1,475 for California. While every record
    is {"st":"MD"} that is merely wasteful; the moment Phase 4 provisions
    readings back in, showing one ZIP republishes several hundred others to
    anyone watching the network tab, and /data/zips/CA.json becomes a
    bulk-download endpoint again.

    Per-ZIP files fix that with no runtime dependency: the front door keeps
    being served by the same CDN as the page, with no API to rate-limit, no
    CORS origin to pin, and nothing to be down. The release gate still applies
    — build() only puts a reading in a file when the ZIP is in a released
    tranche — it just runs at build time rather than per request.

    A missing file is a ZIP we do not cover, which is exactly what the client
    needs to know, so the prefix lookup disappears with the state files.
    """
    out = Path(out)
    if out.exists():
        shutil.rmtree(out)      # stale state shards must not survive the switch
    out.mkdir(parents=True, exist_ok=True)
    n = 0
    for records in by_state.values():
        for zip_code, record in records.items():
            (out / f"{zip_code}.json").write_text(
                json.dumps(record, separators=(",", ":")), encoding="utf-8")
            n += 1
    return n


def main(argv=None):
    ap = argparse.ArgumentParser(description="Generate web/data/zips from the manifest")
    ap.add_argument("--manifest", default=None)
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--tranches", default=str(TRANCHES))
    ap.add_argument("--source", default="rentcast")
    ap.add_argument("--no-readings", action="store_true",
                    help="manifest only; never contacts the store")
    ap.add_argument("--fixture",
                    help="JSON {zip: reading} to use INSTEAD of the store — "
                         "offline, for exercising the released render paths "
                         "without a vendor call or a production release")
    args = ap.parse_args(argv)

    manifest = read_manifest(args.manifest) if args.manifest else read_manifest()
    if not manifest:
        raise SystemExit(
            "page_manifest.csv is empty or missing. Refusing to write: an empty "
            "manifest would emit zero pages and the deploy would delete every "
            "live ZIP URL. Restore the manifest before building.")

    live = set() if args.no_readings else released(args.tranches)
    if args.fixture:
        # The released paths are unreachable in a normal build — nothing is
        # released — so the only way to render and test them is to supply the
        # readings directly. Deliberately offline: no vendor call, no store,
        # no row written anywhere.
        fixture = json.loads(Path(args.fixture).read_text())
        readings = {z: r for z, r in fixture.items() if z in live}
        print(f"provision: fixture supplied {len(readings):,} reading(s); "
              f"the store was not contacted")
    else:
        readings = {} if args.no_readings else readings_for(live, args.source)
    missing = len(live) - len(readings)
    if live and missing:
        # A release that publishes nothing is a release that did not happen,
        # and it used to be a one-line note in a green build. On 2026-08-20 the
        # store was unreachable from CI, all 1,000 released ZIPs fell back to
        # the notice, and the deploy reported success. Nothing was wrong with
        # the pages after indexable() learned to read the record — but the
        # release silently did not land, which is worth a warning annotation
        # rather than a line in a log nobody opens.
        print(f"::warning::provision: {missing:,} of {len(live):,} released "
              f"ZIP(s) have no reading — they render the notice and stay "
              f"noindexed. The tranche is stamped but not published. Check "
              f"the store connection, then re-run the build.")

    by_state = build(manifest, readings)
    written = write(by_state, args.out)

    if written != len(manifest):
        raise SystemExit(f"wrote {written:,} records for {len(manifest):,} "
                         f"manifest rows — refusing to continue")
    print(f"provisioned {written:,} records across {len(by_state)} state file(s)")
    print(f"  released with a reading: {len(readings):,}")
    print(f"  notice only: {written - len(readings):,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
