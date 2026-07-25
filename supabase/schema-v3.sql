-- ShouldISellYet schema v3 — run AFTER schema.sql and schema-v2.sql (idempotent).
-- Adds the report access token used by the paywall (verify-access edge function).

alter table public.subscribers
  add column if not exists access_token uuid;

create index if not exists subscribers_token_idx on public.subscribers (access_token);

-- The token is read ONLY server-side (service role) by the verify-access function.
-- Do NOT add an anon SELECT policy for it — that would expose the table to the browser.
