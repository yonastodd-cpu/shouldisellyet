-- ShouldISellYet schema v11 — run AFTER schema-v10.sql (idempotent).
--
-- First-party anonymous analytics. The privacy policy promises "anonymous,
-- first-party usage counts … no cookies, no advertising trackers, and no
-- personal identifiers", and this table is shaped so that promise cannot be
-- broken by accident: there is nowhere to PUT an IP, user agent, or user id.
-- The track edge function never reads those from the request; even if it did,
-- no column would hold them. Schema as policy enforcement.
--
--   event            one of six product events — checked here AND in the
--                    track function; pipeline/test_track_events.py fails if
--                    the two lists drift.
--   ts               hour-truncated by the function. Coarse on purpose:
--                    exact timestamps are a fingerprinting surface and the
--                    dashboard only ever charts by day.
--   is_new_session   first page_view of a browser session (sessionStorage
--                    flag, client-side). Sessions ≈ visitors; the dashboard
--                    labels it "sessions, not people".
--   utm_source       channel label from the landing URL. Aggregate marketing
--                    data, not identity.
--   referrer         domain only, never a path; our own domain is dropped.
--   zip              the ZIP a visitor checked — market data, not personal.
--   plan             annual | monthly | report on purchase clicks.
--   path             pathname only; the function strips query strings so a
--                    my-report access token can never land here.

create table if not exists public.events (
  id    bigint generated always as identity primary key,
  event text not null check (event in
    ('page_view','zip_check','purchase_click_report',
     'purchase_click_monitor','share_click','match_request_opened')),
  ts timestamptz not null,
  is_new_session boolean not null default false,
  utm_source text,
  referrer   text,
  zip  text check (zip is null or zip ~ '^\d{5}$'),
  plan text check (plan is null or plan in ('annual','monthly','report')),
  path text
);

-- Service-role only. RLS with no policies blocks anon/authenticated even
-- though Supabase's default privileges grant table access to those roles;
-- the revokes make the intent explicit and survive an accidental
-- `alter table … disable row level security`.
alter table public.events enable row level security;
revoke all on table public.events from anon, authenticated;

create index if not exists events_event_ts_idx on public.events (event, ts);
create index if not exists events_zip_idx on public.events (zip) where zip is not null;

-- Daily rollup the dashboard reads instead of scanning raw rows. A plain view
-- stays correct with zero maintenance at this traffic level; the (event, ts)
-- index carries it. Views ignore RLS and run with their owner's rights, which
-- is exactly what lets admin RPCs (security definer) read it — so the revoke
-- below is what keeps the anon key out. Do not skip it.
create or replace view public.events_daily as
  select ts::date as day,
         event,
         coalesce(utm_source, '') as utm_source,
         count(*)::int as n,
         (count(*) filter (where is_new_session))::int as new_sessions
  from public.events
  group by 1, 2, 3;

revoke all on public.events_daily from anon, authenticated;

-- Retention: raw events are deleted after 90 days by
-- pipeline/events_maintenance.py in the weekly jobs workflow (same
-- scheduler and secrets as renewal reminders — no pg_cron dependency).
-- Rollups are recomputed from what remains, so charts beyond 90 days fade
-- deliberately; nothing keeps per-event rows longer.
