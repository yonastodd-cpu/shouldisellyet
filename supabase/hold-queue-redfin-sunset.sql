-- Phase 0 of the Redfin→RentCast migration: hold the marketing queue.
--
-- Every queued post quotes a figure that Phase 0 has just taken off the site
-- and deep-links to a page now serving a "reading being refreshed" notice.
-- Posting one would publish a withdrawn number and land the reader on a page
-- that cannot support it.
--
-- status_reason is a four-value enum (not_newsworthy / timing / duplicate /
-- other), so the reason is recorded HERE and in docs/REDFIN-SUNSET.md rather
-- than crammed into a column that cannot hold it. 'other' is the honest pick:
-- these are not stale, not duplicated, and not badly timed — their data source
-- was withdrawn underneath them.
--
-- REVERSIBLE. Only status and status_reason change. Phase 4 restores the ones
-- whose figures still hold after the formula rebuild; the rest should be
-- regenerated rather than un-skipped, because their numbers will have moved.
update public.marketing_tasks
   set status = 'skipped',
       status_reason = 'other',
       status_updated_at = now()
 where status in ('suggested', 'scheduled');
