#!/usr/bin/env python3
"""Gate C — no code path reads a prior-vendor table without a guard.

Static analysis, no network, no credentials: safe to run on every deploy and on
a fork. It answers one question — for every request to a table that holds
source='redfin' rows, does a guard appear BEFORE the request, inside the same
function?

WHY FUNCTION SCOPE AND NOT PROXIMITY. The first version of this check looked
back a fixed 400 characters from each request. The real guard in
upsert_velocity.py sits 888 characters earlier, so a correct implementation read
as a failure and a genuine gap would have read as a pass at 401 characters. The
distance between a guard and the thing it guards is not a property worth
measuring; whether it dominates the call is.

Run: python3 scripts/gate-db-tripwire.py
Exit 0 clean, 1 on any unguarded access.
"""
import ast
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Tables whose rows carry, or default to, the prior vendor's tag.
# schema-v34 declares `source text not null default 'redfin'`.
GUARDED_TABLES = ("zip_velocity",)
# Matched against IDENTIFIERS pulled from an if-test by _guard_names(), so no
# call parentheses here -- an earlier version required "shows_velocity()" and
# therefore never matched the bare name the AST hands back, failing every
# correctly-guarded call site.
GUARD = re.compile(r"shows_velocity|VELOCITY_ENABLED")
TQ = chr(34) * 3
SQ = chr(39) * 3


def strip_comments(src, ts=False):
    # Remove comments and docstrings before looking for a guard.
    #
    # Caught by mutation-testing this file: the guard regex matched the
    # COMMENT above upsert_velocity's guard -- a paragraph explaining that
    # VELOCITY_ENABLED gates the writer -- so deleting the actual `if` left
    # the gate passing on its own documentation. A check that a comment can
    # satisfy is not a check.
    if ts:
        src = re.sub(r"/\*[\s\S]*?\*/", "", src)
        return re.sub(r"//[^\n]*", "", src)
    src = re.sub(re.escape(TQ) + r"[\s\S]*?" + re.escape(TQ), "", src)
    src = re.sub(re.escape(SQ) + r"[\s\S]*?" + re.escape(SQ), "", src)
    return re.sub(r"#[^\n]*", "", src)



def python_files():
    return sorted(glob.glob(os.path.join(ROOT, "pipeline", "*.py")))


def ts_files():
    return sorted(glob.glob(os.path.join(ROOT, "supabase", "functions", "*", "index.ts")))


def _guard_names(node):
    """Identifiers referenced in a control-flow test."""
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)} | \
           {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)}


def check_python(path, table):
    """Does an `if` that TESTS the flag dominate the request?

    AST, not text. Two earlier versions of this check were satisfied by things
    that are not guards: first the explanatory comment above the guard, then —
    after comments were stripped — the identifier appearing inside the skip
    message's own string literal, `print("... VELOCITY_ENABLED is off ...")`.
    Both times deleting the actual `if` left the gate green.

    A guard is a branch, so ask the tree for a branch: an If node whose TEST
    mentions the flag, appearing on an earlier line than the request.
    """
    src = open(path, encoding="utf-8", errors="replace").read()
    needle = f"/rest/v1/{table}"
    if needle not in src:
        return []
    tree = ast.parse(src)
    out = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        seg = ast.get_source_segment(fn=fn, source=src) if False else (ast.get_source_segment(src, fn) or "")
        if needle not in seg:
            continue
        # line of the request, absolute
        req_line = fn.lineno + seg[:seg.index(needle)].count("\n")
        guard_line = None
        for node in ast.walk(fn):
            if isinstance(node, ast.If) and GUARD.search(" ".join(_guard_names(node.test))):
                if node.lineno < req_line and (guard_line is None or node.lineno < guard_line):
                    guard_line = node.lineno
        out.append((f"{os.path.relpath(path, ROOT)}::{fn.name}", guard_line is not None))
    return out


def check_ts(path, table):
    src = open(path, encoding="utf-8", errors="replace").read()
    needle = f"/rest/v1/{table}"
    if needle not in src:
        return []
    clean = strip_comments(src, ts=True)
    g = GUARD.search(clean)
    ok = bool(g) and needle in clean and g.start() < clean.index(needle)
    return [(os.path.relpath(path, ROOT), ok)]


def main():
    rows = []
    for table in GUARDED_TABLES:
        for f in python_files():
            rows += check_python(f, table)
        for f in ts_files():
            rows += check_ts(f, table)

    if not rows:
        print("gate C: FAIL — found no access to a guarded table at all. "
              "Either the table was renamed or this check has stopped looking "
              "in the right place; a check that finds nothing is not a pass.")
        return 1

    bad = [n for n, ok in rows if not ok]
    for name, ok in sorted(rows):
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    if bad:
        print(f"\ngate C: FAIL — {len(bad)} unguarded access to a prior-vendor table")
        return 1
    print(f"\ngate C: PASS — {len(rows)} access(es), every one guarded in its own scope")
    return 0


if __name__ == "__main__":
    sys.exit(main())
