-- ShouldISellYet schema v14 — run AFTER schema-v13.sql (idempotent).
--
-- Customer list + map RPCs. Same rules as v13: SECURITY DEFINER, is_admin()
-- guard first, EXECUTE revoked from anon/public.
--
-- One field is deliberately never returned: access_token. It is the report
-- credential — the thing a customer's private link IS — and the dashboard
-- has no operation that needs it. A compromised admin session should not be
-- able to harvest every customer's report link; the rare legitimate resend
-- goes through the Supabase dashboard with service-role ceremony.

-- ————— Customer list: search, filters, pagination —————
create or replace function public.admin_customers(
  q text default '', plan_f text default '', status_f text default '',
  lim int default 50, off int default 0
)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  out jsonb;
  total int;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  -- One filtered set feeds both the count and the page, so they can't
  -- disagree. Search matches email substring or exact ZIP.
  with filtered as (
    select *
      from public.subscribers
     where (q = '' or email ilike '%' || q || '%' or zip = q)
       and (plan_f = '' or plan = plan_f)
       and (status_f = '' or status = status_f)
  )
  select (select count(*)::int from filtered),
         coalesce((select jsonb_agg(jsonb_build_object(
             'id', id,
             'email', email,
             'plan', plan,
             'billing_interval', billing_interval,
             'status', status,
             'zip', zip,
             'city', address_city,
             'state', address_state,
             'created_at', created_at,
             'purchased_at', purchased_at,
             -- watches is a jsonb ARRAY in production rows (checked, not
             -- assumed — jsonb_object_keys threw on the real data). Count
             -- whatever shape is there rather than betting on one.
             'watches', case jsonb_typeof(watches)
                          when 'array'  then jsonb_array_length(watches)
                          when 'object' then (select count(*)::int from jsonb_object_keys(watches))
                          else 0
                        end,
             'marketing_opt_out', marketing_opt_out
           ) order by coalesce(purchased_at, created_at) desc)
           from (select * from filtered
                  order by coalesce(purchased_at, created_at) desc
                  limit greatest(1, least(lim, 10000)) offset greatest(0, off)) page),
           '[]'::jsonb)
    into total, out;

  return jsonb_build_object('total', total, 'rows', out);
end;
$$;

revoke execute on function public.admin_customers(text, text, text, int, int) from public, anon;
grant execute on function public.admin_customers(text, text, text, int, int) to authenticated;

-- ————— Row detail for the drawer —————
-- subscribers.id is a UUID (checked against the live table, not assumed — a
-- bigint signature here failed on real data). The bigint variant is dropped
-- so PostgREST never has an ambiguous overload to resolve.
drop function if exists public.admin_customer_detail(bigint);

create or replace function public.admin_customer_detail(cid uuid)
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  select to_jsonb(s) - 'access_token'
    into out
    from public.subscribers s
   where s.id = cid;
  return coalesce(out, '{}'::jsonb);
end;
$$;

revoke execute on function public.admin_customer_detail(uuid) from public, anon;
grant execute on function public.admin_customer_detail(uuid) to authenticated;

-- ————— Map aggregates: counts per ZIP, never identities —————
-- The map layer gets numbers and ZIPs only. Even though the admin could open
-- the customer list beside it, the map payload itself carries no emails or
-- addresses — a screenshot of the map is safe by construction, and ZIP
-- centroids (not street addresses) are the only geography that exists
-- client-side.
create or replace function public.admin_map_data()
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare
  sponsored jsonb := '[]'::jsonb;
  out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  -- zip_claims ships in v15 (agent program paused); correct either way.
  if to_regclass('public.zip_claims') is not null then
    execute $q$
      select coalesce(jsonb_agg(jsonb_build_object('zip', zip, 'n', n)), '[]'::jsonb)
        from (select zip, count(*)::int as n from public.zip_claims
               where status = 'active' group by zip) t
    $q$ into sponsored;
  end if;

  select jsonb_build_object(
    'customers', coalesce((
      select jsonb_agg(jsonb_build_object('zip', zip, 'n', n))
        from (select zip, count(*)::int as n
                from public.subscribers
               where zip is not null and zip ~ '^\d{5}$' and zip <> '00000'
               group by zip) t), '[]'::jsonb),
    'requests', coalesce((
      select jsonb_agg(jsonb_build_object('zip', zip, 'n', n))
        from (select zip, count(*)::int as n
                from public.match_requests
               where zip is not null and zip ~ '^\d{5}$'
               group by zip) t), '[]'::jsonb),
    'sponsored', sponsored
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_map_data() from public, anon;
grant execute on function public.admin_map_data() to authenticated;
