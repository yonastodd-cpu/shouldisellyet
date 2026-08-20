-- v39 — readings_for_scoring() takes an optional ZIP filter.
--
-- v38 returned all 5,000 scored ZIPs and the caller kept the ~1,000 it wanted.
-- Over the linked CLI that worked; over PostgREST the first CI run got 977 of
-- 1,000 — the function returns all 5,000 (verified) and the REST layer did not
-- deliver all of them. Rather than chase the transport's row limit, ask for
-- what is actually needed: a tranche is at most a few thousand ZIPs, the
-- response is a fraction of the size, and the caller can assert it received
-- every ZIP it asked about instead of inferring loss from a smaller number.
--
-- p_zips null keeps the v38 behaviour so calibration and rescoring, which do
-- want the whole set, are unchanged.

create or replace function public.readings_for_scoring(
  p_source text default 'rentcast',
  p_zips   text[] default null
)
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
   where s.source = p_source
     and (p_zips is null or s.zip = any(p_zips));
$$;

revoke all on function public.readings_for_scoring(text, text[]) from public, anon, authenticated;
grant execute on function public.readings_for_scoring(text, text[]) to service_role;
