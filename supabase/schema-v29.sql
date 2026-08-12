-- ShouldISellYet schema v29 — run AFTER schema-v28.sql (idempotent).
--
-- ————— /methodology is a destination too —————
--
-- v26 constrained link_target to /metro/, /zip/ and /research/, which were the
-- three destinations that existed when it was written. The explainer post type
-- (v28) links to /methodology/ — the page that defines the vocabulary every
-- other post uses — and the constraint refused it.
--
-- Caught by the generator's own end-to-end test rather than in production,
-- which is the argument for having written it: the rule was right and its
-- enumeration was simply a month older than the feature.
alter table public.marketing_tasks
  drop constraint if exists marketing_tasks_link_target_check;

alter table public.marketing_tasks
  add constraint marketing_tasks_link_target_check
  check (link_target is null
         or link_target ~ '^/(metro|zip|research)/[A-Za-z0-9._-]+/$'
         or link_target = '/methodology/');
