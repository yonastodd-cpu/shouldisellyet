# Moving research state out of the public repository

**Status: COMPLETE, 2026-08-23.** The files are out of the repository and the
store is the source of truth. Kept for the record of how it was done.

## The problem

`pipeline/research/levels-{month}.json` and `streaks.json` are pipeline inputs —
`research.load_levels(prev)` reads the prior month to count how many ZIPs crossed
into WATCH or ACT. They were also committed, and this repository is public:

| file | ZIP→rating pairs | of which the ZIP's own page withholds a rating |
| --- | ---: | ---: |
| `levels-2026-05.json` | 24,448 | **19,448** |
| `levels-2026-06.json` | 25,133 | **20,133** |
| `levels-2026-07.json` | 25,372 | **20,373** |
| `streaks.json` | 15,714 | **13,455** |

The release page says "We do not publish the list." These files did.

## Why it is two steps

Deleting them first breaks the next build, and worse than breaking it: with no
prior month, every ZIP looks new, nothing looks like a crossing, and the release
page publishes **"0 ZIP markets moved"** — wrong, and publishable, with no error
anywhere. `research.load_levels` now raises rather than allowing that, but a
raise still means a failed build if the store was never seeded.

So: seed the store, prove it can be read back, then remove the files.

## Step 1 — done

- `supabase/schema-v40.sql` — `public.research_state`, one row per artifact,
  RLS on with **no permissive policy**, so only the service role can read it.
- `pipeline/research_store.py` — the adapter. No credentials → returns `None`
  and the caller falls back to files, so local runs behave as before.
- `research.save_levels` and the streaks write now go to **both** store and file.
- `research.load_levels` reads store first, file second, and **raises** on a
  miss unless the caller passes `required=False` (true only for the first month).
- `marketing_tasks.load_streaks` reads store first; a miss there costs a
  marketing candidate, not a published figure, so it still degrades quietly.
- `research.py --seed-store` uploads the committed files and reads them back.
  Exits non-zero if nothing was written or the read-back fails.

## Step 2 — done, 2026-08-23

1. **Schema applied.** `supabase/schema-v40.sql` against production. Verified by
   querying `pg_policies` and `role_table_grants` rather than by reading the
   migration back: RLS on, **zero policies**, and `anon`/`authenticated` hold no
   grants at all.
2. **Store seeded.** Four keys — 24,448 / 25,133 / 25,372 / 15,714 entries. The
   `rows` column matches an actual `jsonb_object_keys` count for every one.
3. **Verified through the build's own path**, which is not the path it was
   seeded on. The schema and rows went in over the CLI's Management API; the
   build reads PostgREST with a service key. The `seed-research-store` CI job
   holds that key and reported *"4 key(s) written and read back."*
4. **Proved the build works without the files.** `--verify-store` points
   `levels_path()` at an empty directory, forcing every read through the store,
   and recomputes July's flip count with `build_month_report`'s own predicate:

   ```
   verify-store: recomputed 2026-07 flips from the store = 2,403; published count = 2,403
   ```

5. **Removed.** `git rm --cached` plus a `.gitignore` entry. The files remain on
   disk as a local cache — `save_levels` still dual-writes — so a machine that
   has run a build keeps working without credentials. CI has no copy.

Tests were run in both states before removal: 515 pass with the files, 511 pass
and 7 skip without them, nothing fails. The skips are the file-fallback tests,
which are marked rather than deleted so they still cover that path anywhere the
files exist.

## What this does not do

Removing the files from HEAD does not remove them from the history of a public
repository. Anyone with a commit reference can still fetch them, exactly as with
the objects covered by GitHub ticket #4688700. Closing that needs the same
conversation with counsel and the same judgement about whether a history rewrite
is worth its own risks — **`LEGAL_HOLD.md` currently forbids one.**

Copies as they stood are preserved in the archive under
`06-per-zip-research-as-committed/`, so nothing was destroyed to do this.
