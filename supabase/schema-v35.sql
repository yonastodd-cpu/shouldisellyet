-- ShouldISellYet schema v35 — run AFTER schema-v34.sql (idempotent).
--
-- ═══ The RentCast landing tables (migration Phase 1, §1.4) ═══
--
-- Two tables and nothing else: where bought market data lands, and what was
-- bought. Neither is read by any published surface — Phase 3 rebuilds the
-- verdict on this data, Phase 4 re-enables the pages. Creating them early is
-- the point: the plan's §1.4 sits at Days 0–4, BEFORE the first paid call,
-- because two of its columns cannot be added retroactively without buying
-- the data again.
--
-- NUMBERING. v34 was the last applied file (ls supabase/schema-v*.sql |
-- sort -V | tail -1). v20/v21 were each written twice and two migrations
-- were lost from the working tree; schema-repair-v20-v21.sql exists because
-- of it. Check before writing v36.

-- ═════════════════════════════════════════════════════════════════════════
-- 1. market_stats — one row per ZIP, per month, per vendor
-- ═════════════════════════════════════════════════════════════════════════
--
-- WHY raw_json IS NOT NULL. This is Lever 2 of the cost plan, in a column.
-- One /markets call returns current statistics plus twelve months of history
-- plus breakdowns by property type and bedroom count; RentCast's terms permit
-- storing it. Keep the whole payload and every later formula revision,
-- threshold recalibration and backtest runs against local data at $0. Drop it
-- and Phase 3's "backtest against your stored raw JSON, not the live API"
-- becomes a second purchase of bytes already bought. A parsed column is a
-- decision about what mattered, made before anyone knew.
--
-- WHY retrieved_at IS NOT NULL, AND NOT BACKFILLABLE. v34 had to approximate
-- this for 27,405 zip_velocity rows — last day of the period each described,
-- documented as an approximation because no true retrieval instant was ever
-- recorded. "When did you retrieve it" is the first question asked about
-- vendor data later, and Phase 0 could not answer it. The runner records the
-- real instant on write; this constraint is what stops that decaying.
--
-- WHY THE PRICE COLUMNS SAY list_. RentCast /markets statistics are computed
-- from ACTIVE LISTINGS. Redfin's were largely CLOSED SALES. A column named
-- median_price holding a list-price median is how a threshold validated on
-- sale prices gets applied to asking prices without anyone noticing — the
-- trend stays valid, the level reads high, and the verdict shifts for a
-- reason no one can see. The name carries the caveat into every query.
-- pipeline/fetch_rentcast.py's parser uses these same names.
--
-- WHAT IS DELIBERATELY ABSENT. No months_of_supply and no price_drop_share:
-- RentCast supplies neither (no closed-sale count, no price-cut share), and
-- a nullable column for a metric the vendor cannot produce reads as "missing
-- this month" rather than "unavailable from this source". Both are open
-- product decisions — see correction 3 in docs/migration/PHASE1-PLUS.md —
-- and whichever source answers them gets its own row here under its own
-- `source`, which is exactly what the composite key is for.
--
-- COUNSEL. Question #2 of the attorney batch is whether SISY's display of
-- readings derived from this data is permitted under RentCast's ToU. This
-- table is the thing that question is about. Storing is understood to be
-- permitted; that is worth confirming before Tier B, not after.

create table if not exists public.market_stats (
  zip                text not null check (zip ~ '^\d{5}$'),
  as_of_month        text not null check (as_of_month ~ '^\d{4}-\d{2}$'),
  source             text not null,
  retrieved_at       timestamptz not null,
  -- parsed, sale-side only. rentals ride along free in dataType=All and are
  -- kept in raw_json; nothing on a for-sale page may read them.
  list_median_price  numeric,
  list_average_price numeric,
  list_median_ppsf   numeric,
  active_dom         numeric,          -- active-listing DOM: skews high, stale stock sits in the pool
  total_listings     integer,
  new_listings       integer,
  history_months     integer,
  raw_json           jsonb not null,
  created_at         timestamptz not null default now(),
  primary key (zip, as_of_month, source)
);

-- The key is (zip, month, SOURCE) so a Redfin-era row and a RentCast row for
-- the same ZIP-month coexist rather than one overwriting the other. During a
-- migration the ability to hold both and compare them is the whole point;
-- v34 added `source` to zip_velocity for the same reason.

alter table public.market_stats enable row level security;
revoke all on table public.market_stats from anon, authenticated;
-- Written by the pipeline with the service key, read by the pipeline. No
-- browser path exists and none should be added without re-reading v11's note
-- on why the anon role sees no market internals.

