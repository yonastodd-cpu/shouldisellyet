-- ShouldISellYet subscriber storage.
-- Run once in Supabase: SQL Editor → paste → Run.

create table if not exists public.subscribers (
  id         uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),
  email      text not null,
  zip        text not null check (zip ~ '^\d{5}$'),
  plan       text not null default 'monitor'
             check (plan in ('monitor', 'report', 'waitlist')),
  address    text,
  status     text not null default 'pending'
             check (status in ('pending', 'active', 'canceled')),
  source     text
);

create index if not exists subscribers_zip_idx  on public.subscribers (zip);
create index if not exists subscribers_plan_idx on public.subscribers (plan, status);

-- Row-level security: the website (anon key) can INSERT only.
-- Reading/updating requires the service-role key (used by the GitHub Action).
alter table public.subscribers enable row level security;

drop policy if exists "anon insert only" on public.subscribers;
create policy "anon insert only"
  on public.subscribers for insert
  to anon
  with check (true);

-- no select/update/delete policies for anon → those operations are denied.
