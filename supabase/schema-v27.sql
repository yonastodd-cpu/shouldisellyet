-- ShouldISellYet schema v27 — run AFTER schema-v26.sql (idempotent).
--
-- ————— Three posts a week, and the windows to put them in —————
--
-- The weekly cap goes from 2 to 3 per channel (operator decision, 2026-08-10),
-- to make room for the post taxonomy: the quota table it has to serve wants
-- roughly 18-22 posts a month, and a 2/week cap across three channels tops out
-- near 24 with no slack, so low-priority types were going to be refused every
-- week rather than occasionally.
--
-- RAISING THE NUMBER ALONE WOULD HAVE DONE NOTHING. The real cap is
-- min(weekly cap, windows the channel actually has), and ig and fb had exactly
-- two windows each — Sunday 19:30 and Wednesday 08:30. A cap of 3 against 2
-- windows is still 2. So this migration adds the third window before raising
-- the number, and the two changes belong together for that reason.
--
-- Friday 08:30 ET, chosen to match the existing morning slot and to spread the
-- week evenly: Sunday evening, Wednesday morning, Friday morning. X already had
-- three (it carries Tuesday as well) and is unchanged.

insert into public.marketing_windows (channel, dow, at_time, label, anchor) values
  ('ig', 5, '08:30', 'Friday morning', false),
  ('fb', 5, '08:30', 'Friday morning', false)
on conflict (channel, dow, at_time) do nothing;


-- ————— The cap itself —————
-- MATCHED SET, and all of it changes together or none of it does:
--   * this function (the enforcement),
--   * public.admin_marketing_week's guidance block (what the operator is told),
--   * pipeline/marketing_config.MAX_WEEKLY_PER_CHANNEL (the Python refusal),
--   * pipeline/marketing_config.FALLBACK_WINDOWS (the dry-run mirror).
-- The generator refuses first and this trigger is the backstop; if the two
-- disagree, the generator plans a post the database then rejects, which reads
-- as a mystery failure in CI.
create or replace function public.marketing_slot_conflict(
  p_id uuid, p_channel text, p_when timestamptz, p_metro text, p_status text)
returns text
language plpgsql stable security definer set search_path = public
as $$
declare
  local_ts timestamp;
  wk date;
  n int;
begin
  if p_status = 'skipped' or p_channel is null or p_when is null then
    return null;
  end if;

  local_ts := p_when at time zone 'America/New_York';

  -- R1. A channel with no rows in marketing_windows can never be scheduled;
  -- that is how nextdoor_naomi stays off.
  if not exists (select 1 from public.marketing_windows w
                  where w.channel = p_channel
                    and w.dow = extract(dow from local_ts)::smallint
                    and w.at_time = local_ts::time) then
    return format('%s has no posting window at %s ET', p_channel,
                  to_char(local_ts, 'Dy HH24:MI'));
  end if;

  -- R2. Counting rows, not slots: a channel with more windows than the cap can
  -- still only take the cap, which is the rule the brief actually states.
  wk := public.marketing_week_start(p_when);
  select count(*) into n
    from public.marketing_tasks t
   where t.channel = p_channel
     and t.status <> 'skipped'
     and t.scheduled_for is not null
     and public.marketing_week_start(t.scheduled_for) = wk
     and (p_id is null or t.id <> p_id);
  if n >= 3 then
    return format('weekly cap: %s already has 3 posts in the week of %s', p_channel, wk);
  end if;

  -- R3. Symmetric window — 14 days either side, across all channels, so the
  -- same metro cannot be recycled on a different network to dodge the rule.
  if p_metro is not null then
    select count(*) into n
      from public.marketing_tasks t
     where t.metro_cbsa = p_metro
       and t.channel is not null
       and t.status <> 'skipped'
       and t.scheduled_for is not null
       and t.scheduled_for between p_when - interval '14 days'
                               and p_when + interval '14 days'
       and (p_id is null or t.id <> p_id);
    if n > 0 then
      return format('metro %s is already scheduled within 14 days of %s',
                    p_metro, to_char(local_ts, 'YYYY-MM-DD'));
    end if;
  end if;

  -- R4. The readable version of marketing_tasks_slot_idx.
  if exists (select 1 from public.marketing_tasks t
              where t.channel = p_channel
                and t.scheduled_for = p_when
                and t.status <> 'skipped'
                and (p_id is null or t.id <> p_id)) then
    return format('slot taken: %s already has a post at %s ET', p_channel,
                  to_char(local_ts, 'Dy HH24:MI'));
  end if;

  return null;