create index if not exists market_stats_source_month_idx
  on public.market_stats (source, as_of_month);
create index if not exists market_stats_zip_idx
  on public.market_stats (zip);

comment on table public.market_stats is
  'Per-ZIP market statistics as bought or derived, one row per zip/month/source. raw_json holds the untouched vendor payload so re-parsing and backtesting never cost another request.';
comment on column public.market_stats.raw_json is
  'The complete vendor response, stored verbatim. Never drop this to save space: it is what makes every later formula revision free.';
comment on column public.market_stats.retrieved_at is
  'The real instant the data was retrieved, recorded on write. Unlike zip_velocity.retrieved_at (v34) this is never an approximation — that gap is why this column is NOT NULL.';
comment on column public.market_stats.list_median_price is
  'Median ASKING price of active listings, not a closed-sale median. Trend is comparable to the Redfin era; absolute level reads higher.';
comment on column public.market_stats.active_dom is
  'Average days on market across ACTIVE listings. Skews high versus a sold-DOM median because stale inventory stays in the pool — recalibrate thresholds, do not port them.';

-- ═════════════════════════════════════════════════════════════════════════
-- 2. market_jobs — what was bought, what it cost, what failed
-- ═════════════════════════════════════════════════════════════════════════
--
-- The durable twin of pipeline/rentcast_jobs.csv. Same columns, same status
-- values: the CSV is the runner's crash-safe checkpoint on the machine doing
-- the work, this is the record that outlives the run. A ZIP marked `done`
-- here is a ZIP nobody should pay for again.
--
-- STATUS IS A CHECK, NOT AN ENUM. v22/v23 reach for an enum when the values
-- are a short fixed list, and these are. The counter-example is more
-- relevant: Phase 0 needed to record WHY 32 marketing posts were skipped and
-- could not, because status_reason is a four-value enum with no room for the
-- reason — so it went into a .sql file and a doc instead. A migration
-- discovers states mid-flight (a vendor timeout class, a tier promoted
-- early), and a check constraint is one editable statement where an enum
-- value is permanent. `free_source_only` is here from the start precisely
-- because Tier C ZIPs need a settled state that is not an error.
--
-- tier RECORDS WHERE THE MONEY WENT. Phase 5's 60-day review promotes Tier C
-- ZIPs that earn impressions and demotes paid ZIPs that never do. That review
-- needs to know what tier each ZIP was in WHEN IT WAS BOUGHT, which nothing
-- else stores — tier_interim.csv is regenerated and will not remember.

create table if not exists public.market_jobs (
  zip          text not null check (zip ~ '^\d{5}$'),
  source       text not null,
  status       text not null check (status in
                 ('pending', 'done', 'no_data', 'error', 'free_source_only')),
  tier         text check (tier is null or tier in ('A', 'B', 'C', 'D')),
  http         integer,
  bytes        integer,
  attempts     integer not null default 0,
  note         text,
  retrieved_at timestamptz,
  updated_at   timestamptz not null default now(),
  primary key (zip, source)
);

alter table public.market_jobs enable row level security;
revoke all on table public.market_jobs from anon, authenticated;

create index if not exists market_jobs_status_idx on public.market_jobs (status);
create index if not exists market_jobs_tier_idx on public.market_jobs (tier);

comment on table public.market_jobs is
  'Per-ZIP acquisition status, one row per zip/source. The durable twin of pipeline/rentcast_jobs.csv — a ZIP marked done is a ZIP nobody should pay for again.';
comment on column public.market_jobs.status is
  'pending / done / no_data / error / free_source_only. no_data is settled, not failed: re-calling a ZIP the vendor has no data for buys the same non-answer.';
comment on column public.market_jobs.tier is
  'The cost tier this ZIP was in when it was acquired. Phase 5 promotes and demotes tiers, and tier_interim.csv is regenerated — without this, what was actually paid for is unrecoverable.';

-- ═════════════════════════════════════════════════════════════════════════
-- Not done here, deliberately
-- ═════════════════════════════════════════════════════════════════════════
-- No loader. pipeline/fetch_rentcast.py writes the disk archive and the CSV
-- ledger, which is what Tier A and the Phase 2.3 validation gate need; the
-- push into these tables is a separate, testable step and lands with the
-- code that reads them. Creating the tables first is still correct — raw_json
-- and retrieved_at are the two columns that cannot be added after the fact
-- without buying the data twice.
