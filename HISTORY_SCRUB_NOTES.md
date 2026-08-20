# History scrub — what happened, what you must do next

Ran 2026-08-19 with `git filter-repo`. **The rewrite is local only. Nothing
has been pushed.** Until you force-push, GitHub still serves the old history.

## What was removed

71 paths, 529 objects, across all three branches. `.git` went 70 MB → 6.5 MB.

| Path | Files |
|---|---|
| `web/data/zips/*.json` | 51 |
| `web/data/cases/*-*.json` + `.png` | 8 |
| `pipeline/cases/*` | 8 |
| `pipeline/rentcast_stats.csv` | 1 |
| `pipeline/snapshots/verdicts-*.json` | 3 |

Deliberately kept: `web/data/cases/index.json` (derived indicators only) and
`pipeline/data/page_manifest.csv` (zip,state — postal geography).

Verified after the rewrite, against the rewritten refs rather than the
command's exit code: **0** purged paths in any commit on any branch, **0**
purged objects reachable in the repo, working tree intact, 384 tests passing.
The remaining `peak_to_trough` matches are in `build_stories.py`,
`build_research.py` and `CASE_STUDY_AUDIT.md` — code and prose naming a field,
not data.

## Step 1 — force-push all three branches

`main` and `legacy/redfin` are both on GitHub and both were rewritten.

```
git push --force-with-lease origin main
git push --force-with-lease origin legacy/redfin
```

`--force-with-lease` rather than `--force`: it refuses if someone else pushed
since your last fetch, which plain `--force` would silently overwrite.

`backup-local` is local-only and should NOT be pushed. It is your pre-rewrite
safety copy and it also exists in the bundle.

## Step 2 — re-clone anywhere else this repo exists

Every existing clone still holds the old history and will try to merge it back.
Do not pull. Delete and re-clone:

```
git clone https://github.com/yonastodd-cpu/shouldisellyet.git
```

That includes any other machine, any CI cache, and any editor working copy.

## Step 3 — secrets

**Nothing to rotate.** The pre-scrub audit scanned all 293 commits for Stripe
keys, AWS keys, private keys and `.env` files and found none — every match was
an environment-variable *read* or documentation. The `eyJ…` tokens in
`index.html`, `admin.html` and `subscribe.html` decode to `"role":"anon"`, the
Supabase anon key, which is public by design with RLS as the boundary.

There is deliberately no `SECRETS_TO_ROTATE.md`; an empty checklist reads like
a completed one.

## Step 4 — the part the force-push does not do

A force-push rewrites the branch. It does not remove the old objects from
GitHub's servers.

- **Old commits stay reachable by SHA.** Anyone with a commit hash — from a
  link, a notification email, a CI log — can still fetch it until GitHub runs
  garbage collection, which is not on a schedule you control.
- **Pull requests keep their own copies.** PR refs are not rewritten.
- **Forks keep everything.** A fork is an independent repository; nothing you
  do to yours touches it.
- **Cached views persist.** GitHub caches rendered commit and blob pages.

**To finish it properly, contact GitHub Support** and ask them to garbage-
collect unreachable objects and purge cached views for
`yonastodd-cpu/shouldisellyet`, citing the removal of third-party licensed
data. Give them the branch names (`main`, `legacy/redfin`) and say the data
was removed by history rewrite on 2026-08-19. This is the only way to close
the gap, and it is worth doing before telling counsel the removal is complete.

## Step 5 — record the date

The counsel memo's Q1 timeline has one line still marked pending:

> Public repository availability of all Redfin-derived files ended [date].

That date is when the force-push lands, not today. Fill it in then, and note
separately when GitHub confirms the cache purge — they are different facts and
the second one is the one that makes the first true.

## If something is wrong

Your pre-rewrite state is in two places:

```
git clone ~/sisy-backup-2026-08-19.bundle recovered
```

and the full folder copy at `~/sisy-backup-2026-08-19-full`. Both were
verified before the rewrite: the bundle carries all three branches, and the
folder copy carries the ignored files a clone would not.

Do not delete either until the force-push has landed and the site has
deployed cleanly at least once.