end;
$$;

revoke execute on function
  public.marketing_slot_conflict(uuid, text, timestamptz, text, text)
  from public, anon, authenticated;


-- The guidance strip must state the cap that is actually enforced. A strip
-- promising 2 while the trigger allows 3 is worse than one that says nothing.
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
      'used', (select coalesce(jsonb_object_agg(channel, n), '{}'::jsonb)
                 from (select channel, count(*)::int as n
                         from public.marketing_tasks
                        where channel is not null and status <> 'skipped'
                          and scheduled_for >= wk_from and scheduled_for < wk_to
                        group by channel) u)
    ),
    'one_thing', (select public.marketing_task_json(t)
                    from public.marketing_tasks t
                   where t.status in ('suggested', 'scheduled')
                     and t.scheduled_for is not null
                     and t.scheduled_for < wk_to
                   order by t.priority_score, t.scheduled_for
                   limit 1),
    'tasks', (select coalesce(jsonb_agg(public.marketing_task_json(t)
                       order by t.scheduled_for, t.priority_score), '[]'::jsonb)
                from public.marketing_tasks t
               where t.scheduled_for >= wk_from and t.scheduled_for < wk_to),
    'overdue', (select coalesce(jsonb_agg(public.marketing_task_json(t)
                         order by t.scheduled_for), '[]'::jsonb)
                  from public.marketing_tasks t
                 where t.status in ('suggested', 'scheduled')
                   and t.scheduled_for is not null
                   and t.scheduled_for < wk_from),
    'unscheduled', (select coalesce(jsonb_agg(public.marketing_task_json(t)
                             order by t.priority_score, t.created_at), '[]'::jsonb)
                      from public.marketing_tasks t
                     where t.status = 'suggested' and t.scheduled_for is null),
    'demoted', (select coalesce(jsonb_agg(jsonb_build_object(
                         'metro_cbsa', metro_cbsa, 'metro_name', metro_name,
                         'skips', skips, 'expires_at', expires_at)
                         order by expires_at desc), '[]'::jsonb)
                  from public.marketing_demotions)
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_marketing_week(date) from public, anon;
grant execute on function public.admin_marketing_week(date) to authenticated;


-- ————— thread_position: a recap thread is many rows, not one —————
--
-- A recap thread is a lead post plus three to five replies plus a closer, and
-- the model is one row per POST. Operator decision (2026-08-10): use
-- thread_position rather than a parent/child column.
--
-- WHY POSITION AND NOT A PARENT ID. Every row in a thread shares one
-- dedupe_key stem and one scheduled slot; what distinguishes them is ORDER,
-- and order is the thing the operator posts in. A parent uuid would need the
-- lead row to exist before its replies can be written, which the generator
-- cannot guarantee — it inserts one row per POST request precisely so a
-- refused row does not roll back its siblings. A position needs no such
-- ordering and cannot dangle.
--
-- NULL = a standalone post, which is almost all of them. 0 = the lead, 1..n =
-- the replies in order. The pair (thread_key, thread_position) is unique so a
-- re-run cannot double a reply.
alter table public.marketing_tasks
  add column if not exists thread_key text;

alter table public.marketing_tasks
  add column if not exists thread_position smallint
  check (thread_position is null or thread_position >= 0);

-- A row is either standalone or fully addressed: a position without a thread
-- to belong to is a reply to nothing.
alter table public.marketing_tasks
  drop constraint if exists marketing_tasks_thread_ck;
alter table public.marketing_tasks
  add constraint marketing_tasks_thread_ck
  check ((thread_key is null) = (thread_position is null));

create unique index if not exists marketing_tasks_thread_idx
  on public.marketing_tasks (thread_key, thread_position)
  where thread_key is not null;

comment on column public.marketing_tasks.thread_key is
  'Groups the rows of one thread. NULL for a standalone post.';
comment on column public.marketing_tasks.thread_position is
  '0 = lead, 1..n = replies in order. NULL for a standalone post.';
