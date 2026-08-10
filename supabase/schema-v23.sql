-- ShouldISellYet schema v23 — run AFTER schema-v22.sql (idempotent).
--
-- The marketing queue: the operator's to-do list, generated from the data.
--
-- WHAT THIS IS. Every suggested post and press pitch becomes a ROW with a
-- schedule slot, a rendered asset, a paste-ready caption, and — the part
-- that makes it a queue rather than a content dump — an explicit "why this,
-- why now" carrying the actual numbers. The pipeline writes rows with the
-- service key at each refresh; the admin Marketing tab reads and advances
-- them through admin RPCs. Nothing here posts anything. Nothing here sends
-- anything. The table is a list of things a human may choose to do.
--
-- THE CALENDAR IS DATA, NOT PROSE. Before this migration the posting rules
-- ("2/week", "Sunday 7:30p is the anchor") existed only in a brief. Three
-- readers need to agree on them — the Python generator, the admin tab's
-- reschedule picker, and whatever writes next year — so they live in
-- marketing_windows and in one conflict function that the table's own
-- trigger enforces. The client picker is a convenience; the trigger is the
-- boundary. A generator that tries to over-schedule gets an exception, not
-- a warning, which is what the brief means by "must REFUSE".
--
-- NUMBERING. schema-v20.sql and schema-v21.sql were each written twice and
-- two applied migrations were lost from the working tree; they are restored
-- by supabase/schema-repair-v20-v21.sql, which a fresh environment runs
-- before this file. v23 has no hard dependency on it (see source_id below).
-- Before writing schema-vNN.sql: ls supabase/schema-v*.sql | sort -V | tail -1.

