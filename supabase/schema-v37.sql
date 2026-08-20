-- ShouldISellYet schema v37 — run AFTER schema-v36.sql (idempotent).
--
-- ═══ Monthly history, as rows ═══
--
-- market_stats holds ONE row per zip/month/source — the current reading's
-- inputs. The twelve months behind it arrive in the same vendor response and
-- live inside raw_json, which is exactly where they cannot be used.
--
-- WHY NOT JUST READ raw_json. The market-reading function is the republication
-- boundary: every field it can return is named explicitly, there is no
-- `select *`, and a test pins the whole allowed set. Reaching into raw_json to
-- pull a series would put the untouched vendor payload back inside the one
-- place built to keep it out — and "only a slice of it" is how that boundary
-- stops meaning anything. So the series is normalised ONCE at load time, into
-- named columns, and the function selects columns like everything else.
--
-- FOUND BY TESTING THE RELEASED PATH. The endpoint's contract promises up to
-- twelve price points; a released ZIP returned exactly one, because one row is
-- all market_stats has. The sparkline would have been a single dot on tranche
-- day.

create table if not exists public.market_history (
  zip               text not null check (zip ~ '^\d{5}$'),
  source            text not null,
  as_of_month       text not null check (as_of_month ~ '^\d{4}-\d{2}$'),
  median_list_price numeric,
  active_dom        numeric,
  total_listings    integer,
  loaded_at         timestamptz not null default now(),
  primary key (zip, source, as_of_month)
);

alter table public.market_history enable row level security;
revoke all on table public.market_history from anon, authenticated;

create index if not exists market_history_zip_idx on public.market_history (zip, as_of_month);

comment on table public.market_history is
  'Monthly series normalised out of market_stats.raw_json at load time, so the reading endpoint can serve a sparkline without ever reading the raw vendor payload.';
comment on column public.market_history.median_list_price is
  'Median ASKING price for that month, not a closed-sale median — same caveat as market_stats.list_median_price.';
