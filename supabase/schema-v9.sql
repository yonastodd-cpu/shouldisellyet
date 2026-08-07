-- ShouldISellYet schema v9 — run AFTER schema-v8.sql (idempotent).
--
-- Auto-renewal compliance. Selling a subscription that renews without saying
-- so, and without a way to cancel, is what the state auto-renewal statutes are
-- about. Three of the four requirements are copy; this is the data behind the
-- fourth — telling people BEFORE the renewal lands.
--
--   billing_interval          'annual' | 'monthly'. Which plan they are on.
--                             `plan` only says monitor/report, so without this
--                             there is no way to tell who gets an annual
--                             renewal reminder.
--
--   current_period_end        When the paid period ends. Written from Stripe's
--                             customer.subscription.created / .updated events,
--                             which carry it in the payload — so no Stripe API
--                             key is needed to keep it current.
--
--   renewal_reminder_sent_for The period_end a reminder was already sent for,
--                             NOT a boolean. A subscription renews every year:
--                             a flag would mark it done forever after the first
--                             one. Storing which period it covered makes the
--                             job idempotent per period and correct on renewal.

alter table public.subscribers
  add column if not exists billing_interval          text,
  add column if not exists current_period_end        timestamptz,
  add column if not exists renewal_reminder_sent_for timestamptz;

comment on column public.subscribers.renewal_reminder_sent_for is
  'The current_period_end a renewal reminder was sent for. Idempotency is per '
  'PERIOD, not per subscriber — a boolean would silence every future renewal.';

-- The reminder job scans for annual subscriptions ending in a ~30-day window
-- that have not been reminded for that period yet.
create index if not exists subscribers_renewal_idx
  on public.subscribers (billing_interval, current_period_end)
  where status = 'active';