-- ————— 1. events.utm_campaign —————
-- The performance loop joins posted tasks to events on the campaign token,
-- and there was nowhere to put one: web/track.js reads utm_source only, and
-- events has no props column by design (schema-v11: "nowhere to PUT an
-- identifier"). A campaign label is the same kind of value as utm_source —
-- an aggregate channel label typed into a URL by us, not a fact about a
-- person — so it lands as its own column under the same posture.
--
-- SHAPE, NOT ENUM. click_source (v22) is an enum because its values are a
-- short fixed list; campaign tokens are minted per task, so an enum is
-- impossible and free text would let junk accumulate. The compromise is a
-- shape: lowercase slug, 2–60 chars, the same regex marketing_tasks uses,
-- so a token the generator can store is always a token events can accept.
-- CONTRACT FOR THE TRACK FUNCTION: normalize to this shape and DROP THE
-- VALUE if it still doesn't match — never let a malformed campaign string
-- fail the insert, or one bad share link silently stops counting pageviews.
alter table public.events
  add column if not exists utm_campaign text
  check (utm_campaign is null or utm_campaign ~ '^[a-z0-9][a-z0-9_-]{1,59}$');

-- The campaign aggregate is the one other admin read that scans raw events,
-- for the same reason admin_top_zips does (schema-v13): the dimension is too
-- sparse to earn a place in the rollup. Partial index keeps it cheap — well
-- under 1% of rows will ever carry a campaign.
create index if not exists events_utm_campaign_idx
  on public.events (utm_campaign) where utm_campaign is not null;

-- WHY events_daily IS NOT REPLACED. It could take a seventh column, and the
-- v16 precedent shows how (append last, widen the group by, repeat the
-- revoke). It should not, for three reasons:
--   1. Nothing would read it. The performance join counts events for ONE
--      campaign token, which is unique per task — no day dimension needed,
--      no grouping to roll up. See marketing_perf_refresh below.
--   2. create-or-replace-view is append-only and irreversible in practice:
--      every column added is permanent ordering budget spent. Spending it on
--      a dimension with no consumer is the wrong trade.
--   3. Replacing the view means re-running "revoke all on public.events_daily
--      from anon, authenticated" — the step v11 says out loud not to skip.
--      Every replace is one chance to forget it and expose the rollup to the
--      anon key. Not replacing it is strictly safer.
-- If a future surface really needs campaign × day, append the column THEN,
-- and repeat the revoke in the same statement block.

-- ————— 2. The posting calendar, as rows —————
-- One row per (channel, weekday, wall-clock time) that a brand post is
-- allowed to occupy, in America/New_York because that is the clock the
-- audience keeps and the one the brief is written in. dow uses 0 = Sunday,
-- matching both Postgres extract(dow …) and JavaScript Date.getDay() so the
-- picker in admin.html needs no translation table.
--
-- CHANGING THE CALENDAR IS A MIGRATION, deliberately. Windows are the thing
-- every cap is measured against; an operator-editable toggle for them would
-- make "2 posts a week" mean whatever it meant last Tuesday.
create table if not exists public.marketing_windows (
  channel text not null check (channel in ('ig', 'x', 'fb', 'nextdoor_naomi')),
  dow     smallint not null check (dow between 0 and 6),   -- 0 = Sunday
  at_time time not null,
  label   text not null,
  anchor  boolean not null default false,   -- the week's top task goes here
  primary key (channel, dow, at_time)
);

alter table public.marketing_windows enable row level security;
revoke all on table public.marketing_windows from anon, authenticated;

-- NEXTDOOR / NAOMI IS ABSENT ON PURPOSE, AND THAT ABSENCE IS THE OFF SWITCH.
-- Naomi Todd is a real, independent licensed agent with no corporate
-- affiliation to this site (docs/ATTRIBUTION.md, correction dated
-- 2026-08-08; introductions are switched off pending a signed agreement).
-- The channel VALUE exists in the enum so the generator can name it, but
-- with zero windows no nextdoor_naomi task can ever be scheduled — the
-- conflict check below refuses it by construction. Same fail-closed shape as
-- web/referral.js. Turning it on is not a config flag flip; it is this
-- INSERT, dated, in a migration, after an agreement exists:
--
--   insert into public.marketing_windows (channel, dow, at_time, label, anchor)
--   values ('nextdoor_naomi', 2, '08:30', 'Tuesday morning', false)
--   on conflict do nothing;
insert into public.marketing_windows (channel, dow, at_time, label, anchor) values
  ('ig', 0, '19:30', 'Sunday anchor',     true),
  ('fb', 0, '19:30', 'Sunday anchor',     true),
  ('x',  0, '19:30', 'Sunday anchor',     true),
  ('ig', 3, '08:30', 'Wednesday morning', false),
  ('fb', 3, '08:30', 'Wednesday morning', false),
  ('x',  2, '08:30', 'Tuesday morning',   false),
  ('x',  3, '08:30', 'Wednesday morning', false)
on conflict (channel, dow, at_time) do nothing;

-- ————— 3. The queue —————
-- WHAT IS NOT IN HERE: no customer, no subscriber, no email address, no
-- personal input of any kind. Rows are about MARKETS — a metro, a ZIP, a
-- statistic — and asset_path points at an image the pipeline generated from
-- published aggregates, the same privacy contract og_card.py enforces in its
-- signature. A task is safe to screenshot by construction.
create table if not exists public.marketing_tasks (
  id         uuid primary key default gen_random_uuid(),
  created_at timestamptz not null default now(),

  -- The triage rule that produced this row. Each maps to a priority tier and
  -- a "why" template in the generator; the tier is stored, not recomputed, so
  -- a demotion that applied at generation time stays visible afterwards.
  type text not null check (type in
    ('post', 'press_pitch', 'burst', 'receipt_quote', 'evergreen')),

  -- NULL channel = not a brand social post (press pitches). Null-channel rows
  -- are exempt from both caps below: pitching an outlet about the metro you
  -- posted about is the point, not a duplicate.
  channel text check (channel is null or channel in
    ('ig', 'x', 'fb', 'nextdoor_naomi')),

  scheduled_for timestamptz,

  -- 0 burst · 1 record · 2 contrarian gap / receipt · 3 big-metro flip ·
  -- 4 geo rotation · 5 evergreen. Lower is louder. A skip-demotion adds 1.
  priority_score int not null check (priority_score between 0 and 5),

  -- The why engine's output. why_headline is one sentence with the number in
  -- it ("WSI hit 14.2% — highest since Mar 2023"); why_detail is 2–3
  -- newline-separated supporting lines, and for a press_pitch it carries the
  -- drafted email verbatim. Newlines, not an array: what the operator copies
  -- must be exactly what was reviewed.
  why_headline text not null,
  why_detail   text,

  -- Geography. metro_cbsa is the stable key every cap and the demotion rule
  -- group on; metro_name is display only (names get re-cut, codes don't).
  -- Mirrors press_corroboration's pair.
  metro_cbsa text,
  metro_name text,
  zip        text check (zip is null or zip ~ '^\d{5}$'),

  -- A PUBLIC path under the deployed site, not a filesystem path: no '..',
  -- no scheme, no query. build_research.py's social_set() is the writer.
  asset_path text check (asset_path is null or
                         asset_path ~ '^/[A-Za-z0-9._/-]+\.(png|jpg|webp)$'),

  caption  text,
  hashtags text,          -- one pre-rendered line; the Copy button copies it verbatim

  -- The join key for the performance loop, and the reason it is UNIQUE: two
  -- tasks sharing a token would each claim all of the other's clicks. Same
  -- shape as events.utm_campaign — keep the two regexes identical.
  utm_campaign text check (utm_campaign is null or
                           utm_campaign ~ '^[a-z0-9][a-z0-9_-]{1,59}$'),
  utm_url      text,

  status        text not null default 'suggested'
                check (status in ('suggested', 'scheduled', 'posted', 'skipped')),
  status_reason text check (status_reason is null or status_reason in
                  ('not_newsworthy', 'timing', 'duplicate', 'other')),
  status_updated_at timestamptz,
  posted_at         timestamptz,

  -- Measured LATER by marketing_perf_refresh, and NULL until it has run for
  -- this row. Null is "not measured yet", 0 is "measured, drove nothing" —
  -- the house rule that a gap is never a zero, applied to a column. The
  -- numbers are STORED rather than joined live because raw events are purged
  -- at 90 days (schema-v11) and a card must not lose its history.
  perf_checks     int,
  perf_clicks     int,      -- purchase_click_report + purchase_click_monitor
  perf_checked_at timestamptz,

  -- The data month the refresh that generated this row was working from
  -- ('2026-08'), same convention as zip_velocity.period and the research
  -- releases. Lets the digest scope "this refresh's queue".
  period text check (period is null or period ~ '^\d{4}-(0[1-9]|1[0-2])$'),

  -- The receipt (press_corroboration.id) behind a receipt_quote task.
  -- DELIBERATELY NOT A FOREIGN KEY: admin_press_delete is a hard delete with
  -- no confirmation dialog, and a task that has already been POSTED is a
  -- record of something that happened in public. It must not vanish, or
  -- cascade-null, because a source row was tidied away. This also keeps v23
  -- independent of the v20/v21 repair file.
  source_id uuid,

  -- Generation is re-runnable: the refresh workflow can fire twice for the
  -- same period (a re-run, a manual dispatch). The generator composes a
  -- stable key — e.g. '2026-08|record|12420|ig' — and inserts with
  -- ?on_conflict=dedupe_key and Prefer: resolution=ignore-duplicates, so a
  -- second run is a no-op instead of a doubled queue.
  dedupe_key text,

  -- A skipped row must say why (the demotion rule reads it) and when (the
  -- 60-day window is measured from it). A posted row must say when. These
  -- are constraints, not conventions, because the service role can write
  -- here directly and the demotion rule silently under-counts a skip that
  -- forgot its stamp.
  constraint marketing_tasks_skip_reason_ck
    check (status <> 'skipped' or (status_reason is not null and status_updated_at is not null)),
  constraint marketing_tasks_posted_at_ck
    check (status <> 'posted' or posted_at is not null),

  -- docs/ATTRIBUTION.md bans these constructions anywhere in the repo. Copy
  -- generated here is pasted straight into public channels, which is the one
  -- place the ban actually costs something, so it is enforced rather than
  -- documented. A caption that trips this is refused at insert: fail closed.
  constraint marketing_tasks_no_affiliation_claim check (
    coalesce(why_headline, '') || ' ' || coalesce(why_detail, '') || ' ' ||
    coalesce(caption, '') || ' ' || coalesce(hashtags, '')
    !~* '(powered by|in partnership with|partnered with|official partner|official data source|endorsed by|sponsored by)'
  )
);

alter table public.marketing_tasks enable row level security;
revoke all on table public.marketing_tasks from anon, authenticated;

-- The week/month reads and the metro-dedupe check are all range scans on
-- scheduled_for; the leaderboard scans posted_at.
create index if not exists marketing_tasks_sched_idx
  on public.marketing_tasks (scheduled_for) where scheduled_for is not null;
create index if not exists marketing_tasks_status_idx
  on public.marketing_tasks (status, priority_score, scheduled_for);
create index if not exists marketing_tasks_metro_idx
  on public.marketing_tasks (metro_cbsa, scheduled_for) where metro_cbsa is not null;
create index if not exists marketing_tasks_posted_idx
  on public.marketing_tasks (posted_at) where status = 'posted';

-- One task per campaign token — see the column note.
create unique index if not exists marketing_tasks_campaign_idx
  on public.marketing_tasks (utm_campaign) where utm_campaign is not null;
create unique index if not exists marketing_tasks_dedupe_idx
  on public.marketing_tasks (dedupe_key) where dedupe_key is not null;

-- THE ONE RACE-PROOF CAP. The trigger below counts rows, which is correct
-- under the single-threaded generator but not against two concurrent
-- writers; this index cannot be raced. It is also the cap whose failure
-- actually publishes something wrong — two posts landing in the same slot on
-- the same channel is a visible double-post.
create unique index if not exists marketing_tasks_slot_idx
  on public.marketing_tasks (channel, scheduled_for)
  where status <> 'skipped' and channel is not null and scheduled_for is not null;

-- ————— 4. Calendar arithmetic —————
-- The marketing week starts SUNDAY, because the Sunday 19:30 ET anchor is
-- the first slot of the week, not the last of the previous one. Postgres
-- date_trunc('week') is Monday-based, hence the ±1 day. Local time, so a
-- post at 19:30 ET on a Sunday in March lands in the week that just began
-- and not the one that ended 30 minutes earlier in UTC.
create or replace function public.marketing_week_start(p_when timestamptz)
returns date
language sql immutable
as $$
  select (date_trunc('week', (p_when at time zone 'America/New_York') + interval '1 day')
          - interval '1 day')::date;
$$;

revoke execute on function public.marketing_week_start(timestamptz) from public, anon;
grant execute on function public.marketing_week_start(timestamptz) to authenticated;

-- Next scheduled data refresh, for the guidance strip. MIRRORS THE CRON in
-- .github/workflows/update.yml ('0 13 * * 1,4' — Mondays and Thursdays,
-- 13:00 UTC). If that cron changes, change this; a strip that promises the
-- wrong refresh day is worse than one that promises nothing.
create or replace function public.marketing_next_refresh()
returns timestamptz
language sql stable
as $$
  select min(d)
    from (select ((date_trunc('day', now() at time zone 'UTC')
                   + make_interval(days => g, hours => 13)) at time zone 'UTC') as d
            from generate_series(0, 7) g) t
   where extract(isodow from (d at time zone 'UTC')) in (1, 4)
     and d > now();
$$;

revoke execute on function public.marketing_next_refresh() from public, anon;
grant execute on function public.marketing_next_refresh() to authenticated;

-- One card shape, three readers (week, month, slots). Defined once so a new
-- column reaches every view at the same time. Composite argument, so it is
-- revoked from every client role — it is called from inside SECURITY DEFINER
-- functions, where the owner's own privilege applies, and PostgREST has no
-- business exposing it as an endpoint.
create or replace function public.marketing_task_json(t public.marketing_tasks)
returns jsonb
language sql immutable
as $$
  select jsonb_build_object(
    'id', t.id, 'created_at', t.created_at,
    'type', t.type, 'channel', t.channel,
    'scheduled_for', t.scheduled_for,
    'week_start', case when t.scheduled_for is null then null
                       else public.marketing_week_start(t.scheduled_for) end,
    'priority_score', t.priority_score,
    'why_headline', t.why_headline, 'why_detail', t.why_detail,
    'metro_cbsa', t.metro_cbsa, 'metro_name', t.metro_name, 'zip', t.zip,
    'asset_path', t.asset_path, 'caption', t.caption, 'hashtags', t.hashtags,
    'utm_campaign', t.utm_campaign, 'utm_url', t.utm_url,
    'status', t.status, 'status_reason', t.status_reason,
    'status_updated_at', t.status_updated_at, 'posted_at', t.posted_at,
    'perf_checks', t.perf_checks, 'perf_clicks', t.perf_clicks,
    'perf_checked_at', t.perf_checked_at,
    'period', t.period, 'source_id', t.source_id);
$$;

revoke execute on function public.marketing_task_json(public.marketing_tasks)
  from public, anon, authenticated;

-- ————— 5. The caps, in one place —————
-- Returns NULL when the placement is legal, or the sentence explaining the
-- refusal. Every writer goes through it: the trigger below (so the generator
-- and any service-role INSERT are covered), admin_marketing_reschedule (so
-- the operator is), and admin_marketing_slots (so the picker greys out what
-- would be refused instead of discovering it on submit).
--
-- The rules, in the order a human would check them:
--   R1  the slot is a window this channel actually has
--   R2  ≤ 2 brand posts per channel per marketing week
--   R3  no second post about the same metro within 14 days
--   R4  the exact slot is free
-- Null-channel rows (press pitches) occupy no slot and are exempt from all
-- four; skipped rows release everything they held.
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

  -- R2. Counting rows, not slots: a channel with three windows (x) can still
  -- only take two posts, which is the cap the brief actually states.
  wk := public.marketing_week_start(p_when);
  select count(*) into n
    from public.marketing_tasks t
   where t.channel = p_channel
     and t.status <> 'skipped'
     and t.scheduled_for is not null
     and public.marketing_week_start(t.scheduled_for) = wk
     and (p_id is null or t.id <> p_id);
  if n >= 2 then
    return format('weekly cap: %s already has 2 posts in the week of %s', p_channel, wk);
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

-- The refusal. An over-schedule raises; it does not warn, and it does not
-- quietly land as 'suggested with no slot'. NOTE FOR THE GENERATOR: insert
-- ONE ROW PER REQUEST. PostgREST sends an array as a single statement, so
-- one refused task would roll back every task in the batch.
create or replace function public.marketing_tasks_guard()
returns trigger
language plpgsql security definer set search_path = public
as $$
declare msg text;
begin
  msg := public.marketing_slot_conflict(new.id, new.channel, new.scheduled_for,
                                        new.metro_cbsa, new.status);
  if msg is not null then
    raise exception 'marketing cap refused: %', msg;
  end if;
  return new;
end;
$$;

-- create-or-replace-trigger is PG14+; drop-then-create is idempotent on any
-- version and leaves nothing behind if this file is re-run.
drop trigger if exists marketing_tasks_caps on public.marketing_tasks;
create trigger marketing_tasks_caps
  before insert or update of scheduled_for, channel, metro_cbsa, status
  on public.marketing_tasks
  for each row execute function public.marketing_tasks_guard();

-- ————— 6. Skip demotion, DERIVED —————
-- The rule: a metro skipped "not newsworthy" twice drops one priority tier
-- for 60 days. NO TABLE FOR THIS, on purpose. The rule is a pure function of
-- the skip log that already exists in marketing_tasks — a demotions table
-- would be a second source of truth that has to be kept in sync with the
-- skips that caused it, and would go stale the first time a task was deleted
-- or a status corrected. A view cannot drift from its inputs.
--
-- expires_at is the SECOND-most-recent qualifying skip plus 60 days: the
-- demotion holds while two skips sit inside the trailing window, so it
-- lapses exactly when the older of the pair ages out.
--
-- Both readers use this one definition — the Python generator selects it
-- with the service key at generation time, and admin_marketing_demotions
-- shows the operator what is currently demoted and until when. The generator
-- is responsible for the disclosure the brief requires: when a demoted metro
-- next appears, its why_detail says so.
create or replace view public.marketing_demotions as
  select metro_cbsa,
         max(metro_name) as metro_name,
         count(*)::int as skips,
         max(status_updated_at) as last_skip_at,
         (array_agg(status_updated_at order by status_updated_at desc))[2]
           + interval '60 days' as expires_at
    from public.marketing_tasks
   where status = 'skipped'
     and status_reason = 'not_newsworthy'
     and metro_cbsa is not null
     and status_updated_at >= now() - interval '60 days'
   group by metro_cbsa
  having count(*) >= 2;

-- Views run with their owner's rights and ignore RLS (schema-v11). This
-- revoke is what keeps the anon key out of it. Do not skip it.
revoke all on public.marketing_demotions from anon, authenticated;

-- ————— 7. The performance loop —————
-- Nightly. Joins posted tasks to events on the campaign token and freezes
-- the counts onto the row. Runs as a service-role job, NOT an admin RPC:
-- it writes derived numbers, and a button that silently rewrites measured
-- history is not something an operator should be able to press by accident.
--
-- No time window on the events side: a campaign token is unique to one task
-- and cannot exist before that task was posted, so every event carrying it
-- belongs to it. The 45-day cutoff is on the TASK side and is the point of
-- the whole design — raw events are purged at 90 days, so re-measuring an
-- older task would make its number shrink as its evidence expired. After 45
-- days the number stops moving and stands as the record.
create or replace function public.marketing_perf_refresh(p_days int default 45)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare touched int;
begin
  update public.marketing_tasks t
     set perf_checks = s.checks,
         perf_clicks = s.clicks,
         perf_checked_at = now()
    from (
      select t2.id,
             coalesce(e.checks, 0) as checks,
             coalesce(e.clicks, 0) as clicks
        from public.marketing_tasks t2
        left join (
          select utm_campaign,
                 count(*) filter (where event = 'zip_check')::int as checks,
                 count(*) filter (where event in
                   ('purchase_click_report', 'purchase_click_monitor'))::int as clicks
            from public.events
           where utm_campaign is not null
           group by utm_campaign
        ) e on e.utm_campaign = t2.utm_campaign
       where t2.status = 'posted'
         and t2.utm_campaign is not null
         and t2.posted_at >= now() - make_interval(days => greatest(1, p_days))
    ) s
   where t.id = s.id;
  get diagnostics touched = row_count;
  return jsonb_build_object('ok', true, 'tasks', touched, 'days', p_days);
end;
$$;

revoke execute on function public.marketing_perf_refresh(int)
  from public, anon, authenticated;

-- ————— 8. Admin RPCs —————
-- Same rules as every admin surface since v12: SECURITY DEFINER, is_admin()
-- first, EXECUTE revoked from public/anon and granted to authenticated. The
-- Marketing tab reads nothing except through these.

-- This week: the cards, the guidance strip, and the one thing to do today.
-- Overdue and unscheduled ride along in their own arrays — a task that
-- slipped past its slot must not disappear from the only screen that shows
-- it. p_week_start defaults to the current marketing week (Sunday-based).
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
    -- The operating rules, rendered live rather than typed into the HTML.
    'guidance', jsonb_build_object(
      'weekly_cap', 2,
      'anchor', 'Sunday 19:30 ET',
      -- Burst window state, derived: a rate move ≥ RATE_BURST_POINTS is what
      -- creates a burst task (pipeline/rate_watch.py), so an open window IS
      -- an unposted burst task inside its 48h.
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
    -- "If you do one thing today": highest priority still unposted, overdue
    -- rows included, earliest slot breaking the tie.
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

-- Month grid. Weeks are enumerated whether or not they hold anything, so an
-- empty allowed week can be flagged; `evergreen` is the standing suggestion
-- for filling one. p_month is 'YYYY-MM' (zip_velocity.period convention).
create or replace function public.admin_marketing_month(p_month text default null)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  mon text;
  m_start date;
  m_from timestamptz;
  m_to   timestamptz;
  out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  mon := coalesce(nullif(btrim(p_month), ''),
                  to_char(now() at time zone 'America/New_York', 'YYYY-MM'));
  if mon !~ '^\d{4}-(0[1-9]|1[0-2])$' then raise exception 'bad month'; end if;
  m_start := (mon || '-01')::date;
  m_from := (m_start::timestamp at time zone 'America/New_York');
  m_to   := ((m_start + interval '1 month') at time zone 'America/New_York');

  select jsonb_build_object(
    'month', mon,
    'days', (
      select coalesce(jsonb_agg(jsonb_build_object('day', d, 'tasks', tj)
                        order by d), '[]'::jsonb)
        from (select (t.scheduled_for at time zone 'America/New_York')::date as d,
                     jsonb_agg(public.marketing_task_json(t)
                       order by t.scheduled_for, t.priority_score) as tj
                from public.marketing_tasks t
               where t.scheduled_for >= m_from and t.scheduled_for < m_to
               group by 1) g),
    'weeks', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'week_start', k.ws,
               'scheduled', coalesce(c.sched, 0),
               'posted',    coalesce(c.posted, 0),
               'empty',     coalesce(c.sched, 0) + coalesce(c.posted, 0) = 0)
               order by k.ws), '[]'::jsonb)
        -- Integer series, not a date series: generate_series(date, date,
        -- interval) resolves to the timestamptz overload and would make the
        -- grid depend on the session TimeZone. Noon local sidesteps the DST
        -- midnights.
        from (select distinct public.marketing_week_start(
                       (((m_start + g) + time '12:00') at time zone 'America/New_York')) as ws
                from generate_series(0, 30) g
               where (m_start + g) < (m_start + interval '1 month')::date) k
        left join (select public.marketing_week_start(scheduled_for) as ws,
                          count(*) filter (where status in ('suggested', 'scheduled'))::int as sched,
                          count(*) filter (where status = 'posted')::int as posted
                     from public.marketing_tasks
                    where scheduled_for is not null
                    group by 1) c on c.ws = k.ws),
    'evergreen', (select public.marketing_task_json(t)
                    from public.marketing_tasks t
                   where t.type = 'evergreen' and t.status = 'suggested'
                   order by t.priority_score, t.created_at
                   limit 1)
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_marketing_month(text) from public, anon;
grant execute on function public.admin_marketing_month(text) to authenticated;

