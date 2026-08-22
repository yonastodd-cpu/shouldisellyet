#!/usr/bin/env python3
"""Snapshot the vendor's live terms, dated, so version drift is on the record.

    python3 pipeline/snapshot_vendor_terms.py              # dry run, NO network
    python3 pipeline/snapshot_vendor_terms.py --fetch      # take the snapshot
    python3 pipeline/snapshot_vendor_terms.py --fetch --fail-on-change

WHY THIS FILE EXISTS. We hold the terms as they stood on 21 August 2026. We do
NOT hold the version that was in force on 19 August 2026, when the first 5,000
calls were made, and the memo to counsel says so in as many words. That gap
cannot be closed — nobody kept a copy — but it can be prevented from happening
again, and one unattended monthly fetch is what prevents it. The question this
answers is not "what do the terms say", it is "what did they say ON THE DAY we
relied on them", and that question has exactly one acceptable form of evidence:
the bytes, with a date and a digest.

WHAT MAKES IT EVIDENCE RATHER THAN A DOWNLOAD
  * the response body is written byte-for-byte. No text extraction, no
    prettifying, no encoding fixes. A transformed copy is a description of the
    document, not the document.
  * every run appends a MANIFEST row whether or not anything changed. "We
    looked on 2026-09-01 and it was identical" is a fact worth holding; a
    directory that only records changes cannot distinguish "unchanged" from
    "nobody ran it".
  * the filename carries the date and the manifest carries the SHA-256, the
    HTTP status, and whatever Last-Modified / ETag the server volunteered.

WHY IT REFUSES TO WRITE INTO A TRACKED DIRECTORY. This repository is public.
Committing a vendor's terms-of-use text would republish their copyrighted
document to the world from the account of a licensee who is arguing about
licence scope — the exact shape of the problem this whole workstream exists to
clean up. So the destination is checked against `git check-ignore` before a
single byte is written, and an un-ignored destination is a hard stop, not a
warning. The .gitignore entry is a prerequisite, not an afterthought.

IT DOES NOT RUN ON IMPORT AND IT DOES NOT RUN WITHOUT --fetch. Running with no
arguments prints the plan and touches no network. That is deliberate: this
module gets imported by its test, edited by people who are not thinking about
quota or vendor logs, and scheduled by CI. Only one of those three should ever
produce a request, and it has to ask.

NOT A VENDOR DATA CALL. This fetches a public terms page over plain HTTPS with
no API key. It is not metered, it does not touch api.rentcast.io, and it
cannot consume quota — worth stating because the standing instruction in this
repo is that nothing calls the vendor, and a reader hitting this file needs to
know in the first screen why it is not that.

CI: monthly, unattended. See the schedule note at the bottom of this file.
"""

import argparse
import csv
import hashlib
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_data import _ssl_context      # same CA handling as the pipeline

ROOT = Path(__file__).resolve().parents[1]

# Default destination. MUST be git-ignored — see the guard below. Named
# "docs/" because that is where a human will look for it, not because these
# files are documentation: they are exhibits.
DEST = ROOT / "docs" / "vendor-terms"
MANIFEST = "MANIFEST.csv"
MANIFEST_FIELDS = ["retrieved_at", "slug", "url", "http", "bytes", "sha256",
                   "last_modified", "etag", "changed_from_previous", "file"]

# The pages to hold. CONFIRM THESE AGAINST THE EXECUTED AGREEMENT before the
# first scheduled run: a snapshot of the wrong page is worse than no snapshot,
# because it looks like diligence. The memo records that unseen third-party
# terms control on conflict, so anything the agreement incorporates by
# reference belongs in this list too — that is precisely the class of document
# we cannot currently produce.
TERMS_URLS = (
    ("terms-of-service", "https://www.rentcast.io/terms-of-service"),
    ("privacy-policy", "https://www.rentcast.io/privacy-policy"),
)

UA = "shouldisellyet-terms-archiver"
TIMEOUT = 60


def today(clock=None):
    return (clock or (lambda: datetime.now(timezone.utc)))().strftime("%Y-%m-%d")


def stamp(clock=None):
    return (clock or (lambda: datetime.now(timezone.utc)))().strftime("%Y-%m-%dT%H:%M:%SZ")


def is_ignored(path, root=ROOT):
    """True when git would refuse to track `path`.

    `git check-ignore -q` exits 0 for ignored, 1 for not ignored, 128 when it
    cannot answer (not a repo, git missing). 128 is treated as NOT ignored: a
    guard that fails open is not a guard, and the cost of being wrong here is
    publishing a vendor's copyrighted terms from a public repository.
    """
    try:
        r = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(path)],
                           capture_output=True)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def fetch(url, opener=None, timeout=TIMEOUT):
    """(http_status, body_bytes, headers). Raises on anything but a 2xx.

    Kept tiny and injectable so the test can exercise the writing, hashing and
    manifest logic without a network — the one thing this module must never do
    by accident.
    """
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    op = opener or (lambda r: urllib.request.urlopen(
        r, timeout=timeout, context=_ssl_context()))
    with op(req) as resp:
        body = resp.read()
        return getattr(resp, "status", 200), body, dict(resp.headers)


