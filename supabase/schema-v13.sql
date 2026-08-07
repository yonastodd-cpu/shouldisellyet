-- ShouldISellYet schema v13 — run AFTER schema-v12.sql (idempotent).
--
-- Overview + funnel RPCs, and the one subscribers column they need.
--
--   purchased_at    When the webhook confirmed payment. Distinct from
--                   created_at because a pending signup row is created at
--                   form-submit and only PATCHed to active when Stripe's
--                   webhook lands — usually minutes, occasionally a day if
--                   someone stalls on the payment page. Funnel windows and
--                   the customer drawer coalesce() to created_at for rows
--                   from before this column existed.
--
-- Every function: SECURITY DEFINER, is_admin() guard first, EXECUTE revoked
-- from anon/public. Purchases are counted from webhook-written rows —
-- the dashboard never talks to Stripe.

alter table public.subscribers
  add column if not exists purchased_at timestamptz;

-- ————— Overview cards —————
create or replace function public.admin_overview(days int default 30)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  since_d date := (now() - make_interval(days => days))::date;
  since_t timestamptz := now() - make_interval(days => days);
  ev jsonb;
  out jsonb;
  agents_n int := 0;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  -- Event counts from the rollup — the dashboard's common queries never
  -- touch raw events.
  select coalesce(jsonb_object_agg(event, n), '{}'::jsonb)
    into ev
    from (select event, sum(n)::int as n
            from public.events_daily
           where day >= since_d
           group by event) t;

  -- Agent program is paused; the table ships in v15. to_regclass keeps this
  -- function correct whether or not v15 has run yet.
  if to_regclass('public.agents') is not null then
    execute 'select count(*)::int from public.agents where verified' into agents_n;
  end if;

  select jsonb_build_object(
    'days', days,
    'sessions', coalesce((select sum(new_sessions)::int from public.events_daily
                           where day >= since_d and event = 'page_view'), 0),
    'events', ev,
    'reports_sold', (select count(*)::int from public.subscribers
                      where plan = 'report' and stripe_session_id is not null
                        and coalesce(purchased_at, created_at) >= since_t),
    'new_subs',     (select count(*)::int from public.subscribers
                      where plan = 'monitor' and stripe_session_id is not null
                        and coalesce(purchased_at, created_at) >= since_t),
    'active_subs',    (select count(*)::int from public.subscribers
                        where plan = 'monitor' and status = 'active'),
    'active_monthly', (select count(*)::int from public.subscribers
                        where plan = 'monitor' and status = 'active'
                          and billing_interval = 'monthly'),
    'active_annual',  (select count(*)::int from public.subscribers
                        where plan = 'monitor' and status = 'active'
                          and billing_interval = 'annual'),
    'active_unknown', (select count(*)::int from public.subscribers
                        where plan = 'monitor' and status = 'active'
                          and billing_interval is null),
    'match_requests', (select count(*)::int from public.match_requests
                        where created_at >= since_t),
    'agents_active', agents_n
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_overview(int) from public, anon;
grant execute on function public.admin_overview(int) to authenticated;

-- ————— Funnel: stages, per-day series, utm breakdown —————
create or replace function public.admin_funnel(days int default 30)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  since_d date := (now() - make_interval(days => days))::date;
  since_t timestamptz := now() - make_interval(days => days);
  out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  select jsonb_build_object(
    'days', days,
    'stages', jsonb_build_object(
      'sessions', coalesce((select sum(new_sessions)::int from public.events_daily
                             where day >= since_d and event = 'page_view'), 0),
      'checks',   coalesce((select sum(n)::int from public.events_daily
                             where day >= since_d and event = 'zip_check'), 0),
      'clicks',   coalesce((select sum(n)::int from public.events_daily
                             where day >= since_d
                               and event in ('purchase_click_report','purchase_click_monitor')), 0),
      'purchases', (select count(*)::int from public.subscribers
                     where stripe_session_id is not null
                       and coalesce(purchased_at, created_at) >= since_t),
      'active',    (select count(*)::int from public.subscribers
                     where plan = 'monitor' and status = 'active')
    ),
    -- Zero-filled day series so the chart's x-axis never skips quiet days.
    'series', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'day', d::date,
               'sessions', coalesce(s.sessions, 0),
               'checks',   coalesce(s.checks, 0),
               'clicks',   coalesce(s.clicks, 0),
               'purchases', coalesce(p.n, 0)) order by d), '[]'::jsonb)
        from generate_series(since_d, current_date, interval '1 day') d
        left join (
          select day,
                 sum(new_sessions) filter (where event = 'page_view')::int as sessions,
                 sum(n) filter (where event = 'zip_check')::int as checks,
                 sum(n) filter (where event in
                   ('purchase_click_report','purchase_click_monitor'))::int as clicks
            from public.events_daily where day >= since_d group by day
        ) s on s.day = d::date
        left join (
          select coalesce(purchased_at, created_at)::date as day, count(*)::int as n
            from public.subscribers
           where stripe_session_id is not null
             and coalesce(purchased_at, created_at) >= since_t
           group by 1
        ) p on p.day = d::date
    ),
    -- Channel table. Purchases are deliberately absent: attributing a
    -- purchase to a channel would require tying a person's session to their
    -- payment, which is exactly the identity linkage the privacy posture
    -- rules out. Clicks are the deepest attributable stage.
    'utm', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'utm_source', utm_source,
               'sessions', sessions, 'checks', checks, 'clicks', clicks)
               order by sessions desc), '[]'::jsonb)
        from (
          select coalesce(nullif(utm_source, ''), '(direct)') as utm_source,
                 sum(new_sessions) filter (where event = 'page_view')::int as sessions,
                 coalesce(sum(n) filter (where event = 'zip_check'), 0)::int as checks,
                 coalesce(sum(n) filter (where event in
                   ('purchase_click_report','purchase_click_monitor')), 0)::int as clicks
            from public.events_daily
           where day >= since_d
           group by 1
        ) u
    )
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_funnel(int) from public, anon;
grant execute on function public.admin_funnel(int) to authenticated;

-- ————— Top-checked ZIPs —————
-- The one admin read that scans raw events: the rollup has no zip dimension,
-- and adding one would triple its cardinality for a single table. An indexed
-- scan over ≤90 days of a low-traffic table is cheaper than that.
create or replace function public.admin_top_zips(days int default 30, lim int default 25)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  select coalesce(jsonb_agg(jsonb_build_object('zip', zip, 'checks', n) order by n desc), '[]'::jsonb)
    into out
    from (select zip, count(*)::int as n
            from public.events
           where event = 'zip_check' and zip is not null
             and ts >= now() - make_interval(days => days)
           group by zip
           order by n desc
           limit greatest(1, least(lim, 100))) t;
  return out;
end;
$$;

revoke execute on function public.admin_top_zips(int, int) from public, anon;
grant execute on function public.admin_top_zips(int, int) to authenticated;
