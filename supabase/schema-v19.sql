-- ShouldISellYet schema v19 — run AFTER schema-v18.sql (idempotent).
--
-- Form-hardening T4: double opt-in for recurring email.
--
-- THE INVARIANT THIS CREATES — and why it must not be "simplified" away:
-- no recurring email ever goes to an address that has not either (a) paid,
-- or (b) clicked a signed confirm link. confirmed_at is the single flag for
-- both: the Stripe webhook stamps it on payment (a card charge verifies the
-- address better than any click), and the `confirm` edge function stamps it
-- when the signed link is opened. Every sender of RECURRING mail filters on
-- it (today's senders filter on paid status, which implies it; a future
-- waitlist sender MUST filter confirmed_at is not null).
--
-- This is the primary defense against signing up a third party's address to
-- harass them — an unconfirmed address receives exactly ONE email, ever, the
-- confirm request — and it protects the Resend sender reputation: recurring
-- mail to addresses that never asked for it is how a sending domain ends up
-- suppressed or blocklisted, which would take the paid transactional flow
-- down with it.

alter table public.subscribers
  add column if not exists confirmed_at timestamptz;

-- Backfill: every paying subscriber is confirmed by payment, dated to the
-- purchase (or row creation where purchased_at predates schema-v13).
update public.subscribers
   set confirmed_at = coalesce(purchased_at, created_at)
 where confirmed_at is null
   and status in ('active', 'report', 'canceled')
   and source = 'stripe';

-- Pre-migration waitlist rows stay confirmed_at NULL and are deliberately
-- NOT purged (the 7-day purge in events_maintenance.py only touches rows
-- created after this migration): these people were promised "we'll tell you
-- when your ZIP goes live" before confirmation existed. They must not be
-- emailed recurring mail as-is; when the waitlist sender is built, its first
-- act for these rows is a single confirm request, not the announcement.
