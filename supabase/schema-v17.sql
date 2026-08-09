-- ShouldISellYet schema v17 — run AFTER schema-v16.sql (idempotent).
--
-- Form-hardening T1: the bot_rejected / turnstile_bypass counters, and the
-- closure of the raw anon INSERT path into subscribers.
--
-- APPLY ORDER MATTERS for section 2: revoke only after the site deploy that
-- switches the waitlist card and subscribe.html to the `signup` edge
-- function, or live signups fail in the interim. Section 1 is safe anytime —
-- edge functions treat counter-insert failure as non-fatal, so a function
-- deployed before this migration simply drops its counts until it lands.

-- ————— 1. Counter events —————
-- bot_rejected: a public form submission silently dropped by the honeypot or
--   the <2s timing check. turnstile_bypass: a submission allowed through
--   because the Turnstile script failed to load or keys aren't configured
--   (availability over lockout — see the T3 functions). Both are COUNTERS:
--   the row carries the event name, the hour bucket, and the function path.
--   No content, no identifier — counting is not tracking, so the privacy
--   page's "anonymous usage counts" sentence stays true.
alter table public.events drop constraint if exists events_event_check;
alter table public.events add constraint events_event_check
  check (event in ('page_view', 'zip_check', 'purchase_click_report',
                   'purchase_click_monitor', 'share_click',
                   'match_request_opened', 'bot_rejected', 'turnstile_bypass'));

-- ————— 2. Close the raw insert path —————
-- The browser writes subscriber rows through the `signup` edge function now,
-- which runs the honeypot/timing checks (and, from T2/T3, rate limits and
-- Turnstile) with the service key. The anon INSERT policy predates that
-- function and is the bypass around every one of those checks — a curl loop
-- with the public anon key could fill the table with strangers' addresses.
-- Do NOT re-add an anon policy on subscribers; add checks to the signup
-- function instead.
drop policy if exists "anon insert only" on public.subscribers;
revoke insert on table public.subscribers from anon, authenticated;
