-- ShouldISellYet schema v2 — run AFTER schema.sql (safe to run anytime; idempotent).
-- Adds Stripe linkage columns used by the stripe-webhook edge function.

alter table public.subscribers
  add column if not exists stripe_customer_id text,
  add column if not exists stripe_subscription_id text;

create index if not exists subscribers_email_idx on public.subscribers (email);

-- Relax the zip check to tolerate Stripe-sourced rows where the postal code
-- was missing (webhook inserts '00000' as a sentinel for manual follow-up).
-- (No change needed if your original check allows 5 digits — '00000' passes.)
