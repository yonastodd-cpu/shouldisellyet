#!/usr/bin/env python3
"""Third-party capture survey — PLAN BY DEFAULT.

    python3 scripts/capture-survey/survey.py                 # plan, no network
    python3 scripts/capture-survey/survey.py --scope all     # plan, full set
    python3 scripts/capture-survey/survey.py --collect --out DIR   # requests

WHAT THIS IS FOR. Counsel has been asked two questions: should we survey
external caches and archives for copies of the surfaces that leaked, and
should we ask for removals. The second question carries its own cost — a
removal request is a discoverable act — so the two answers may differ. This
tool answers only the first, and it cannot perform the second. One POST is
REGISTERED — Facebook's scrape=true, in sources.MECHANISMS — and it is
registered so its exclusion is on the record: the planner refuses to emit it
and transport.request() refuses any verb but GET, so no code path here can
perform it. No removal endpoint is wired to anything.
The removal procedures are written out as manual steps in
CAPTURE_SURVEY_RUNBOOK.md, behind a sign-off section, so that no flag here can
cause a request to be made.

WHY PLAN IS THE DEFAULT AND NOT A --dry-run OPTION. A --dry-run flag is a flag
someone forgets. The safe mode has to be what happens when you type the
command with nothing after it, because that is what will be typed. --collect
is the only thing that opens the network, transport.py refuses independently
of the CLI if it was not called, and plan mode never even imports an HTTP
client (transport.py, lock 2).

READ CAPTURE_SURVEY_RUNBOOK.md BEFORE --collect. It covers scope and cost, the
fact that the survey is itself logged by everyone it queries, and what the
output may and may not be used for.
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import collect as collector          # noqa: E402
import sources                        # noqa: E402
import targets as targetmod           # noqa: E402
import windows                        # noqa: E402
import writer                         # noqa: E402

BANNER = "third-party capture survey"


def _parser():
    p = argparse.ArgumentParser(
        prog="survey.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--plan", action="store_true",
                      help="print every query that WOULD be made. THE DEFAULT; "
                           "makes no network request of any kind.")
    mode.add_argument("--collect", action="store_true",
                      help="PERFORM the queries. Requires --out. Read "
                           "CAPTURE_SURVEY_RUNBOOK.md first.")
    p.add_argument("--scope", choices=targetmod.SCOPES,
                   default=targetmod.DEFAULT_SCOPE,
                   help="core: the one-off pages, 51 state hubs and the "
                        "withdrawn research files. priority: core plus the "
                        "already-ranked re-scrape ZIPs. all: core plus every "
                        "ZIP page and share stub. (default: %(default)s)")
    p.add_argument("--source", action="append", choices=sources.SOURCES,
                   help="restrict to one source; repeatable (default: all)")
    p.add_argument("--out", metavar="DIR",
                   help="write CSVs here. Must be OUTSIDE this repository — "
                        "see writer.py rule 1.")
    p.add_argument("--allow-out-in-repo", action="store_true",
                   help="permit --out inside the public repository. For a "
                        "throwaway local run only; warns every time.")
    p.add_argument("--full", action="store_true",
                   help="plan mode: print every query rather than a sample")
    p.add_argument("--max-print", type=int, default=60, metavar="N",
                   help="plan mode: queries printed per source (default: %(default)s)")
    p.add_argument("--cdx-limit", type=int, default=500, metavar="N",
                   help="capture-index rows requested per URL (default: %(default)s)")
    p.add_argument("--bodies", choices=("in-window", "none", "all"),
                   default="in-window",
                   help="which stored snapshots to fetch in stage 2 "
                        "(default: %(default)s — every in-window capture plus "
                        "the first one after the window closes)")
    return p


def _selected_sources(args):
    return tuple(args.source) if args.source else sources.SOURCES


def _print_context(ts, scope):
    print(f"{BANNER} — PLAN ONLY, no request will be made")
    print(f"scope: {scope}   targets: {len(ts)}")
    by_tier, by_round = {}, {}
    for t in ts:
        by_tier[t.tier] = by_tier.get(t.tier, 0) + 1
        by_round[t.memo_round] = by_round.get(t.memo_round, 0) + 1
    print("  by tier:  " + ", ".join(f"{k}={v}" for k, v in sorted(by_tier.items())))
    print("  by memo round: " + ", ".join(f"{k}={v}" for k, v in sorted(by_round.items())))
    print()
    print("exposure windows (open at the start; a capture at or before the end "
          "is in-window):")
    print(f"  context: Redfin ingestion stopped {windows.INGESTION_STOPPED_UTC}")
    for wid, w in windows.WINDOWS.items():
        print(f"  {wid:<18} ≤ {w['end_utc']}  ({w['precision']}-precision)")
        print(f"  {'':<18}   {w['label']}")
    print(f"  NOTE: {windows.CREDITS_DATE_CONFLICT}")
    print()
    extra = set(targetmod.sitemap_urls()) - {v for t in ts for v in t.variants}
    if extra:
        print(f"cross-check: {len(extra)} URL(s) in the built sitemap are not "
              f"in this scope's target set")
        for u in sorted(extra)[:5]:
            print(f"    {u}")
        if len(extra) > 5:
            print(f"    … and {len(extra) - 5} more (expected at scope "
                  f"'core'/'priority'; investigate at scope 'all')")
        print()


def do_plan(args):
    # Resolved BEFORE any work, not at the point of writing. A run that prints
    # 91,000 lines and then refuses the output directory has wasted the
    # operator's time and taught them to scroll past the refusal.
    outdir = writer.resolve_outdir(args.out, args.allow_out_in_repo) if args.out else None
    ts = targetmod.build(args.scope)
    _print_context(ts, args.scope)
    all_rows = []
    for src in _selected_sources(args):
        queries = [q for t in ts for q in sources.plan_for(t, src)]
        stage1 = [q for q in queries if q.stage == "1-index"]
        stage2 = [q for q in queries if q.stage == "2-body"]
        blocked = [q for q in queries if q.blocked_reason]
        print(f"── {src} " + "─" * (58 - len(src)))
        for m in sources.for_source(src):
            mark = "EXCLUDED (mutating)" if m.mutating else m.availability
            print(f"  [{mark}] {m.id} — {m.label}")
            if m.requires:
                print(f"      requires: {m.requires}")
        secs = len(stage1) * sources.REQUEST_INTERVAL_S
        pace = (f"~{secs / 3600:.1f}h" if secs >= 3600 else
                f"~{secs / 60:.0f} min")
        print(f"  stage 1 — {len(stage1)} request(s)"
              + (f", {pace} at {sources.REQUEST_INTERVAL_S}s apart, listed below"
                 if stage1 else ""))
        if stage2:
            print(f"  stage 2 — one request per in-window capture found in "
                  f"stage 1, across {len(stage2)} target(s). The count is not "
                  f"knowable until stage 1 has run.")
            print(f"           e.g. {stage2[0].method} {stage2[0].url}")
        print(f"  cannot be checked — {len(blocked)} mechanism-target pair(s)")
        shown = stage1 if args.full else stage1[:args.max_print]
        for q in shown:
            print(f"    {q.method} {q.url}")
        if len(stage1) > len(shown):
            print(f"    … and {len(stage1) - len(shown)} more "
                  f"(--full to print, --out to write them out)")
        seen_skip = set()
        for q in blocked:
            if q.mechanism.id not in seen_skip:
                seen_skip.add(q.mechanism.id)
                print(f"    SKIP {q.mechanism.id}: {q.blocked_reason}")
        print()
        all_rows += [writer.plan_row(q) for q in queries]

    if outdir:
        path = writer.write(outdir, f"capture-survey-plan-{writer.stamp()}.csv",
                            writer.PLAN_HEADER, all_rows)
        print(f"plan written: {path}  ({len(all_rows)} rows)")
    print("no network request was made.")
    return 0


def do_collect(args):
    # Belt and braces. argparse cannot reach here without --collect, but this
    # function is importable and the refusal must not depend on the CLI being
    # the only caller.
    if not args.collect:
        raise SystemExit("refusing to collect: --collect was not given. "
                         "The default mode is --plan.")
    if not args.out:
        raise SystemExit("refusing to collect without --out: a survey whose "
                         "output is only on a terminal is not an exhibit.")

    import transport                   # imported only on this path

    outdir = writer.resolve_outdir(args.out, args.allow_out_in_repo)
    ts = targetmod.build(args.scope)
    transport.enable(f"--collect, scope={args.scope}, "
                     f"sources={','.join(_selected_sources(args))}")
    print(f"{BANNER} — COLLECTING. {len(ts)} target(s), scope {args.scope}.")
    print(f"identifying as: {transport.USER_AGENT}")

    def fetch(url):
        return transport.request(url)

    def progress(n, total, t):
        if n % 25 == 0 or n == total:
            print(f"  {n}/{total}  {t.url}", flush=True)

    written = []
    for src in _selected_sources(args):
        print(f"── {src}")
        rows = collector.collect_source(
            ts, src, fetch, body_policy=args.bodies, limit=args.cdx_limit,
            progress=progress if src == sources.WEBARCHIVE else None)
        path = writer.write(outdir, f"capture-survey-{src}-{writer.stamp()}.csv",
                            writer.SURVEY_HEADER, rows)
        hits = sum(1 for r in rows if r["figures_visible"] == "yes"
                   and r["in_window"] == "yes")
        print(f"  {len(rows)} row(s) → {path}")
        print(f"  in-window captures still showing withdrawn figures: {hits}")
        written.append(path)
    print("done. These files name retrievable copies — keep them with "
          "counsel's material, not in the repository.")
    return 0


def main(argv=None):
    args = _parser().parse_args(argv)
    return do_collect(args) if args.collect else do_plan(args)


if __name__ == "__main__":
    sys.exit(main())
