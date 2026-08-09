-- ShouldISellYet schema v21 — run AFTER schema-v20.sql (idempotent).
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
