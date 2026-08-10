-- ShouldISellYet schema v24 — run AFTER schema-v23.sql (idempotent).
--
-- ————— Bug fix: the dedupe index could not be inferred —————
--
-- v23 created the idempotency index as a PARTIAL unique index:
--
--   create unique index marketing_tasks_dedupe_idx
--     on public.marketing_tasks (dedupe_key) where dedupe_key is not null;
--
-- and the generator writes rows through PostgREST with
-- `?on_conflict=dedupe_key` + `Prefer: resolution=ignore-duplicates`, which
-- emits `ON CONFLICT (dedupe_key) DO NOTHING`. Postgres cannot infer a
-- PARTIAL index from a bare column list — the arbiter clause has to repeat the
-- predicate — so every one of those inserts raised
--
--   42P10: there is no unique or exclusion constraint matching the
--          ON CONFLICT specification
--
-- Found on 2026-08-10 while filling the queue for the first time: the row
-- INSERTs failed against production even though the schema, the generator and
-- 125 tests were all green, because nothing in the test suite speaks PostgREST
-- — the writer is monkeypatched out in every test, which is exactly the seam
-- a bug like this lives in.
--
-- THE PREDICATE WAS NEVER LOAD-BEARING. dedupe_key is nullable, and in a
-- Postgres unique index NULLs are distinct: many rows may carry a NULL key
-- with or without the WHERE clause. The partial form bought nothing and cost
-- inference, so it goes. Same reasoning does NOT apply to
-- marketing_tasks_campaign_idx or marketing_tasks_slot_idx: nothing does an
-- upsert on those, and slot_idx's predicate (status <> 'skipped') is the
-- actual rule — a skipped row must release its slot.

drop index if exists public.marketing_tasks_dedupe_idx;

create unique index if not exists marketing_tasks_dedupe_idx
  on public.marketing_tasks (dedupe_key);
