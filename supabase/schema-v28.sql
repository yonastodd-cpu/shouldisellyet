-- ShouldISellYet schema v28 — run AFTER schema-v27.sql (idempotent).
--
-- ————— post_type: what KIND of story a row is —————
--
-- `type` already says what the row is mechanically (post / press_pitch /
-- burst / receipt_quote / evergreen) and drives the caps: a null-channel row
-- occupies no window. post_type says what it is EDITORIALLY, which is a
-- different question and the one the monthly slate is judged on. A month of
-- nine metro movers and nothing else is nine valid rows and a bad slate.
--
-- Kept as a second column rather than folded into `type` because the two axes
-- genuinely differ: an explainer and a national pulse are both `post` and both
-- occupy a window, and nothing about scheduling should have to care which is
-- which.
alter table public.marketing_tasks
  add column if not exists post_type text
  check (post_type is null or post_type in (
    'metro_mover',      -- a metro newly shifting; surface vs underneath
    'zip_spotlight',    -- one ZIP as a micro-profile
    'national_pulse',   -- the aggregate, "lowest/highest since"
    'recap_thread',     -- lead + replies (see thread_key / thread_position)
    'divergence',       -- two metros, same headlines, opposite signals
    'threshold_event',  -- a genuine first or crossing
    'steady_market',    -- a market that looks fine and is fine
    'explainer',        -- one concept, evergreen
    'contrarian',       -- the narrative and the data disagree
    'receipt',          -- the press caught up to a flag
    'burst',            -- a rate move opened a window
    'press_pitch'       -- an outlet batch
  ));

comment on column public.marketing_tasks.post_type is
  'Editorial shape, for the monthly mix. `type` is the mechanical kind.';

create index if not exists marketing_tasks_post_type_idx
  on public.marketing_tasks (period, post_type);

-- The mix meter: how this month's slate compares to the quota it is supposed
-- to hit. Advisory in exactly the sense the leaderboard is — it returns counts
-- and nothing acts on them. The quotas live in pipeline/marketing_config.py
-- (the operator edits them there) and are passed in, so this function has no
-- opinion of its own to drift from.
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
    'total', (select count(*) from public.marketing_tasks where period = per),
    'by_type', (select coalesce(jsonb_object_agg(pt, n), '{}'::jsonb)
                  from (select coalesce(post_type, 'unclassified') as pt,
                               count(*)::int as n
                          from public.marketing_tasks
                         where period = per
                         group by 1) t)
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_marketing_mix(text) from public, anon;
grant execute on function public.admin_marketing_mix(text) to authenticated;

create or replace function public.marketing_task_json(t public.marketing_tasks)
returns jsonb
language sql immutable
as $$
  select jsonb_build_object(
    'id', t.id, 'created_at', t.created_at,
    'type', t.type, 'post_type', t.post_type, 'channel', t.channel,
    'thread_key', t.thread_key, 'thread_position', t.thread_position,
    'scheduled_for', t.scheduled_for,
    'week_start', case when t.scheduled_for is null then null
                       else public.marketing_week_start(t.scheduled_for) end,
    'priority_score', t.priority_score,
    'why_headline', t.why_headline, 'why_detail', t.why_detail,
    'metro_cbsa', t.metro_cbsa, 'metro_name', t.metro_name, 'zip', t.zip,
    'asset_path', t.asset_path, 'caption', t.caption, 'hashtags', t.hashtags,
    'caption_short', t.caption_short, 'short_path', t.short_path, 'lint', t.lint,
    'link_target', t.link_target,
    'utm_campaign', t.utm_campaign, 'utm_url', t.utm_url,
    'status', t.status, 'status_reason', t.status_reason,
    'status_updated_at', t.status_updated_at, 'posted_at', t.posted_at,
    'perf_checks', t.perf_checks, 'perf_clicks', t.perf_clicks,
    'perf_checked_at', t.perf_checked_at,
    'period', t.period, 'source_id', t.source_id);
$$;

revoke execute on function public.marketing_task_json(public.marketing_tasks)
  from public, anon, authenticated;
