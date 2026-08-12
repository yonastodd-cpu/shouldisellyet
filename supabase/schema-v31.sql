-- ShouldISellYet schema v31 — run AFTER schema-v30.sql (idempotent).
--
-- ═══ A thread is ONE post that happens to be many rows ═══
--
-- v27 added thread_key and thread_position and stated that every row of a
-- thread shares one scheduled slot. It did not change any of the rules that
-- make that impossible. As shipped, a six-row thread fails four separate ways:
--
--   1. marketing_tasks_slot_idx is UNIQUE on (channel, scheduled_for) — reply 1
--      collides with the lead. This is the index v23 calls "THE ONE RACE-PROOF
--      CAP", so it cannot simply be dropped.
--   2. marketing_slot_conflict R4 is the readable version of the same rule and
--      refuses the same row with 'slot taken'.
--   3. R2 counts ROWS against the weekly cap, so a six-row thread would consume
--      six of a channel's three posts — it could never be placed even alone.
--   4. R3's 14-day metro cooldown would fire for every metro a reply names,
--      poisoning the calendar for six metros to publish one roundup.
--
-- THE ORGANISING IDEA, and every change below follows from it: a REPLY is not a
-- post. It occupies no slot, spends no cap, and burns no cooldown, because the
-- reader receives it as the body of the post its lead already accounted for.
-- Only leads (thread_position = 0) and standalone posts (NULL) are posts.
--
-- coalesce(thread_position, 0) = 0 is therefore the single predicate added
-- everywhere: it selects standalone posts AND leads, and excludes replies. Two
-- unrelated posts still can never share a slot; the cap still binds.


-- ————— 1. The race-proof cap, narrowed rather than weakened —————
-- Same uniqueness for everything that is a post; replies step out of it.
drop index if exists public.marketing_tasks_slot_idx;
create unique index marketing_tasks_slot_idx
  on public.marketing_tasks (channel, scheduled_for)
  where status <> 'skipped' and channel is not null and scheduled_for is not null
    and coalesce(thread_position, 0) = 0;


-- ————— 2. The four rules —————
create or replace function public.marketing_slot_conflict(
  p_id uuid, p_channel text, p_when timestamptz, p_metro text, p_status text)
returns text
language plpgsql stable security definer set search_path = public
as $$
declare
  local_ts timestamp;
  wk date;
  n int;
  is_reply boolean;
begin
  if p_status = 'skipped' or p_channel is null or p_when is null then
    return null;
  end if;

  -- The row's own position decides which rules apply to it. Read from the row
  -- rather than passed in, so the trigger signature is unchanged and every
  -- existing caller keeps working.
  select coalesce(thread_position, 0) > 0 into is_reply
    from public.marketing_tasks where id = p_id;
  is_reply := coalesce(is_reply, false);

  local_ts := p_when at time zone 'America/New_York';

  -- R1 still applies to replies: a reply cannot be posted into a window its
  -- channel does not have, because it is posted at the lead's time and the lead
  -- had to clear this same check. Keeping it costs nothing and means a reply
  -- whose slot was edited by hand cannot drift outside the calendar.
  if not exists (select 1 from public.marketing_windows w
                  where w.channel = p_channel
                    and w.dow = extract(dow from local_ts)::smallint
                    and w.at_time = local_ts::time) then
    return format('%s has no posting window at %s ET', p_channel,
                  to_char(local_ts, 'Dy HH24:MI'));
  end if;

  -- R2. Threads count ONCE. The subject of the cap is posts, and the reader
  -- receives a thread as one post.
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

  -- R3. A reply neither burns a cooldown nor is subject to one. A recap names
  -- several metros in passing; treating each mention as a dedicated post would
  -- lock six metros out of the calendar for a fortnight to publish one roundup,
  -- and would let the roundup be refused by a metro it merely lists.
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

  -- R4. The readable version of marketing_tasks_slot_idx, narrowed to match it
  -- exactly. If these two ever disagree, the index wins silently and the
  -- operator gets a raw 23505 instead of a sentence.
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
  public.marketing_slot_conflict(uuid, text, timestamptz, text, text)
  from public, anon, authenticated;


-- ————— 3. No orphan replies —————
-- A reply with no lead is a post into the void: it carries a slot and a link
-- and nothing introduces it. The generator MUST insert position 0 first.
--
-- This is deliberately an INSERT-time check and not a foreign key. v27 chose
-- position over a parent uuid so that a refused row could not roll back its
-- siblings, and an FK would reintroduce exactly that coupling. A check gives
-- the guarantee without the cascade — and it makes a refused LEAD abort its own
-- replies, which is the behaviour you want: better no thread than half a one.
create or replace function public.marketing_thread_guard()
returns trigger
language plpgsql security definer set search_path = public
as $$
begin
  if new.thread_position is not null and new.thread_position > 0
     and not exists (select 1 from public.marketing_tasks
                      where thread_key = new.thread_key and thread_position = 0) then
    raise exception 'thread % has no lead: insert thread_position 0 before reply %',
      new.thread_key, new.thread_position;
  end if;
  return new;
end;
$$;

drop trigger if exists marketing_tasks_thread on public.marketing_tasks;
create trigger marketing_tasks_thread
  before insert on public.marketing_tasks
  for each row execute function public.marketing_thread_guard();


-- ————— 4. Gaps are reported, not prevented —————
-- Contiguity cannot be enforced row by row: every thread is momentarily
-- incomplete while it is being written. A view costs nothing and cannot drift
-- from its input, the same argument marketing_demotions makes.
create or replace view public.marketing_thread_gaps as
  select thread_key,
         min(period)            as period,
         count(*)               as rows_present,
         max(thread_position)   as highest_position,
         max(thread_position) + 1 - count(*) as missing
    from public.marketing_tasks
   where thread_key is not null and status <> 'skipped'
   group by thread_key
  having max(thread_position) + 1 <> count(*)
      or bool_or(thread_position = 0) is not true;

revoke all on public.marketing_thread_gaps from anon, authenticated;
