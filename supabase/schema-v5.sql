-- schema-v5: match_requests — the "Get Connected" introduction flow.
-- Run after schema-v4.sql (SQL Editor → paste → Run).
--
-- Replaces the on-page Realtor Match card with a neutral request flow: the
-- consumer report shows no agent until the user explicitly asks for an
-- introduction. Rows are written ONLY by the match-request edge function
-- (service role) after the user checks the consent box; the consent text
-- they saw is stored verbatim alongside the timestamp.
--
-- The team is emailed per row (see functions/match-request) and makes the
-- introduction manually — `status` tracks that pipeline.

create table if not exists public.match_requests (
  id           uuid primary key default gen_random_uuid(),
  created_at   timestamptz not null default now(),
  name         text not null,
  email        text not null,
  phone        text,
  zip          text not null check (zip ~ '^\d{5}$'),
  address      text,
  timeline     text,
  note         text,
  verdict      text,          -- the report's verdict tag at request time (HOLD/WATCH/ACT)
  source       text not null default 'report',
  consent_text text not null, -- the exact consent copy the user agreed to
  consented_at timestamptz not null default now(),
  status       text not null default 'new'
               check (status in ('new', 'contacted', 'introduced', 'closed', 'spam'))
);

create index if not exists match_requests_status_idx
  on public.match_requests (status, created_at desc);

-- RLS locked to the service role: no anon policies at all, so the public
-- anon key can neither read nor write this table. The only write path is
-- the match-request edge function.
alter table public.match_requests enable row level security;
