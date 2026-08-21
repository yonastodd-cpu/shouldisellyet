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
OUT = ROOT / "web" / "data" / "z"        # PUBLIC: state code only, no figures
BUILD = ROOT / ".build" / "readings"     # PRIVATE: full records, never deployed
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
        rows = db_rows(source, zips)
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


def write(by_state, out=OUT, build_out=None):
    """Two sets of records: one the site ships, one only the build sees.

    THE PUBLIC SET CARRIES NO FIGURES. web/data/z/{zip}.json is {"st": "MD"}
    for every ZIP, released or not. It exists so the client can tell a ZIP we
    cover from one we do not, and for nothing else.

    THE PRIVATE SET carries the readings and is written outside web/, so the
    deploy cannot pick it up. build_pages reads it to render each page's own
    figures into that page's HTML.

    WHY THEY ARE SEPARATE. Per-ZIP public files fixed one problem and created a
    larger one. They stopped a page downloading a whole state to show one ZIP —
    but 5,000 files named by ZIP code, each holding current metrics and a
    twelve-month history, is a dataset anyone can collect by iterating five
    digits: roughly 60,000 asking prices and 60,000 days-on-market values,
    downloadable without authentication. That is distribution of the vendor's
    underlying measurements whatever the file layout, and it is what the
    licence question turns on.

    The reading is ours and stays on the page. The vendor's figures now reach a
    reader one page at a time, from the endpoint, or not at all.

    Superseded reasoning, kept because it explains the shape:

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
    # A DEFAULT MUST NOT POINT AT SHARED STATE. build_out used to default to
    # the repo-root BUILD directory, so a caller overriding only `out` — every
    # test does — rmtree'd the real private records and replaced them with its
    # fixtures. CI runs provision, then pytest, then build_pages: provisioning
    # wrote 5,000 readings, the suite wiped them, and the build put 5,000
    # released pages back behind the notice. Green tests, dark site.
    #
    # The private set now follows wherever the public one is written unless a
    # caller says otherwise, so a test writing to tmp_path stays in tmp_path.
    out = Path(out)
    build_out = Path(build_out) if build_out is not None else (
        BUILD if out == OUT else out.parent / "_private_readings")
    for d in (out, build_out):
        if d.exists():
            shutil.rmtree(d)    # stale records must not survive the switch
        d.mkdir(parents=True, exist_ok=True)
    n = 0
    for records in by_state.values():
        for zip_code, record in records.items():
            # PUBLIC: OUR output only — the reading word, its basis, the
            # month it is as of, and the state. Not one vendor measurement.
            #
            # This is the licence distinction expressed in the data model.
            # The HOLD/WATCH/ACT word is ours: we computed it, and displaying
            # it is the use the vendor's terms clearly permit. The figures
            # underneath it are theirs, and those now come one ZIP at a time
            # from the endpoint or not at all. Enumerating every file here
            # yields a list of ZIPs and what we think of them — a directory of
            # our own opinions, which is not a redistribution of their data.
            #
            # Deliberately absent: m (the seven metrics), h (the twelve-month
            # price and days-on-market series), s and r (the score and its
            # reason triples, which carry derived vendor ratios).
            public = {"st": record.get("st", "")}
            for k in ("l", "b", "p"):
                if record.get(k) is not None:
                    public[k] = record[k]
            (out / f"{zip_code}.json").write_text(
                json.dumps(public, separators=(",", ":")), encoding="utf-8")
            # PRIVATE: the full record, for the build only.
            (build_out / f"{zip_code}.json").write_text(
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
