-- ShouldISellYet schema REPAIR — re-materializes the migrations that two
-- filename collisions erased from the working tree. NOT a new version number.
--
-- WHAT HAPPENED. schema-v20.sql and schema-v21.sql were each written TWICE.
-- The second author of each name overwrote the first, so two migrations that
-- had already been applied to production vanished from the repo:
--
--   git show 3fa684d:supabase/schema-v20.sql   → public.zip_velocity
--   git show 2a9c64f:supabase/schema-v21.sql   → public.press_corroboration
--                                                + admin_press_list / _add /
--                                                  _delete + admin_zip_checks
--
-- Production HAS all of these objects. The working tree did not, which means
-- a rebuild, a staging clone, or a fork replaying schema-v2 … v22 in order
-- would come up MISSING the press-corroboration CRUD the admin Markets tab
-- calls and the zip_velocity table upsert_velocity.py writes to.
--
-- WHY THIS IS NOT schema-v23.sql. A version number is a claim that production
-- is one step behind. Production is not behind — it already ran both of these
-- statements, under names that no longer point at them. Numbering the repair
-- would permanently misstate the history and make the next author believe
-- there were 23 forward migrations when there were 22. This file is a REPAIR:
-- run it once against any environment whose objects do not match git, then
-- forget it. On production it is a no-op by construction (see below). Fresh
-- environments run it BEFORE schema-v23.sql.
--
-- IDEMPOTENCE. The text below is byte-for-byte what was applied, so:
--   * create table if not exists     — skipped where the table exists
--   * create or replace function     — same name, same argument names, same
--                                      return type ⇒ replaces in place. Do
--                                      NOT edit a signature in this file; a
--                                      renamed parameter makes CREATE OR
--                                      REPLACE fail outright, and a changed
--                                      body silently reverts whatever is live.
--   * enable row level security      — no-op when already enabled
--   * revoke / grant                 — no-op when already in that state
-- No DROP, no ALTER of an existing column, no data touched.
--
-- NEVER REUSE A VERSION NUMBER AGAIN. Before writing schema-vNN.sql, run
--   ls supabase/schema-v*.sql | sort -V | tail -1
-- and take the next integer.

-- ═════════════════════════════════════════════════════════════════════════
-- Recovered from 3fa684d:supabase/schema-v20.sql
-- ═════════════════════════════════════════════════════════════════════════
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

-- ═════════════════════════════════════════════════════════════════════════
-- Recovered from 2a9c64f:supabase/schema-v21.sql
-- ═════════════════════════════════════════════════════════════════════════
--
-- Markets-to-Market T3/T4: the press-corroboration log (the receipts) and
-- the per-ZIP activity read the admin map + target-market table share.

-- ————— News corroboration log —————
-- Every row is a RECEIPT: a published article that corroborates a verdict
-- event we flagged earlier. It feeds marketing claims ("we flagged it N days
-- before the press"), so url and published_on are NOT NULL — no receipt
-- without a source. lead_days is computed, not entered: article date minus
-- our first-flag date, positive = we were ahead.
create table if not exists public.press_corroboration (
  id           uuid primary key default gen_random_uuid(),
  url          text not null,
  outlet       text not null,
  headline     text not null,
  published_on date not null,
  metro_cbsa   text,                      -- one of these two identifies the geo
  zip          text check (zip is null or zip ~ '^\d{5}$'),
  corroborates text not null check (corroborates in
                 ('first_watch', 'first_act', 'gathering_entry')),
  flag_date    date not null,             -- when WE first flagged that event
  note         text,
  created_at   timestamptz not null default now()
);

alter table public.press_corroboration enable row level security;
revoke all on table public.press_corroboration from anon, authenticated;

-- Admin-only CRUD via security-definer RPCs, same is_admin() gate as every
-- other admin surface (schema-v12).
create or replace function public.admin_press_list()
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  select coalesce(jsonb_agg(jsonb_build_object(
           'id', id, 'url', url, 'outlet', outlet, 'headline', headline,
           'published_on', published_on, 'metro_cbsa', metro_cbsa, 'zip', zip,
           'corroborates', corroborates, 'flag_date', flag_date, 'note', note,
           'lead_days', (published_on - flag_date))
           order by published_on desc), '[]'::jsonb)
    into out from public.press_corroboration;
  return out;
end;
$$;

create or replace function public.admin_press_add(
  p_url text, p_outlet text, p_headline text, p_published date,
  p_cbsa text, p_zip text, p_corroborates text, p_flag date, p_note text)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare rid uuid;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  if p_url is null or btrim(p_url) = '' or p_published is null then
    raise exception 'no receipt without a source: url and article date required';
  end if;
  insert into public.press_corroboration
    (url, outlet, headline, published_on, metro_cbsa, zip, corroborates, flag_date, note)
  values (btrim(p_url), coalesce(btrim(p_outlet), ''), coalesce(btrim(p_headline), ''),
          p_published, nullif(btrim(p_cbsa), ''), nullif(btrim(p_zip), ''),
          p_corroborates, p_flag, nullif(btrim(p_note), ''))
  returning id into rid;
  return jsonb_build_object('ok', true, 'id', rid);
end;
$$;

create or replace function public.admin_press_delete(rid uuid)
returns jsonb
language plpgsql security definer set search_path = public
as $$
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  delete from public.press_corroboration where id = rid;
  return jsonb_build_object('ok', true);
end;
$$;

-- ————— Activity by checked ZIP (T3 join + T4 map layer) —————
-- zip_check events already store the CHECKED zip — where people are checking,
-- not where visitors are located. No IP, no geolocation, nothing new stored:
-- this only aggregates what the anonymous counts design already keeps.
create or replace function public.admin_zip_checks(days int default 30)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  select coalesce(jsonb_object_agg(zip, n), '{}'::jsonb) into out
    from (select zip, count(*)::int as n
            from public.events
           where event = 'zip_check' and zip is not null
             and ts >= now() - make_interval(days => days)
           group by zip) t;
  return out;
end;
$$;

revoke execute on function public.admin_press_list() from public, anon;
revoke execute on function public.admin_press_add(text,text,text,date,text,text,text,date,text) from public, anon;
revoke execute on function public.admin_press_delete(uuid) from public, anon;
revoke execute on function public.admin_zip_checks(int) from public, anon;
grant execute on function public.admin_press_list() to authenticated;
grant execute on function public.admin_press_add(text,text,text,date,text,text,text,date,text) to authenticated;
grant execute on function public.admin_press_delete(uuid) to authenticated;
grant execute on function public.admin_zip_checks(int) to authenticated;
