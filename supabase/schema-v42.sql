-- schema-v42 — paid-coverage-gap demand outcome (2026-08-28).
--
-- WHY. A paying customer's report page can now trigger the on-demand pull
-- itself (the checkout page was previously the only caller). When THAT pull
-- fails the floor, the failure is not an anonymous coverage-gap data point —
-- it is a person who has already paid and is being served a partial report.
-- At current scale that is a personal-follow-up event, so it gets its own
-- outcome value the admin demand report can surface separately, and the
-- ondemand-pull function emails the operator when it writes one.
--
-- 'paid_coverage_gap' is SERVER-WRITTEN ONLY, like the pull_* outcomes: the
-- demand edge function's OUTCOMES allowlist does not accept it from clients
-- (see supabase/functions/demand/index.ts).
--
-- Apply: npx supabase db query --linked "$(cat supabase/schema-v42.sql)"

alter table public.zip_lookups
  drop constraint if exists zip_lookups_outcome_check;

alter table public.zip_lookups
  add constraint zip_lookups_outcome_check check (outcome in
    ('reading_shown', 'notice_shown', 'invalid_zip',
     'pull_failed', 'pull_capacity', 'paid_coverage_gap'));