-- Mark posted. Only from an unposted state, so a double-click cannot move
-- posted_at and quietly re-open the 45-day measurement window.
create or replace function public.admin_marketing_mark_posted(tid uuid)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare n int;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  update public.marketing_tasks
     set status = 'posted', posted_at = now(), status_updated_at = now(),
         status_reason = null
   where id = tid and status in ('suggested', 'scheduled');
  get diagnostics n = row_count;
  return jsonb_build_object('ok', n = 1);
end;
$$;

revoke execute on function public.admin_marketing_mark_posted(uuid) from public, anon;
grant execute on function public.admin_marketing_mark_posted(uuid) to authenticated;

-- Skip. The reason is required and comes from the picklist because it is not
-- a note — 'not_newsworthy' twice on a metro is what feeds the demotion, and
-- free text could not be counted.
create or replace function public.admin_marketing_skip(tid uuid, p_reason text)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare n int;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  if p_reason is null or p_reason not in
     ('not_newsworthy', 'timing', 'duplicate', 'other') then
    raise exception 'bad reason';
  end if;

  update public.marketing_tasks
     set status = 'skipped', status_reason = p_reason, status_updated_at = now()
   where id = tid and status in ('suggested', 'scheduled');
  get diagnostics n = row_count;
  return jsonb_build_object('ok', n = 1);
