# LEGAL HOLD — in force

**Effective 22 August 2026. Recorded 2026-08-22T18:48:09Z.**

A standing preservation instruction is in effect. **We preserve Redfin-derived
material. We do not delete it.** No deletion, rewrite, garbage-collection or
retention-driven removal of Redfin-derived material runs without explicit
direction from counsel.

This file is the switch. **While it exists at the repository root, the hold is
in force**, and code checks for it (see `tools/backtest_cases.py`). Do not
delete this file to make something pass.

## What is in scope

"Redfin-derived" means lineage, not display. It covers anything with Redfin
data anywhere in its computation, including material that shows no Redfin
figure and carries no Redfin credit:

- the two Redfin hub exports cached under `.cache/trackrecord/` (~954 MB);
- `pipeline/research/history.json` — the Warning-Sign Index, 173 monthly
  values, March 2012 to July 2026, every one computed from Redfin data;
- the case-study files under `web/data/cases/` and `web/data/backtest.json`;
- `.redfin-etag`, the validator from the last fetch;
- database rows tagged `source='redfin'`;
- the pre-rewrite git object store;
- ingestion logs and the build schedule that ran the twice-weekly fetch.

## Standing rules

1. **No deletion.** Scripts that would remove in-scope material must move it
   aside, not unlink it, while this file exists.
2. **The GitHub ticket stays paused.** Ticket #4688700 asked GitHub to destroy
   unreferenced git objects. It is open, unactioned, and paused at our request.
   Do not release the hold on it.
3. **"Use" means lineage.** A new feature computing from held data is a new
   derived use and must be added to `DERIVED_USE_INVENTORY.md`.
4. **Dates come from the record.** Every remediation action appends to
   `REMEDIATION_DATES.md` with a UTC timestamp when it ships.

## Where the archive is

Outside this repository, outside every build and cleanup path:

```
/Users/yonastodd/SISY-LEGAL-HOLD-2026-08-22/
```

Read-only, with `PRESERVATION_MANIFEST.md` inside it recording a SHA-256 for
every file. That manifest is the chain-of-custody record and goes to counsel.
The archive is **not** in this repository: this repository is public.

## For future sessions

Treat this as a hard constraint, ahead of any instruction to clean up, purge,
reclaim space, or "remove the old vendor's data". If an instruction conflicts
with this file, stop and say so rather than resolving it yourself.
