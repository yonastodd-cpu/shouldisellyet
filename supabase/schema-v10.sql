-- ShouldISellYet schema v10 — run AFTER schema-v9.sql (idempotent).
--
-- Marketing opt-out, for CAN-SPAM.
--
-- The distinction this column enforces: TRANSACTIONAL mail keeps flowing to
-- everyone (the report link they paid for, verdict alerts they subscribed to,
-- billing notices before a renewal). Only PROMOTIONAL content is suppressed —
-- today that is exactly one thing, the MyMarketCheckup upsell block inside the
-- report-access email.
--
-- Opting out of marketing must not silently cancel the product. Someone who
-- clicks unsubscribe on an upsell still needs the report they bought and still
-- needs to be told before their card is charged again. So this flag is read
-- ONLY where promotional content is assembled — never as a gate on sending.

alter table public.subscribers
  add column if not exists marketing_opt_out    boolean not null default false,
  add column if not exists marketing_opt_out_at timestamptz;

comment on column public.subscribers.marketing_opt_out is
  'Suppresses PROMOTIONAL content only (currently the report email upsell). '
  'Transactional mail — report access, verdict alerts, renewal notices — is '
  'sent regardless, and must stay that way.';