end;
$$;

revoke execute on function public.admin_marketing_skip(uuid, text) from public, anon;
grant execute on function public.admin_marketing_skip(uuid, text) to authenticated;

-- Reschedule. THE CLIENT PICKER IS NOT A BOUNDARY — it renders what
-- admin_marketing_slots says is free, but this function re-runs every cap
-- against the row it is actually moving, and the trigger re-runs them again
-- on the UPDATE. A hand-crafted rpc('admin_marketing_reschedule', …) from
-- the browser console gets the same refusal the picker would have shown.
create or replace function public.admin_marketing_reschedule(tid uuid, p_when timestamptz)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare
  ch text; metro text; st text; msg text; n int;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  if p_when is null then raise exception 'no time given'; end if;

  select channel, metro_cbsa, status into ch, metro, st
    from public.marketing_tasks where id = tid;
  if not found then raise exception 'no such task'; end if;
  if st not in ('suggested', 'scheduled') then
    raise exception 'only an unposted task can be moved';
  end if;

  msg := public.marketing_slot_conflict(tid, ch, p_when, metro, 'scheduled');
  if msg is not null then
    raise exception 'reschedule refused: %', msg;
  end if;

  update public.marketing_tasks
     set scheduled_for = p_when, status = 'scheduled', status_updated_at = now()
   where id = tid;
  get diagnostics n = row_count;
  return jsonb_build_object('ok', n = 1, 'scheduled_for', p_when);
