-- ShouldISellYet schema v7 — run AFTER schema-v6.sql (idempotent).
--
-- Exactly-once post-purchase email.
--
-- Two separate problems, two columns.
--
-- 1. `stripe_session_id` — DUPLICATE ROWS.
--    Stripe retries a webhook until it gets a 2xx, and can deliver the same
--    event more than once regardless. The old handler flipped the pending row
--    to active on the first delivery, so a retry found no pending row, fell
--    through to its INSERT branch, and created a SECOND active row with a
--    second access token — and sent a second welcome email. Keying on the
--    Stripe session id makes a retry recognisable as the same purchase.
--
--    The unique index is what actually enforces it: two concurrent deliveries
--    can both see "no existing row" and both try to insert, and only the
--    database can break that tie. Partial, so the many rows with no session
--    id (manual signups, waitlist) don't collide on null.
--
-- 2. `report_email_sent_at` — DOUBLE SENDS.
--    Separate from row identity: a row can exist while its email hasn't gone
--    out (a Resend outage on the first delivery). The handler claims the send
--    with a conditional update — `set report_email_sent_at = now() where it
--    is null` — and only sends if that update returns a row. Whoever wins the
--    update sends; everyone else skips. A timestamp rather than a boolean so
--    support can see WHEN it went out.
--
--    Named for the report email but it guards the monitor welcome email too:
--    one post-purchase email per purchase, whichever plan it is.

alter table public.subscribers
  add column if not exists stripe_session_id    text,
  add column if not exists report_email_sent_at timestamptz;

create unique index if not exists subscribers_stripe_session_idx
  on public.subscribers (stripe_session_id)
  where stripe_session_id is not null;

comment on column public.subscribers.report_email_sent_at is
  'When the post-purchase access email went out. Null = not yet sent; the '
  'webhook claims it with a conditional update so retries cannot double-send.';
