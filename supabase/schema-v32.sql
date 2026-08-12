-- ShouldISellYet schema v32 — run AFTER schema-v31.sql (idempotent).
--
-- ═══ Reading a thread back ═══
--
-- v31 made threads legal to WRITE. The read side still treats every row as an
-- independent post, which produces three specific wrongs in the Marketing tab:
--
--   * "one thing to do next" could name reply 4 of a thread, an instruction to
--     post a sentence that begins mid-argument with no lead in sight.
--   * the mix meter would count a six-row thread as six posts, so one roundup
--     would read as half the month's output.
--   * tasks are ordered by (scheduled_for, priority_score); six rows share both,
--     so the replies would render in whatever order the planner returned them.
--     A thread displayed out of order is worse than no thread — it reads as
--     incoherent copy rather than as a sorting bug.
--
-- Same predicate as v31 throughout: coalesce(thread_position, 0) = 0 is "this
-- row is a post".

create or replace function public.admin_marketing_week(p_week_start date default null)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  wk date;
  wk_from timestamptz;
  wk_to   timestamptz;
  out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  wk := coalesce(p_week_start, public.marketing_week_start(now()));
  wk_from := (wk::timestamp at time zone 'America/New_York');
  wk_to   := ((wk + 7)::timestamp at time zone 'America/New_York');

  select jsonb_build_object(
    'week_start', wk,
    'guidance', jsonb_build_object(
      'weekly_cap', 3,
      'anchor', 'Sunday 19:30 ET',
      'burst_open', exists (select 1 from public.marketing_tasks
                             where type = 'burst'
                               and status in ('suggested', 'scheduled')
                               and scheduled_for >= now() - interval '48 hours'),
      'next_refresh', public.marketing_next_refresh(),
      -- Counts posts, matching the cap it is reporting against. A thread that
      -- showed as "x 6" under a cap of 3 would look like the cap had failed.
      'used', (select coalesce(jsonb_object_agg(channel, n), '{}'::jsonb)
                 from (select channel, count(*)::int as n
                         from public.marketing_tasks
                        where channel is not null and status <> 'skipped'
                          and coalesce(thread_position, 0) = 0
                          and scheduled_for >= wk_from and scheduled_for < wk_to
                        group by channel) u)
    ),
    -- The next action is always a whole post. Replies are part of the lead's
    -- instruction, not separate errands.
    'one_thing', (select public.marketing_task_json(t)
                    from public.marketing_tasks t
                   where t.status in ('suggested', 'scheduled')
                     and t.scheduled_for is not null
                     and coalesce(t.thread_position, 0) = 0
                     and t.scheduled_for < wk_to
                   order by t.priority_score, t.scheduled_for
                   limit 1),
    -- tasks DOES include replies: the operator has to read the thread to post
    -- it. Ordering is the whole point here. scheduled_for and priority_score
    -- are identical across a thread's rows by construction (the generator
    -- assigns one score to the whole thread — matched pair with
    -- pipeline/marketing_tasks.py), so thread_key groups the rows and
    -- thread_position puts them in reading order. NULLS FIRST keeps ordinary
    -- posts ahead of a thread that ties with them.
    'tasks', (select coalesce(jsonb_agg(public.marketing_task_json(t)
                       order by t.scheduled_for, t.priority_score,
                                t.thread_key nulls first,
                                coalesce(t.thread_position, 0)), '[]'::jsonb)
                from public.marketing_tasks t
               where t.scheduled_for >= wk_from and t.scheduled_for < wk_to),
    'overdue', (select coalesce(jsonb_agg(public.marketing_task_json(t)
                         order by t.scheduled_for), '[]'::jsonb)
                  from public.marketing_tasks t
                 where t.status in ('suggested', 'scheduled')
                   and t.scheduled_for is not null
                   and coalesce(t.thread_position, 0) = 0
                   and t.scheduled_for < wk_from),
    'unscheduled', (select coalesce(jsonb_agg(public.marketing_task_json(t)
                             order by t.priority_score, t.created_at), '[]'::jsonb)
                      from public.marketing_tasks t
                     where t.status = 'suggested' and t.scheduled_for is null
                       and coalesce(t.thread_position, 0) = 0),
    'demoted', (select coalesce(jsonb_agg(jsonb_build_object(
                         'metro_cbsa', metro_cbsa, 'metro_name', metro_name,
                         'skips', skips, 'expires_at', expires_at)
                         order by expires_at desc), '[]'::jsonb)
                  from public.marketing_demotions),
    -- Surfaced so a half-written thread is visible in the tab rather than only
    -- to whoever thinks to query the view.
    'thread_gaps', (select coalesce(jsonb_agg(jsonb_build_object(
                             'thread_key', thread_key, 'rows_present', rows_present,
                             'highest_position', highest_position, 'missing', missing)
                             order by thread_key), '[]'::jsonb)
                      from public.marketing_thread_gaps)
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_marketing_week(date) from public, anon;
grant execute on function public.admin_marketing_week(date) to authenticated;


-- The mix meter measures the month's editorial balance. One roundup is one
-- item of that balance however many rows carry it.
create or replace function public.admin_marketing_mix(p_period text default null)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  per text;
  out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  per := coalesce(nullif(btrim(p_period), ''),
                  (select max(period) from public.marketing_tasks));
  select jsonb_build_object(
    'period', per,
    'total', (select count(*) from public.marketing_tasks
               where period = per and coalesce(thread_position, 0) = 0),
    'by_type', (select coalesce(jsonb_object_agg(pt, n), '{}'::jsonb)
                  from (select coalesce(post_type, 'unclassified') as pt,
                               count(*)::int as n
                          from public.marketing_tasks
                         where period = per and coalesce(thread_position, 0) = 0
                         group by 1) t)
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_marketing_mix(text) from public, anon;
grant execute on function public.admin_marketing_mix(text) to authenticated;