end;
$$;

revoke execute on function public.admin_marketing_reschedule(uuid, timestamptz) from public, anon;
grant execute on function public.admin_marketing_reschedule(uuid, timestamptz) to authenticated;

-- The picker's option list: every window this task's channel has in the next
-- p_days, each with the refusal reason attached when it is not available, so
-- the operator can see WHY a slot is greyed out rather than guessing. A task
-- with no channel (a press pitch) has no windows and returns an empty list.
create or replace function public.admin_marketing_slots(tid uuid, p_days int default 21)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  ch text; metro text; out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  select channel, metro_cbsa into ch, metro
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
    -- Days counted forward from TODAY IN ET, not current_date: current_date
    -- is the session's date, and after 20:00 ET the session (UTC) is already
    -- on tomorrow. An integer series also avoids the date/timestamptz
    -- overload ambiguity in generate_series.
    from (select ((cal.d + w.at_time) at time zone 'America/New_York') as slot,
                 w.label as wlabel, w.anchor
            from (select ((now() at time zone 'America/New_York')::date + g) as d
                    from generate_series(0, greatest(1, least(p_days, 90))) g) cal
            join public.marketing_windows w
              on w.channel = ch and w.dow = extract(dow from cal.d)::smallint) g
    cross join lateral (select public.marketing_slot_conflict(
                                 tid, ch, g.slot, metro, 'scheduled')) c(conflict)
   where g.slot > now();
  return out;