def previous_digest(dest, slug):
    """The sha256 of the last snapshot of this page, or "" if there is none."""
    mf = Path(dest) / MANIFEST
    if not mf.exists():
        return ""
    last = ""
    for row in csv.DictReader(mf.open(encoding="utf-8")):
        if row.get("slug") == slug:
            last = row.get("sha256") or last
    return last


def append_manifest(dest, row):
    mf = Path(dest) / MANIFEST
    new = not mf.exists()
    with mf.open("a", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        if new:
            w.writeheader()
        w.writerow(row)


def snapshot(urls=TERMS_URLS, dest=DEST, fetcher=fetch, clock=None):
    """Fetch and store each page. Returns the manifest rows written.

    A failure on one URL does not abandon the others — a terms page that 404s
    because the vendor moved it is itself a finding, and it must not cost us
    the snapshot of the page that still resolves.
    """
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    day, when = today(clock), stamp(clock)
    rows, failures = [], []
    for slug, url in urls:
        try:
            http, body, headers = fetcher(url)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            failures.append((slug, url, str(e)[:200]))
            continue
        digest = hashlib.sha256(body).hexdigest()
        prev = previous_digest(dest, slug)
        name = f"{slug}-{day}.html"
        # Byte-for-byte. write_bytes, never write_text: re-encoding a document
        # you may have to authenticate later is quietly destroying the exhibit.
        (dest / name).write_bytes(body)
        row = {"retrieved_at": when, "slug": slug, "url": url, "http": http,
               "bytes": len(body), "sha256": digest,
               "last_modified": headers.get("Last-Modified", ""),
               "etag": headers.get("ETag", ""),
               "changed_from_previous": "" if not prev else str(digest != prev).lower(),
               "file": name}
        append_manifest(dest, row)
        rows.append(row)
    return rows, failures


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fetch", action="store_true",
                    help="actually make the requests (without this: dry run)")
    ap.add_argument("--dest", default=str(DEST))
    ap.add_argument("--fail-on-change", action="store_true",
                    help="exit non-zero when a page differs from the last "
                         "snapshot — how CI turns drift into an alarm")
    args = ap.parse_args(argv)
    dest = Path(args.dest)

    if not args.fetch:
        print("DRY RUN — no request made. Would snapshot into", dest)
        for slug, url in TERMS_URLS:
            print(f"  {slug:<20} {url}")
        print("Re-run with --fetch to take the snapshot.")
        return 0

    # The guard, before anything is fetched: refusing after the download would
    # leave the bytes in a tracked directory for whatever runs next to commit.
    if not is_ignored(dest):
        print(f"REFUSING to write to {dest}: git does not ignore it.\n"
              f"These files are a third party's copyrighted terms and this "
              f"repository is public. Add the directory to .gitignore first.",
              file=sys.stderr)
        return 2

    rows, failures = snapshot(dest=dest)
    for r in rows:
        state = ("first snapshot" if r["changed_from_previous"] == ""
                 else "CHANGED since the last snapshot"
                 if r["changed_from_previous"] == "true" else "unchanged")
        print(f"{r['slug']:<20} {r['http']} {r['bytes']:>8,}B  {r['sha256'][:12]}  {state}")
    for slug, url, err in failures:
        print(f"{slug:<20} FAILED {url}: {err}", file=sys.stderr)

    changed = [r for r in rows if r["changed_from_previous"] == "true"]
    if changed:
        print("\nTERMS DRIFT: " + ", ".join(r["slug"] for r in changed) +
              " changed since the last snapshot. Both versions are on disk; "
              "diff them and send the result to counsel.")
    if failures:
        return 1
    return 3 if (changed and args.fail_on_change) else 0


# ————— THE CI JOB THIS NEEDS —————
#
# Monthly, unattended, and NOT part of the data refresh: it must keep running
# on a month when nothing is fetched or deployed, because the whole point is
# an unbroken monthly record.
#
#   schedule:  cron "0 6 1 * *"  (06:00 UTC on the 1st) + workflow_dispatch
#   steps:     checkout → python3 pipeline/snapshot_vendor_terms.py --fetch
#                          --dest "$RUNNER_TEMP/vendor-terms" --fail-on-change
#   artifact:  upload $RUNNER_TEMP/vendor-terms with a long retention. On CI
#              the snapshot CANNOT live in the working tree — the repo is
#              public and a job that commits it publishes the thing the guard
#              above exists to stop. The artifact (or a private bucket) is the
#              durable copy; the local docs/vendor-terms/ is for hand runs.
#   note:      --dest must be seeded with the previous run's MANIFEST.csv for
#              change detection to work across runs — download the prior
#              artifact first, or point --dest at private storage that
#              persists. Without that, every run reports "first snapshot",
#              which is honest but useless as an alarm.
#   exit 3:    a page changed. Fail the job loudly; that is the alarm.
#   exit 1:    a fetch failed — also worth failing on. A terms URL that stops
#              resolving is a finding, not an outage to retry past.
#
# .gitignore needs one line (the orchestrator owns that file):
#   docs/vendor-terms/

if __name__ == "__main__":
    sys.exit(main())
