-- ShouldISellYet schema v4 — run AFTER schema.sql, schema-v2.sql, schema-v3.sql
-- (safe to run anytime; idempotent).
--
-- Adds personal-number alerts: a subscriber can ask to be emailed when their
-- OWN walk-away number, equity, or lock-in cost crosses a threshold they set
-- (as opposed to the existing ZIP-level verdict-color alert, which watches
-- the market, not their specific numbers).
--
-- This is opt-in and requires the subscriber to explicitly submit their
-- calculation inputs via the save-watch edge function — see
-- supabase/functions/save-watch/index.ts. Nothing here is populated by
-- default; a subscriber who never sets a watch has null values throughout.

alter table public.subscribers
  -- Snapshot of the inputs needed to recompute their numbers monthly:
  -- {value, baselineMedian, pp, yr, bal, rate, origAmt, origYr, piti, costPct}
  add column if not exists calc_inputs jsonb,
  add column if not exists watch_metric text
    check (watch_metric in ('walkaway', 'equity', 'lockin')),
  add column if not exists watch_direction text
    check (watch_direction in ('below', 'above')),
  add column if not exists watch_threshold numeric,
  -- Latch so we alert once per crossing, not every month it stays crossed.
  add column if not exists watch_crossed boolean not null default false;

-- No RLS changes: the anon key still can't UPDATE this table (insert-only,
-- per schema.sql). Watch settings are written by the save-watch edge
-- function using the service-role key, after verifying the subscriber's
-- access token — the same pattern as verify-access and stripe-webhook.
