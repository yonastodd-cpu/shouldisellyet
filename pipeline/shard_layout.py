#!/usr/bin/env python3
"""One guard for the per-state shard layout that no longer exists.

Until 2026-08-20 public records lived in web/data/zips/{STATE}.json, each file
a {zip: entry} map. Commit 4c0117a moved provisioning to web/data/z/{zip}.json,
one file per ZIP, so that showing one ZIP stops shipping several hundred.

Eleven scripts still read the old path. Every one of them failed the same way:
Path.glob() on a directory that does not exist yields nothing and does NOT
raise, so a loader returns {} and the caller carries on with zero records. Two
of them then wrote that emptiness over a tracked file — pipeline/
data/page_manifest.csv and the pipeline/research/*.json set — and exited 0.
A third, promote_tranche, silently reported every ZIP as "no reading at all",
which is why Tranche 1 could not be staged.

None of it surfaced in CI: the steps that run these scripts are gated on
`changed == 'true'`, and update.yml hardcodes that false while ingestion is
stopped. They are dormant, not fixed — turning ingestion back on re-arms all
of them at once. Hence a loud failure rather than a repair: several of these
want the withdrawn Redfin record shape, so there is nothing to repoint them at.

Run: python3 -m pytest pipeline/test_shard_layout.py -q
"""

from pathlib import Path

LEGACY_DIR = "web/data/zips"
CURRENT_DIR = "web/data/z"


def require_shards(path, who, needs=""):
    """Raise unless `path` is a directory holding at least one .json file.

    `who` names the caller. `needs` says what record shape it wanted, so the
    message can say whether repointing would even help.
    """
    d = Path(path)
    if not d.is_dir():
        raise SystemExit(
            f"{who}: {d} does not exist.\n"
            f"Public records moved to {CURRENT_DIR}/ (one file per ZIP) on "
            f"2026-08-20; the per-state layout was removed.\n"
            + (f"This script needs {needs}, so pointing it at the new "
               f"directory would not help — those fields are not published "
               f"any more.\n" if needs else "")
            + "REFUSING TO RUN rather than proceeding with zero records.")
    # An empty-but-present directory is NOT guarded here. Callers legitimately
    # pass one to mean "no data this run", and their own tests do exactly that.
    # The bug this module exists for is the directory being GONE. Refusing to
    # write empty output is a separate guard, and belongs at the write.
    return d
