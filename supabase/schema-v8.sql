-- ShouldISellYet schema v8 — run AFTER schema-v7.sql (idempotent).
--
-- Records WHICH referring-agent disclosure each introduction request saw.
--
-- `consent_text` (schema-v5) already stores the consent wording verbatim. This
-- is the other half: the disclosure shown AFTER submission — who handles the
-- request, and that their brokerage may receive a referral fee if the person
-- goes on to work with an introduced agent.
--
-- Two columns rather than one:
--
--   disclosure_version  — short, indexable, and records the VARIANT as well as
--                         the date ("2026-08-05.v1-full" vs "…-generic"). The
--                         generic variant is what ships while a credential is
--                         missing, and it is a materially different disclosure,
--                         so it must be distinguishable at a glance.
--
--   disclosure_text     — the wording itself, verbatim. A version string only
--                         helps if you still have the text it points at, and
--                         copy in a repo moves. Same reasoning as consent_text:
--                         if someone ever asks "what was I told", the answer
--                         should come from the row, not from git archaeology.
--
-- Nullable on purpose: rows written before this migration genuinely have no
-- disclosure recorded, and backfilling a guess would be worse than a null.

alter table public.match_requests
  add column if not exists disclosure_version text,
  add column if not exists disclosure_text    text,
  add column if not exists disclosure_shown_at timestamptz;

comment on column public.match_requests.disclosure_version is
  'Which referring-agent disclosure this person saw, e.g. 2026-08-05.v1-full. '
  'The -generic suffix means a credential was missing and the fallback text ran.';

create index if not exists match_requests_disclosure_idx
  on public.match_requests (disclosure_version);
