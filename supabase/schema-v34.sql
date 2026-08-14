-- ShouldISellYet schema v34 — run AFTER schema-v33.sql (idempotent).
--
-- ═══ Provenance for the Redfin sunset (migration Phase 0.2) ═══
--
-- Every stored market figure came from one vendor and nothing recorded that.
-- Before any of it is reprocessed or replaced, each row gets to say where it
-- came from and when it was retrieved — so a mixed table during the migration
-- is readable, and so "what did you hold, and when" has an answer that is not
-- an archaeology exercise over git history.
--
-- NOTE ON A NAME COLLISION: public.subscribers already has a `source` column
-- and it means SIGNUP CHANNEL. It is deliberately NOT touched here — writing
-- 'redfin' onto it would corrupt attribution data to answer a question it was
-- never asked.
--
-- RETENTION IS NOT DECIDED HERE. Counsel question #1 (docs/REDFIN-SUNSET.md)
-- is whether stored vendor-derived data must be deleted or merely stopped.
-- Until that is answered the posture is: stop displaying, stop computing,
-- retain. Tagging first is what makes a later purge precise instead of broad.

alter table public.zip_velocity
  add column if not exists source text not null default 'redfin';
alter table public.zip_velocity
  add column if not exists retrieved_at timestamptz;

alter table public.marketing_tasks
  add column if not exists source text not null default 'redfin';

-- Backfill retrieved_at from the best evidence each table actually has.
-- zip_velocity has no timestamp of its own, so the period it describes is the
-- honest answer: the last day of that month, marked as an approximation in
-- the column comment rather than presented as a retrieval instant we do not
-- have.
update public.zip_velocity
   set retrieved_at = coalesce(retrieved_at,
        (to_date(period || '-01', 'YYYY-MM-DD') + interval '1 month - 1 day')::timestamptz)
 where retrieved_at is null;

comment on column public.zip_velocity.source is
  'Upstream data vendor for the figures in this row. Redfin ingestion stopped 2026-08-13; rows written after the migration carry their own vendor.';
comment on column public.zip_velocity.retrieved_at is
  'When the underlying vendor data was retrieved. Backfilled rows carry the last day of the period they describe — an approximation, not a recorded instant.';
comment on column public.marketing_tasks.source is
  'Vendor behind the figures quoted in this post''s copy.';

create index if not exists zip_velocity_source_idx on public.zip_velocity (source);
