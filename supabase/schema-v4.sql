-- ShouldISellYet schema v4 — run AFTER schema.sql, schema-v2.sql, schema-v3.sql
-- (safe to run anytime; idempotent).
--
-- Adds personal-number alerts: a subscriber can ask to be emailed when their
-- OWN walk-away number, equity, or lock-in cost crosses a threshold they set
-- (as opposed to the existing ZIP-level verdict-color alert, which watches
-- the market, not their specific numbers).
--
-- A subscriber can watch UP TO THREE metrics at once (one toggle per number
-- on the report — walk-away, equity, lock-in cost), so `watches` is an array
-- rather than a single set of columns; saving one metric's watch never
-- overwrites another's.
--
-- This is opt-in and requires the subscriber to explicitly submit their
-- calculation inputs via the save-watch edge function — see
-- supabase/functions/save-watch/index.ts. Nothing here is populated by
-- default; a subscriber who never sets a watch has calc_inputs = null and
-- watches = '[]'.

alter table public.subscribers
  -- Snapshot of the inputs needed to recompute their numbers monthly, shared
  -- across all of that subscriber's watches:
  -- {value, baselineMedian, bal, rate, origAmt, costPct}
  add column if not exists calc_inputs jsonb,
  -- Array of 0-3 entries: {metric, direction, threshold, crossed}
  --   metric    in "walkaway" | "equity" | "lockin"
  --   direction in "below" | "above"
  --   threshold numeric
  --   crossed   bool — latch so we alert once per crossing, not every month
  --             it stays crossed (reset to false when the value moves back)
  add column if not exists watches jsonb not null default '[]'::jsonb;

-- No RLS changes: the anon key still can't UPDATE this table (insert-only,
-- per schema.sql). Watch settings are written by the save-watch edge
-- function using the service-role key, after verifying the subscriber's
-- access token — the same pattern as verify-access and stripe-webhook.
