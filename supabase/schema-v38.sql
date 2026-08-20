-- v38 — readings_for_scoring(): the provisioning query, callable with the
-- service key.
--
-- WHY THIS EXISTS. provision_readings scores from market_stats and needs the
-- twelve-month history that lives inside raw_json. It got there by shelling out
-- to `supabase db query --linked`, which needs a linked project — fine on an
-- operator's machine, absent in CI. On 2026-08-20 the tranche-1 deploy failed
-- exactly there: "Cannot find project ref", every record fell back to the
-- notice, and the release did not land.
--
-- WHY NOT JUST SELECT OVER PostgREST. raw_json is the republication boundary:
-- it holds the vendor payload verbatim and must never leave the database. The
-- transform below unpacks only the five fields a reading needs, per month, and
-- returns nothing else — so the boundary stays server-side and the caller
-- cannot ask for the rest.
--
-- SECURITY DEFINER because market_stats is RLS-protected and revoked from
-- anon/authenticated. Execute is granted to service_role alone: there is no
-- browser path to this and none should be added.

create or replace function public.readings_for_scoring(p_source text default 'rentcast')
returns table (
  zip                text,
  as_of_month        text,
  list_median_price  numeric,
  active_dom         numeric,
  total_listings     numeric,
  list_median_ppsf   numeric,
  new_listings       numeric,
  history            jsonb
)
language sql
stable
security definer
set search_path = public, pg_temp
as $$
  select s.zip, s.as_of_month, s.list_median_price, s.active_dom,
         s.total_listings, s.list_median_ppsf, s.new_listings,
         (select jsonb_object_agg(t.k, jsonb_build_object(
                   'medianPrice',              t.v->'medianPrice',
                   'averageDaysOnMarket',      t.v->'averageDaysOnMarket',
                   'totalListings',            t.v->'totalListings',
                   'medianPricePerSquareFoot', t.v->'medianPricePerSquareFoot',
                   'newListings',              t.v->'newListings'))
            from jsonb_each(s.raw_json->'saleData'->'history') as t(k, v)) as history
    from public.market_stats s
   where s.source = p_source;
$$;

revoke all on function public.readings_for_scoring(text) from public, anon, authenticated;
grant execute on function public.readings_for_scoring(text) to service_role;
