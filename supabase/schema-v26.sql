-- ShouldISellYet schema v26 — run AFTER schema-v25.sql (idempotent).
--
-- ————— Where the click lands —————
--
-- Every post used to link to the homepage. Someone who tapped "76% of the ZIP
-- codes we track in Grand Rapids are moving toward a danger line" arrived
-- somewhere that does not mention Grand Rapids, which throws the click away
-- and wastes the only asset a post has.
--
-- link_target is the site-relative page the post opens — /metro/{slug}/,
-- /zip/{zip}/ or /research/{yyyy-mm}/ — resolved most-specific-first by the
-- generator and baked into utm_url. Stored so the admin card can show the
-- destination beside the post, and so a homepage link is visible as data
-- rather than only as a lint string.
--
-- The check refuses "/" outright: the homepage is not a destination for a post
-- about one market, and a constraint says so where a convention would drift.
alter table public.marketing_tasks
  add column if not exists link_target text
  check (link_target is null or link_target ~ '^/(metro|zip|research)/[A-Za-z0-9._-]+/$');

comment on column public.marketing_tasks.link_target is
  'Site-relative deep destination. The homepage is not permitted.';

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
