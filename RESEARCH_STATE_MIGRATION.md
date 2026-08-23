# Moving research state out of the public repository

**Status: step 1 of 2 done. The files are still committed. Do not remove them yet.**

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

## Step 2 — not done, and here is exactly what it needs

1. **Apply the schema.** `supabase/schema-v40.sql` against the project.
2. **Seed the store.** Either run the `seed-research-store` job in
   `.github/workflows/compliance-monthly.yml` (workflow_dispatch), or locally
   with `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` set:
   ```
   python3 pipeline/research.py --seed-store
   ```
   It must print `written and read back` and exit 0. **If it does not, stop.**
3. **Prove the build reads the store, not the files.** Move the files aside
   temporarily and run the monthly build; the flip count must still come out at
   2,403 for July. If it comes out 0 or raises, the store is not seeded.
4. **Then remove the files** — `git rm --cached` plus a `.gitignore` entry, in
   their own commit. Git history retains them, and copies are already preserved
   under `LEGAL_HOLD.md` in `06-per-zip-research-as-committed/`.

## What this does not do

Removing the files from the repo's HEAD does not remove them from its history,
and this repository is public. Anyone with a commit reference can still fetch
them, exactly as with the objects covered by GitHub ticket #4688700. Closing
that requires the same conversation with counsel, and the same decision about
whether a history rewrite is worth its own risks — **`LEGAL_HOLD.md` currently
forbids one.**