end;
$$;

revoke execute on function public.admin_marketing_slots(uuid, int) from public, anon;
grant execute on function public.admin_marketing_slots(uuid, int) to authenticated;

-- 30-day leaderboard + advisory lines.
--
-- ADVISORY ONLY. Nothing in this function changes a priority, a rotation or
-- a schedule; it returns sentences an operator may act on. Automatic
-- behaviour changes from performance data are not in scope and should not be
-- added here.
--
-- MEASURED ≠ ZERO. Posts the nightly join has not reached yet (perf_checks
-- null) are excluded from every median and from the "0 checks" rule, and
-- counted out loud in `unmeasured`. A leaderboard that treated an unrun job
-- as evidence of failure would recommend dropping a channel that is working.
create or replace function public.admin_marketing_leaderboard(days int default 30)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  since timestamptz := now() - make_interval(days => greatest(1, days));
  med numeric;
  unmeasured int;
  out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  select percentile_cont(0.5) within group (order by rate)
    into med
    from (select coalesce(sum(perf_checks), 0)::numeric / count(*) as rate
            from public.marketing_tasks
           where status = 'posted' and posted_at >= since
             and metro_cbsa is not null and perf_checks is not null
           group by metro_cbsa) m;

  select count(*)::int into unmeasured
    from public.marketing_tasks
   where status = 'posted' and posted_at >= since and perf_checks is null;

  select jsonb_build_object(
    'days', days,
    'unmeasured', unmeasured,
    'measured_through', (select max(perf_checked_at) from public.marketing_tasks),
    'by_metro', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'metro_cbsa', metro_cbsa, 'metro_name', metro_name,
               'posts', posts, 'measured', measured,
               'checks', checks, 'clicks', clicks)
               order by checks desc, posts desc), '[]'::jsonb)
        from (select metro_cbsa, max(metro_name) as metro_name,
                     count(*)::int as posts,
                     count(*) filter (where perf_checks is not null)::int as measured,
                     coalesce(sum(perf_checks), 0)::int as checks,
                     coalesce(sum(perf_clicks), 0)::int as clicks
                from public.marketing_tasks
               where status = 'posted' and posted_at >= since and metro_cbsa is not null
               group by metro_cbsa) t),
    'by_type', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'type', type, 'posts', posts, 'measured', measured,
               'checks', checks, 'clicks', clicks)
               order by checks desc, posts desc), '[]'::jsonb)
        from (select type, count(*)::int as posts,
                     count(*) filter (where perf_checks is not null)::int as measured,
                     coalesce(sum(perf_checks), 0)::int as checks,
                     coalesce(sum(perf_clicks), 0)::int as clicks
                from public.marketing_tasks
               where status = 'posted' and posted_at >= since
               group by type) t),
    'by_channel', (
      select coalesce(jsonb_agg(jsonb_build_object(
               'channel', channel, 'posts', posts, 'measured', measured,
               'checks', checks, 'clicks', clicks)
               order by checks desc, posts desc), '[]'::jsonb)
        from (select channel, count(*)::int as posts,
                     count(*) filter (where perf_checks is not null)::int as measured,
                     coalesce(sum(perf_checks), 0)::int as checks,
                     coalesce(sum(perf_clicks), 0)::int as clicks
                from public.marketing_tasks
               where status = 'posted' and posted_at >= since and channel is not null
               group by channel) t),
    'advisories', (
      select coalesce(jsonb_agg(a.line order by a.ord), '[]'::jsonb)
        from (
          -- Rotate up. Needs a real median (> 0) and at least 3 measured
          -- posts behind the metro, so one lucky post cannot rewrite the
          -- rotation — the same floor discipline as MIN_SOLD_FOR_ANGLE.
          select 1 as ord,
                 format('%s posts convert %sx the median — increase rotation',
                        coalesce(max(metro_name), metro_cbsa),
                        round((coalesce(sum(perf_checks), 0)::numeric / count(*)) / med, 1)
                       ) as line
            from public.marketing_tasks
           where status = 'posted' and posted_at >= since
             and metro_cbsa is not null and perf_checks is not null
           group by metro_cbsa
          having med is not null and med > 0 and count(*) >= 3
             and (coalesce(sum(perf_checks), 0)::numeric / count(*)) >= 3 * med

          union all

          -- Consider dropping. Only when every post on the channel has
          -- actually been measured — otherwise this is a report on the
          -- nightly job, not on the channel.
          select 2,
                 format('%s has driven 0 checks in %s days across %s posts — consider dropping',
                        channel, days, count(*))
            from public.marketing_tasks
           where status = 'posted' and posted_at >= since and channel is not null
           group by channel
          having count(*) >= 5
             and count(*) filter (where perf_checks is null) = 0
             and coalesce(sum(perf_checks), 0) = 0

          union all

          -- The labelled gap. Never a zero.
          select 3,
                 format('%s posted task(s) in this window are not measured yet — '
                        || 'the nightly performance join has not reached them. '
                        || 'Counted as unknown, not as zero.', unmeasured)
           where unmeasured > 0
        ) a)
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_marketing_leaderboard(int) from public, anon;
grant execute on function public.admin_marketing_leaderboard(int) to authenticated;

-- What is currently demoted, and until when. The tab shows it beside the
-- guidance strip so a quiet metro is explained rather than merely missing.
create or replace function public.admin_marketing_demotions()
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  select coalesce(jsonb_agg(jsonb_build_object(
           'metro_cbsa', metro_cbsa, 'metro_name', metro_name,
           'skips', skips, 'last_skip_at', last_skip_at,
           'expires_at', expires_at) order by expires_at desc), '[]'::jsonb)
    into out from public.marketing_demotions;
  return out;
end;
$$;

revoke execute on function public.admin_marketing_demotions() from public, anon;
grant execute on function public.admin_marketing_demotions() to authenticated;

-- NO CSV RPC. schedule.csv is the current month's scheduled tasks, which
-- admin_marketing_month already returns in full; the export button builds
-- the file client-side from data the tab has already fetched. A second
-- server-side rendering of the same rows is a second place for the two to
-- disagree about what "this month, scheduled only" means.
