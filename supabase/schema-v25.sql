-- ShouldISellYet schema v25 — run AFTER schema-v24.sql (idempotent).
--
-- ————— Two captions per task, and a short link that still measures —————
--
-- CAPTION_SHORT. X is not a premium account, so a post there has 280
-- characters including the link and the tags. The long caption is not
-- truncatable into that — a hook, a contrast, a why-now and an attribution
-- line do not survive being cut mid-sentence — so the generator writes TWO
-- captions from the same facts and the channel decides which one is the post.
-- Stored rather than derived because the operator copies what was reviewed:
-- a caption re-shortened at render time is not the caption anyone approved.
--
-- SHORT_PATH. The visible link used to be the full UTM URL, which is ugly in
-- a caption, and the obvious fix — show the bare domain, keep the tracked URL
-- in the admin Copy button — silently breaks the performance loop: the
-- operator pastes the caption, the posted link carries no campaign token, and
-- perf_checks measures nothing for the life of the post. So the short link is
-- a REAL destination: pipeline/post_pack.py writes a static redirect page at
-- /go/{token}/ that bounces to /?utm_source=…&utm_campaign={token}, the same
-- trick /s/{zip} already uses on a host with no server. The link a reader
-- sees and the link that gets counted are the same link.
--
-- The token stays in the path on purpose. A prettier slug (/go/gr) would need
-- a slug→campaign map that can drift, collide between metros, or 404 a post
-- that is already public. Self-describing costs a few characters and cannot
-- come apart.

alter table public.marketing_tasks
  add column if not exists caption_short text;

alter table public.marketing_tasks
  add column if not exists short_path text
  check (short_path is null or short_path ~ '^/go/[a-z0-9][a-z0-9_-]{1,59}/$');

-- Lint results, so the admin card can show WHY a caption is questionable
-- without re-running the linter in JavaScript (one implementation, in Python,
-- next to the templates it checks). Empty array = clean; null = never linted.
alter table public.marketing_tasks
  add column if not exists lint jsonb;

comment on column public.marketing_tasks.caption_short is
  'The <=280 variant, written for X. Not a truncation of caption.';
comment on column public.marketing_tasks.short_path is
  'Site-relative path of the generated redirect that carries the campaign token.';
comment on column public.marketing_tasks.lint is
  'Array of lint failure strings from the generator; [] means it passed.';


-- The card shape gains the three new fields. Same definition as v23 §4 plus
-- caption_short / short_path / lint — kept here rather than edited into v23 so
-- an environment that has already applied v23 converges by running v25.
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
    'utm_campaign', t.utm_campaign, 'utm_url', t.utm_url,
    'status', t.status, 'status_reason', t.status_reason,
    'status_updated_at', t.status_updated_at, 'posted_at', t.posted_at,
    'perf_checks', t.perf_checks, 'perf_clicks', t.perf_clicks,
    'perf_checked_at', t.perf_checked_at,
    'period', t.period, 'source_id', t.source_id);
$$;

revoke execute on function public.marketing_task_json(public.marketing_tasks)
  from public, anon, authenticated;
