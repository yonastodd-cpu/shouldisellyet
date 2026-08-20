-- ShouldISellYet schema v36 — run AFTER schema-v35.sql (idempotent).
--
-- ═══ The release allowlist, where a server can read it ═══
--
-- Phase 4 releases ZIPs in tranches, and pipeline/tranches.json is the file
-- that records it. That file works for the BUILD, which reads the repo. It
-- cannot work for an Edge Function, which does not.
--
-- Without a server-side copy the only way for market-reading to decide
-- whether a ZIP may be served is to trust the caller, and "is this ZIP
-- released?" is exactly the question a caller must not be allowed to answer.
-- So this table is the durable twin of tranches.json, the same relationship
-- market_jobs already has with the runner's CSV ledger.
--
-- WRITTEN BY pipeline/promote_tranche.py --release, which is also what stamps
-- released_utc in the JSON. The two are written together on purpose: a ZIP
-- released in one and not the other is a page that renders a reading the API
-- refuses to serve, or the reverse.

create table if not exists public.zip_release (
  zip         text primary key check (zip ~ '^\d{5}$'),
  tranche     text not null,
  basis       text not null default 'active listings',
  released_at timestamptz not null default now()
);

alter table public.zip_release enable row level security;
revoke all on table public.zip_release from anon, authenticated;
-- Read by the market-reading function with the service-role key, written by
-- the release tool. No browser path exists and none should be added: the
-- allowlist is a server-side authority, and a client that could read it could
-- also enumerate what is about to be published.

create index if not exists zip_release_tranche_idx on public.zip_release (tranche);

comment on table public.zip_release is
  'Server-readable copy of the Phase 4 release allowlist. The durable twin of pipeline/tranches.json — the build reads the file, the API reads this. A ZIP in one and not the other is a page whose reading the API will not serve, or the reverse.';
comment on column public.zip_release.basis is
  'The reading basis this ZIP was released on. Present so a future basis change is a visible column rather than an assumption.';
