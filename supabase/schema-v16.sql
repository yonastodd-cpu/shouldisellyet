-- ShouldISellYet schema v16 — run AFTER schema-v15.sql (idempotent).
--
-- AI-referral breakout for the admin funnel: bucket the ALREADY-STORED
-- referrer domain into source_bucket = 'ai_engine' when the visit came from
-- an AI answer engine, so the admin funnel can break out AI-driven visits.
--
-- WHERE THE BUCKETING LIVES, AND WHY. The events table deliberately has no
-- props/jsonb column ("nowhere to PUT an identifier" — schema-v11), so the
-- bucket is DERIVED here, in the view, from events.referrer — a domain the
-- track function already stores with own-hosts dropped and DNT/GPC users
-- never reaching it. This is a strict coarsening of existing data: no new
-- client field, no new identifier, works retroactively over the whole raw
-- window, and the privacy policy's "anonymous usage counts, no personal
-- identifiers" sentence needs no edit. If the engine list changes, edit the
-- ai_referrer() function below and everything downstream follows.

create or replace function public.ai_referrer(r text)
returns boolean
language sql immutable
as $$
  select regexp_replace(coalesce(r, ''), '^www\.', '') in
    ('chatgpt.com', 'chat.openai.com', 'perplexity.ai',
     'copilot.microsoft.com', 'gemini.google.com');
$$;

-- events_daily grows a source_bucket column (appended last — create or
-- replace view may only add columns at the end). Existing consumers that
-- sum n / new_sessions are unaffected by the finer grouping.
create or replace view public.events_daily as
  select ts::date as day,
         event,
         coalesce(utm_source, '') as utm_source,
         count(*)::int as n,
         (count(*) filter (where is_new_session))::int as new_sessions,
         case when public.ai_referrer(referrer) then 'ai_engine' else '' end as source_bucket
  from public.events
  group by 1, 2, 3, 6;

revoke all on public.events_daily from anon, authenticated;

-- admin_funnel: same shape as v13 plus one key, 'ai' — sessions/checks/clicks
-- where source_bucket = 'ai_engine', rendered by admin.html as an extra row
-- in the By-channel table. Purchases stay unattributed on purpose (v13 note:
-- tying a payment to a browsing session is the identity linkage the privacy
-- posture rules out).
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
    -- Channel table. Purchases are deliberately absent — see v13 note above.
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
    ),
    -- AI answer-engine visits, from the derived source_bucket.
    'ai', (
      select jsonb_build_object(
        'sessions', coalesce(sum(new_sessions) filter (where event = 'page_view'), 0)::int,
        'checks',   coalesce(sum(n) filter (where event = 'zip_check'), 0)::int,
        'clicks',   coalesce(sum(n) filter (where event in
                      ('purchase_click_report','purchase_click_monitor')), 0)::int)
        from public.events_daily
       where day >= since_d and source_bucket = 'ai_engine'
    )
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_funnel(int) from public, anon;
grant execute on function public.admin_funnel(int) to authenticated;
