-- ShouldISellYet schema v41 — run AFTER schema-v40.sql (idempotent).
--
-- ═══ Search-demand logging + on-demand pulls ═══
--
-- Three tables and one admin read, all service-role-only:
--
--   zip_lookups     one row per homepage ZIP lookup (and per on-demand pull
--                   failure), written by the `demand` edge function. This is
--                   the measurement layer for the notice-page funnel: which
--                   ZIPs people ask about that we do not yet score, and
--                   whether a purchase or notify-me followed in-session.
--                   NO PII, same posture as public.events: ZIP + outcome +
--                   hour-truncated timestamp + two follow booleans. The row
--                   id is a client-generated random UUID whose only purpose
--                   is letting the SAME tab mark its own lookup as followed —
--                   it identifies a lookup, never a person, and dies with the
--                   tab session.
--
--   ondemand_pulls  the vendor-call ledger for purchase-time pulls — the
--                   edge-function twin of pipeline/rentcast_jobs.csv, which
--                   an edge function cannot read. Every ROW is one paid API
--                   call (store-served requests write nothing), so
--                   count(month) vs the ceiling is the whole cost control.
--
--   zip_readings    the reading the on-demand path computed at pull time,
--                   as NAMED COLUMNS (level / score / reasons / basis), so
--                   market-reading can serve the word for a pulled ZIP
--                   before the next deploy provisions its static record.
--                   Never raw_json; the republication boundary holds.

create table if not exists public.zip_lookups (
  id                uuid primary key,
  zip               text not null check (zip ~ '^\d{5}$'),
  outcome           text not null check (outcome in
                      ('reading_shown', 'notice_shown', 'invalid_zip',
                       'pull_failed', 'pull_capacity')),
  ts                timestamptz not null,          -- hour-truncated by the fn
  followed_purchase boolean not null default false,
  followed_notify   boolean not null default false,
  created_at        timestamptz not null default now()
);

alter table public.zip_lookups enable row level security;
revoke all on table public.zip_lookups from anon, authenticated;

create index if not exists zip_lookups_ts_idx  on public.zip_lookups (ts);
create index if not exists zip_lookups_zip_idx on public.zip_lookups (zip);

comment on table public.zip_lookups is
  'Search-demand log: one row per homepage ZIP lookup, written by the demand edge function. ZIP + outcome + hour-truncated ts + follow flags; no identifiers. The id is a client-random UUID so the same tab can mark its own lookup followed — it names a lookup, not a person.';

create table if not exists public.ondemand_pulls (
  id     bigint generated always as identity primary key,
  zip    text not null check (zip ~ '^\d{5}$'),
  month  text not null check (month ~ '^\d{4}-\d{2}$'),
  status text not null check (status in ('pulled', 'no_data', 'error')),
  at     timestamptz not null default now()
);

alter table public.ondemand_pulls enable row level security;
revoke all on table public.ondemand_pulls from anon, authenticated;

create index if not exists ondemand_pulls_month_idx on public.ondemand_pulls (month);

comment on table public.ondemand_pulls is
  'One row per purchase-time vendor API call (any status). count(*) for the current month against ONDEMAND_MONTHLY_CEILING is the hard cost ceiling; store-served checkouts write nothing here.';

create table if not exists public.zip_readings (
  zip         text not null check (zip ~ '^\d{5}$'),
  source      text not null,
  level       text not null check (level in ('green', 'yellow', 'red', 'strong')),
  score       integer not null,
  reasons     jsonb not null default '[]'::jsonb,
  basis       text not null,
  as_of_month text not null check (as_of_month ~ '^\d{4}-\d{2}$'),
  computed_at timestamptz not null,
  primary key (zip, source)
);

alter table public.zip_readings enable row level security;
revoke all on table public.zip_readings from anon, authenticated;

comment on table public.zip_readings is
  'Reading computed at on-demand pull time, in named columns, so market-reading can serve the word for a pulled ZIP before the next deploy. Our own output (verdict-methodology-v2 level/score/reason codes), never vendor payload.';

-- ————— Demand report, admin-only —————
-- Same shape as the other admin_* reads: security definer, is_admin() guard,
-- jsonb out, execute granted to authenticated only (the guard does the real
-- gating — see schema-v12).
create or replace function public.admin_demand(days int default 30)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  select jsonb_build_object(
    'totals', (
      select coalesce(jsonb_object_agg(outcome, n), '{}'::jsonb)
        from (select outcome, count(*)::int as n
                from public.zip_lookups
               where ts >= now() - make_interval(days => days)
               group by outcome) t
    ),
    'followed_purchase', (
      select count(*)::int from public.zip_lookups
       where ts >= now() - make_interval(days => days) and followed_purchase
    ),
    'followed_notify', (
      select count(*)::int from public.zip_lookups
       where ts >= now() - make_interval(days => days) and followed_notify
    ),
    'top_notice_zips', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'zip', zip, 'lookups', n,
               'purchases', p, 'notifies', f) order by n desc), '[]'::jsonb)
        from (select zip, count(*)::int as n,
                     count(*) filter (where followed_purchase)::int as p,
                     count(*) filter (where followed_notify)::int as f
                from public.zip_lookups
               where outcome = 'notice_shown'
                 and ts >= now() - make_interval(days => days)
               group by zip
               order by n desc
               limit 25) t
    ),
    'pulls_this_month', (
      select count(*)::int from public.ondemand_pulls
       where month = to_char(now(), 'YYYY-MM')
    ),
    'pulls_ok_this_month', (
      select count(*)::int from public.ondemand_pulls
       where month = to_char(now(), 'YYYY-MM') and status = 'pulled'
    )
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_demand(int) from public, anon;
grant execute on function public.admin_demand(int) to authenticated;
