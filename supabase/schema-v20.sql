-- ShouldISellYet schema v20 — run AFTER schema-v19.sql (idempotent).
--
-- Velocity T2: the serving side of the paywall boundary.
--
-- Per-ZIP approach velocity is the PAID layer. The pipeline computes it on
-- every refresh (velocity.py) and upserts it here (upsert_velocity.py); the
-- ONLY read path is verify-access, which returns a ZIP's payload solely for
-- a valid purchase token. Nothing here is readable with the anon key, and
-- the browser never fetches velocity from a public file — the repo commits
-- metro/state aggregates only. That is the server-side gate the brief
-- requires: an unauthenticated fetch of report data cannot contain velocity
-- fields because the data lives nowhere the anon role can see.

create table if not exists public.zip_velocity (
  zip        text primary key check (zip ~ '^\d{5}$'),
  period     text not null,           -- data month this payload was computed from
  payload    jsonb not null,          -- {sig:{spy:{dir,rate,mtl},...}, score, state, low_volume}
  updated_at timestamptz not null default now()
);

alter table public.zip_velocity enable row level security;
revoke all on table public.zip_velocity from anon, authenticated;
