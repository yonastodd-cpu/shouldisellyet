#!/usr/bin/env python3
"""The output schema, and the two rules about where it may be written.

ONE CSV PER SOURCE, ONE SCHEMA FOR ALL THREE. Counsel receives three files
that can be opened side by side and diffed. The web-archive file will have
rows with dates in them and the other two will have rows saying why they have
no dates; that difference is a finding, and it only reads as a finding if the
shape is otherwise identical.

EVERY ROW CARRIES ITS OWN PROVENANCE. Not just URL and date: which mechanism
produced it, whether that mechanism was runnable, which exposure window the
date was measured against, and what the literal evidence was. A survey is a
factual exhibit — a row that cannot be re-derived from its own contents is a
row someone has to come back and ask about.

RULE 1 — OUTPUT GOES OUTSIDE THIS REPOSITORY BY DEFAULT. This repository is
public. .gitignore already keeps AUDIT_REPORT.md, LICENSE_AUDIT.md,
GITHUB_PURGE_REQUEST.md and DERIVED_USE_INVENTORY.md out of it for one reason,
written there in full: a register of open exposures does not belong in the
same public place as the exposures. A survey naming URLs where withdrawn
figures are STILL retrievable, with the archive timestamps to fetch them by,
is that register with retrieval instructions attached. So --out must be a path
outside the repository, and --allow-out-in-repo exists only so that a
throwaway local check does not require inventing a directory. It prints a
warning every time.

RULE 2 — NEVER OVERWRITE. Filenames carry a UTC stamp and the writer refuses
an existing path. Two reasons, and the second is the real one: an output file
is dated evidence handed to counsel, and evidence that can be silently
replaced by a later run with different contents is not evidence. Refusing is
also the only behaviour compatible with the standing preservation instruction
in LEGAL_HOLD.md — nothing this tool does may remove or truncate a stored
file, and its own prior output is a stored file.
"""

import csv
from datetime import datetime, timezone
from pathlib import Path

import detect

REPO_ROOT = Path(__file__).resolve().parents[2]

# yes / no / unknown, from a detector verdict. The three-way detector verdict
# travels alongside in its own column: "yes" is the answer counsel needs and
# "rating_visible on a page whose subject is not the vocabulary" is the reason
# for it, and flattening the second into the first loses the argument.
_VISIBLE = {
    detect.FIGURES_VISIBLE: "yes",
    detect.RATING_VISIBLE: "yes",
    detect.VOCABULARY_ONLY: "no",
    detect.CLEAN: "no",
    detect.NOT_FETCHED: "unknown",
}

SURVEY_HEADER = [
    "url",                 # the canonical target URL
    "url_variant",         # the exact spelling queried (trailing slash matters)
    "surface",             # which leaking surface this URL was, per surfaces.py
    "memo_round",          # 1, 2 or 3 — the memo's rounds
    "tier",                # core / priority / bulk
    "source",              # webarchive / searchcache / socialpreview
    "mechanism",           # the registered mechanism id
    "availability",        # public / requires_credential / retired / policy_review
    "capture_utc",         # ISO 8601, or blank when nothing was captured
    "capture_id",          # the source's own capture identifier (CDX timestamp)
    "in_window",           # yes / no / n-a — the column the memo asked for
    "windows_matched",     # which exposure windows the capture falls inside
    "http_status",         # status recorded AT CAPTURE, not now
    "mime",
    "digest",              # content digest; a change here is a change on the page
    "retrieval_url",       # how to re-fetch this exact capture, for verification
    "figures_visible",     # yes / no / unknown — the memo's third column
    "visibility_verdict",  # the three-way detector verdict behind it
    "evidence",            # the literal string matched, so a human can check
    "checked_utc",         # when THIS survey looked
    "note",                # why a row is empty, or anything a reader needs
]

PLAN_HEADER = [
    "url", "url_variant", "surface", "memo_round", "tier", "windows",
    "source", "mechanism", "availability", "method", "request_url", "stage",
    "blocked_reason", "note",
]


def now_utc():
    return datetime.now(timezone.utc)


def stamp(when=None):
    return (when or now_utc()).strftime("%Y%m%dT%H%M%SZ")


def survey_row(target, variant, mechanism, *, capture_utc="", capture_id="",
               in_window="n-a", windows_matched="", http_status="", mime="",
               digest="", retrieval_url="", verdict=detect.NOT_FETCHED,
               evidence="", checked_utc=None, note=""):
    return {
        "url": target.url,
        "url_variant": variant,
        "surface": target.surface,
        "memo_round": target.memo_round,
        "tier": target.tier,
        "source": mechanism.source,
        "mechanism": mechanism.id,
        "availability": mechanism.availability,
        "capture_utc": capture_utc,
        "capture_id": capture_id,
        "in_window": in_window,
        "windows_matched": windows_matched,
        "http_status": http_status,
        "mime": mime,
        "digest": digest,
        "retrieval_url": retrieval_url,
        "figures_visible": _VISIBLE[verdict],
        "visibility_verdict": verdict,
        "evidence": evidence,
        "checked_utc": checked_utc or now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": note,
    }


def plan_row(query):
    t = query.target
    return {
        "url": t.url,
        "url_variant": query.variant,
        "surface": t.surface,
        "memo_round": t.memo_round,
        "tier": t.tier,
        "windows": ";".join(t.windows),
        "source": query.mechanism.source,
        "mechanism": query.mechanism.id,
        "availability": query.mechanism.availability,
        "method": query.method,
        "request_url": query.url,
        "stage": query.stage,
        "blocked_reason": query.blocked_reason,
        "note": query.note,
    }


def resolve_outdir(path, allow_in_repo=False):
    """The output directory, or a refusal explaining rule 1."""
    d = Path(path).expanduser().resolve()
    inside = d == REPO_ROOT or REPO_ROOT in d.parents
    if inside and not allow_in_repo:
        raise SystemExit(
            f"refusing to write survey output inside the repository: {d}\n"
            f"  This repository is public and the output names URLs where "
            f"withdrawn figures may still be retrievable, with the "
            f"timestamps to retrieve them by.\n"
            f"  Write it beside the preservation archive instead, e.g. "
            f"--out ~/SISY-LEGAL-HOLD-2026-08-22/capture-survey\n"
            f"  --allow-out-in-repo overrides this for a throwaway local run.")
    if inside:
        print(f"WARNING: writing inside the public repository ({d}). "
              f"Do not commit it; move it to counsel's directory when done.")
    d.mkdir(parents=True, exist_ok=True)
    return d


def write(outdir, name, header, rows):
    """Write one CSV. Refuses an existing path — see rule 2."""
    path = Path(outdir) / name
    if path.exists():
        raise SystemExit(f"refusing to overwrite existing output: {path}")
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return path
