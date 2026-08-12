-- ShouldISellYet schema v33 — run AFTER schema-v32.sql (idempotent).
--
-- ═══ Fixing v31: a BEFORE INSERT trigger cannot read its own row ═══
--
-- v31 decided whether a row was a reply by looking it up:
--
--     select coalesce(thread_position, 0) > 0 into is_reply
--       from public.marketing_tasks where id = p_id;
--
-- with a comment claiming this kept the trigger signature unchanged. The
-- reasoning was wrong in the one case that matters. marketing_tasks_caps is a
-- BEFORE INSERT trigger, so the row is not in the table when the lookup runs:
-- it found nothing, is_reply came back NULL, coalesce made it false, and every
-- reply was judged as a full post. R4 then refused reply 1 with 'slot taken'.
--
-- The whole of v31 was therefore inert on insert — threads were exactly as
-- impossible as before it. Caught by inserting a real six-row thread against
-- production inside a rolled-back transaction; reading the function could not
-- have shown it, because the SQL is correct in isolation and only wrong given
-- when it runs.
--
-- The position is now PASSED IN. That means a signature change and all three
-- callers move together: the trigger (insert), admin_marketing_reschedule
-- (moving one row), and admin_marketing_slots (previewing a picker's options).

drop function if exists public.marketing_slot_conflict(uuid, text, timestamptz, text, text);

create or replace function public.marketing_slot_conflict(
  p_id uuid, p_channel text, p_when timestamptz, p_metro text, p_status text,
  p_thread_position smallint default null)
returns text
language plpgsql stable security definer set search_path = public
as $$
declare
  local_ts timestamp;
  wk date;
  n int;
  is_reply boolean := coalesce(p_thread_position, 0) > 0;
begin
  if p_status = 'skipped' or p_channel is null or p_when is null then
    return null;
  end if;

  local_ts := p_when at time zone 'America/New_York';

  -- R1 applies to replies too: a reply is posted at the lead's time, and a slot
  -- edited by hand outside the calendar should still be refused.
  if not exists (select 1 from public.marketing_windows w
                  where w.channel = p_channel
                    and w.dow = extract(dow from local_ts)::smallint
                    and w.at_time = local_ts::time) then
    return format('%s has no posting window at %s ET', p_channel,
                  to_char(local_ts, 'Dy HH24:MI'));
  end if;

  -- R2. A thread spends one post of the cap, not one per row.
  if not is_reply then
    wk := public.marketing_week_start(p_when);
    select count(*) into n
      from public.marketing_tasks t
     where t.channel = p_channel
       and t.status <> 'skipped'
       and t.scheduled_for is not null
       and coalesce(t.thread_position, 0) = 0
       and public.marketing_week_start(t.scheduled_for) = wk
       and (p_id is null or t.id <> p_id);
    if n >= 3 then
      return format('weekly cap: %s already has 3 posts in the week of %s', p_channel, wk);
    end if;
  end if;

  -- R3. A reply neither burns a metro cooldown nor is subject to one; a roundup
  -- names several metros in passing and must not lock them out for a fortnight.
  if p_metro is not null and not is_reply then
    select count(*) into n
      from public.marketing_tasks t
     where t.metro_cbsa = p_metro
       and t.channel is not null
       and t.status <> 'skipped'
       and t.scheduled_for is not null
       and coalesce(t.thread_position, 0) = 0
       and t.scheduled_for between p_when - interval '14 days'
                               and p_when + interval '14 days'
       and (p_id is null or t.id <> p_id);
    if n > 0 then
      return format('metro %s is already scheduled within 14 days of %s',
                    p_metro, to_char(local_ts, 'YYYY-MM-DD'));
    end if;
  end if;

  -- R4. Must match marketing_tasks_slot_idx exactly. If they disagree the index
  -- wins silently and the operator gets a raw 23505 instead of a sentence.
  if not is_reply then
    if exists (select 1 from public.marketing_tasks t
                where t.channel = p_channel
                  and t.scheduled_for = p_when
                  and t.status <> 'skipped'
                  and coalesce(t.thread_position, 0) = 0
                  and (p_id is null or t.id <> p_id)) then
      return format('slot taken: %s already has a post at %s ET', p_channel,
                    to_char(local_ts, 'Dy HH24:MI'));
    end if;
  end if;

  return null;
end;
$$;

revoke execute on function
  public.marketing_slot_conflict(uuid, text, timestamptz, text, text, smallint)
  from public, anon, authenticated;


-- ————— Caller 1: the insert/update trigger —————
create or replace function public.marketing_tasks_guard()
returns trigger
language plpgsql security definer set search_path = public
as $$
declare msg text;
begin
  msg := public.marketing_slot_conflict(new.id, new.channel, new.scheduled_for,
                                        new.metro_cbsa, new.status,
                                        new.thread_position);
  if msg is not null then
    raise exception 'marketing cap refused: %', msg;
  end if;
  return new;
end;
$$;

-- The trigger must also fire when thread_position changes, or a row could be
-- demoted to a reply (escaping the cap) without being re-checked.
drop trigger if exists marketing_tasks_caps on public.marketing_tasks;
create trigger marketing_tasks_caps
  before insert or update of scheduled_for, channel, metro_cbsa, status, thread_position
  on public.marketing_tasks
  for each row execute function public.marketing_tasks_guard();


-- ————— Caller 2: moving one row —————
create or replace function public.admin_marketing_reschedule(tid uuid, p_when timestamptz)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
  ch text; metro text; st text; msg text; n int; tp smallint; tk text;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  if p_when is null then raise exception 'no time given'; end if;

  select channel, metro_cbsa, status, thread_position, thread_key
    into ch, metro, st, tp, tk
    from public.marketing_tasks where id = tid;
  if not found then raise exception 'no such task'; end if;
  if st not in ('suggested', 'scheduled') then
    raise exception 'only an unposted task can be moved';
  end if;

  msg := public.marketing_slot_conflict(tid, ch, p_when, metro, 'scheduled', tp);
  if msg is not null then
    raise exception 'reschedule refused: %', msg;
  end if;

  -- Moving a thread moves the whole thread. Dragging the lead to Friday while
  -- its replies stay on Sunday would publish a thread whose body is three days
  -- ahead of its opening; dragging a single reply is meaningless, since replies
  -- are posted in one sitting with the lead.
  if tk is not null then
    update public.marketing_tasks
       set scheduled_for = p_when, status = 'scheduled', status_updated_at = now()
     where thread_key = tk and status in ('suggested', 'scheduled');
  else
    update public.marketing_tasks
       set scheduled_for = p_when, status = 'scheduled', status_updated_at = now()
     where id = tid;
  end if;
  get diagnostics n = row_count;
  return jsonb_build_object('ok', n >= 1, 'scheduled_for', p_when, 'rows_moved', n);
end;
$$;

revoke execute on function public.admin_marketing_reschedule(uuid, timestamptz) from public, anon;
grant execute on function public.admin_marketing_reschedule(uuid, timestamptz) to authenticated;


-- ————— Caller 3: the slot picker —————
create or replace function public.admin_marketing_slots(tid uuid, p_days int default 21)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  ch text; metro text; tp smallint; out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  select channel, metro_cbsa, thread_position into ch, metro, tp
    from public.marketing_tasks where id = tid;
  if not found then raise exception 'no such task'; end if;
  if ch is null then return '[]'::jsonb; end if;

  select coalesce(jsonb_agg(jsonb_build_object(
           'at', g.slot,
           'label', to_char(g.slot at time zone 'America/New_York', 'Dy Mon DD HH24:MI'),
           'window', g.wlabel,
           'anchor', g.anchor,
           'ok', c.conflict is null,
           'reason', c.conflict) order by g.slot), '[]'::jsonb)
    into out
    from (select ((cal.d + w.at_time) at time zone 'America/New_York') as slot,
                 w.label as wlabel, w.anchor
            from (select ((now() at time zone 'America/New_York')::date + g) as d
                    from generate_series(0, greatest(1, least(p_days, 90))) g) cal
            join public.marketing_windows w
              on w.channel = ch and w.dow = extract(dow from cal.d)::smallint) g
    cross join lateral (select public.marketing_slot_conflict(
                                 tid, ch, g.slot, metro, 'scheduled', tp)) c(conflict)
   where g.slot > now();
  return out;
end;
$$;

revoke execute on function public.admin_marketing_slots(uuid, int) from public, anon;
grant execute on function public.admin_marketing_slots(uuid, int) to authenticated;
