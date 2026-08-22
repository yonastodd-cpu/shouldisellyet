#!/usr/bin/env python3
"""Turning responses into rows — parsing separated from fetching, on purpose.

Every function here is pure except the ones that take a `fetch` callable, and
that callable is always passed in. Nothing in this file imports transport.py.
Two things follow, and both matter more than the tidiness:

  * the parsers are tested against fixture bytes, so the schema is exercised
    without a single request being made — which is the whole shape of this
    task: build it, prove it, do not run it;
  * the day counsel says yes, the only new moving part is a real `fetch`, and
    everything downstream of it has already been proven.

WHICH BODIES GET FETCHED, AND WHY NOT ALL OF THEM. Stage 1 lists captures;
stage 2 fetches stored bodies to answer whether a withdrawn figure is visible.
At full scope stage 1 is ~91,000 index queries and stage 2 could be an order
of magnitude more. The default fetches every in-window capture — those are the
exhibit — plus the FIRST capture after the last window closes for that URL.
That last one is the control: it is what shows the archive holding a clean
copy after the withdrawal, which is the difference between "we found old
copies" and "we found old copies and here is where they stop".
"""

import json

import detect
import sources
import windows
import writer


def parse_cdx(payload):
    """CDX JSON -> [{field: value}]. Tolerates the empty answer.

    The archive returns a bare `[]` (or an empty body) for a URL it has never
    captured, and the first row of a non-empty answer is the field names, not
    a capture. Treating that header as a capture would put a row dated
    "timestamp" into an evidence file.
    """
    if not payload or not payload.strip():
        return []
    data = json.loads(payload)
    if not data:
        return []
    header, *rest = data
    return [dict(zip(header, row)) for row in rest]


def _classify_capture(target, cap):
    when = windows.parse_cdx(cap["timestamp"])
    hit = windows.matched(target.windows, when)
    return when, hit


def _body_wanted(target, captures, policy):
    """The indices whose stored bodies stage 2 should fetch."""
    if policy == "none":
        return set()
    if policy == "all":
        return set(range(len(captures)))
    wanted, first_after = set(), None
    for i, cap in enumerate(captures):
        try:
            _, hit = _classify_capture(target, cap)
        except ValueError:
            continue
        if hit:
            wanted.add(i)
        elif first_after is None:
            first_after = i
    if first_after is not None:
        wanted.add(first_after)
    return wanted


def webarchive_rows(target, fetch, *, body_policy="in-window", limit=500):
    """Rows for one target across every spelling of its URL.

    A URL with no captures still produces a row. "The archive holds nothing
    for /s/20601/" is a survey finding and has to be visible as one; an absent
    row is indistinguishable from a URL nobody remembered to check.
    """
    cdx_mech = sources.BY_ID["wayback_cdx"]
    snap_mech = sources.BY_ID["wayback_snapshot"]
    rows = []
    for variant in target.variants:
        status, body, err = fetch(sources.cdx_url(variant, limit=limit))
        if body is None:
            rows.append(writer.survey_row(
                target, variant, cdx_mech, http_status=status,
                note=f"capture index not retrieved — {err or 'no body'}"))
            continue
        try:
            captures = parse_cdx(body)
        except ValueError as e:
            rows.append(writer.survey_row(
                target, variant, cdx_mech, http_status=status,
                note=f"capture index unparseable — {type(e).__name__}"))
            continue
        if not captures:
            rows.append(writer.survey_row(
                target, variant, cdx_mech, http_status=status,
                verdict=detect.CLEAN,
                note="no captures held for this URL spelling"))
            continue
        if len(captures) >= limit:
            # Silence here would understate exposure, which is the direction
            # of error this survey cannot afford.
            rows.append(writer.survey_row(
                target, variant, cdx_mech, http_status=status,
                note=f"TRUNCATED: the index returned the {limit}-row cap; "
                     f"re-run this URL with a higher --cdx-limit before "
                     f"treating its capture list as complete"))
        wanted = _body_wanted(target, captures, body_policy)
        for i, cap in enumerate(captures):
            try:
                when, hit = _classify_capture(target, cap)
            except ValueError as e:
                rows.append(writer.survey_row(
                    target, variant, cdx_mech,
                    capture_id=str(cap.get("timestamp", ""))[:32],
                    note=f"unreadable capture timestamp — {e}"))
                continue
            retrieval = sources.snapshot_url(cap["timestamp"], cap.get("original", variant))
            verdict, evidence, note = detect.NOT_FETCHED, "", ""
            if i in wanted:
                s2, snap, serr = fetch(retrieval)
                verdict, evidence = detect.classify(snap, target.url)
                if snap is None:
                    note = f"stored body not retrieved — {serr or 'no body'}"
            else:
                note = ("body not fetched: outside the exposure window and not "
                        "the first capture after it")
            rows.append(writer.survey_row(
                target, variant, snap_mech if i in wanted else cdx_mech,
                capture_utc=windows.to_iso(when),
                capture_id=cap["timestamp"],
                in_window="yes" if hit else "no",
                windows_matched=";".join(hit),
                http_status=cap.get("statuscode", ""),
                mime=cap.get("mimetype", ""),
                digest=cap.get("digest", ""),
                retrieval_url=retrieval,
                verdict=verdict, evidence=evidence, note=note))
    return rows


def blocked_rows(target, source):
    """One row per mechanism we could not run, saying why.

    This is most of the searchcache and socialpreview output, and it is the
    point of including those sources at all. The finding counsel needs from
    them is not "nothing was cached" — we cannot know that — it is "no
    credential-free way exists to find out, and here is each mechanism and the
    specific reason".
    """
    out = []
    for q in sources.plan_for(target, source):
        if q.mechanism.availability == sources.PUBLIC:
            continue
        out.append(writer.survey_row(
            target, q.variant, q.mechanism,
            note=f"not checked — {q.blocked_reason}"))
    return out


def collect_source(targets, source, fetch, *, body_policy="in-window",
                   limit=500, progress=None):
    """Every row for one source. `fetch` is injected; nothing here opens one."""
    rows = []
    for n, t in enumerate(targets, 1):
        if source == sources.WEBARCHIVE:
            rows += webarchive_rows(t, fetch, body_policy=body_policy, limit=limit)
        rows += blocked_rows(t, source)
        if progress:
            progress(n, len(targets), t)
    return rows
