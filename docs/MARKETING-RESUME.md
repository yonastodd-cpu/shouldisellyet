# Marketing queue — where this stopped (2026-08-10)

Two of the brief's three commits are in and unpushed. This file is the
handoff; delete it when the work is finished.

    a13b983  Task 1 — schema + task generation
    e8184b0  Task 2 — Marketing tab, campaign capture, nightly perf join

`pytest pipeline/ -q` is green at 113. Nothing has been pushed and **nothing
has been applied to the production database**.

## Do these two in this order, or the site starts erroring

1. **Apply the migrations.** Both are idempotent and were exercised against
   production inside a rolled-back transaction (20 behavioural checks, all
   passing — caps refusing a third weekly post, the ATTRIBUTION constraint
   refusing banned copy, anon getting `forbidden`).

   ```bash
   cd "/Users/yonastodd/Rally ETH/shouldisellyet"
   npx supabase db query --linked -f supabase/schema-repair-v20-v21.sql
   npx supabase db query --linked -f supabase/schema-v23.sql
   ```

   The repair file restores `zip_velocity` and `press_corroboration`, whose
   DDL was destroyed when the v20/v21 filenames were reused. Production
   already has those objects, so it is a no-op there — it exists so the repo
   can rebuild the database it actually runs.

2. **Then redeploy the track function.** In this order only: it now sends
   `utm_campaign`, and until step 1 lands, every insert 400s on the unknown
   column and analytics stops counting.

   ```bash
   npx supabase functions deploy track --no-verify-jwt
   ```

Before step 1 the Marketing tab is harmless — it renders a named "not
readable from this browser" state naming the missing RPC, and every other tab
keeps working.

## What is left to build

**Task 3 (the third commit).** Contract section 3 lists the manifest; the
contract itself is at
`/private/tmp/claude-501/-Users-yonastodd-Rally-ETH/d852a3ae-2954-4748-9d4f-d9a1994371c7/scratchpad/mq/contract.md`
(re-derivable — it is the reconciler output of workflow `wf_c02e29ae-e5b`).
In short: the digest rewrite replacing the archive-folder prose at
`growth_digest.py` ~509–519 with the queue link plus the top-3 why_headlines;
`pipeline/post_pack.py --render` drawing the per-task PNGs; the
`_social_frame(foot=…)` one-line change in `build_research.py`;
`web/assets/mkt/` in `.gitignore`; the `post_pack --render` step in
update.yml's every-deploy block; the CSV export button; and the three test
files.

**One known defect, already diagnosed.** `cand_record()` in
`pipeline/marketing_tasks.py` (~line 384) frames its caption as alarm
regardless of which way the record points. Against the real 2026-06 data it
renders:

> Warning signs are flashing in 62.2% of U.S. ZIP housing markets — the
> lowest share since December 2025.

The market is *improving* — third consecutive monthly decline, which the
card's own `why_detail` says out loud. `guard()` cannot catch this: the
problem is that the framing does not track the data's direction, not that a
banned word slipped through. `cand_flips()` gets this right by only firing on
an upward crossing; `cand_record()` cannot, because `strongest_record()`
legitimately returns low records. Fix: branch the caption on the record's
direction, and add a low-record fixture asserting no alarm framing.

## Operator settings still unset (by design, not oversight)

Both print a labelled line and sit out until set, in
`pipeline/marketing_config.py`:

- `MARKET_NARRATIVE` / its as-of month — the contrarian-gap rule needs a
  narrative to argue against.
- `PRESS_OUTLET_BATCHES` (or the `PRESS_LIST` secret) — no pitch tasks
  without an outlet batch.

`nextdoor_naomi` stays off, and there is no flag to flip: the channel has
zero rows in `marketing_windows`, so the conflict check refuses it by
construction. Turning it on is a dated migration INSERT (quoted in
`docs/MARKETING.md`) after a signed agreement exists — see
`docs/ATTRIBUTION.md`, correction dated 2026-08-08.
