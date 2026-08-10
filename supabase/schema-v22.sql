-- ShouldISellYet schema v22 — run AFTER schema-v21.sql (idempotent).
--
-- click_source on events: which SURFACE a purchase click came from, when a
-- page has more than one instance of the same CTA. First value: 'sticky_bar'
-- (the mobile docked unlock bar) — inline surfaces send nothing and stay
-- null, so the sticky bar's contribution is measurable against the inline
-- bar without re-tagging every existing CTA. Extend the check by migration
-- when a new surface needs its own value; free text is deliberately not
-- allowed (an enum can't silently accumulate junk).
alter table public.events
  add column if not exists click_source text
  check (click_source is null or click_source in ('sticky_bar'));
