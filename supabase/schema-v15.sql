-- ShouldISellYet schema v15 — run AFTER schema-v14.sql (idempotent).
--
-- Ops queues: request status workflow, dormant agent tables, health probe.
--
-- ON THE AGENT TABLES. The agent/sponsorship program was paused 2026-08-05
-- and the referring-agent flow was switched off 2026-08-07 pending a signed
-- agreement. These tables are built anyway — empty, RLS-denied, with NO
-- public surface writing to them — because the dashboard brief calls for the
-- Agents tab and the alternative is rebuilding schema under time pressure
-- the week an agent signs. Dormant structure is cheap; nothing about it
-- re-opens signup. If counsel's referral-entity design (a pending TODO)
-- reshapes the model, ALTER these then — they hold zero rows today.

-- ————— Request status workflow —————
alter table public.match_requests
  add column if not exists status text not null default 'new'
    check (status in ('new','sent_to_agent','recruiting_broker',
                      'contacted','closed_won','closed_lost')),
  add column if not exists status_updated_at timestamptz;

-- ————— Dormant agent tables —————
create table if not exists public.agents (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  email text not null,
  phone text,
  brokerage text,
  license_no text,
  license_state text,
  verified boolean not null default false,   -- the manual activation switch
  stripe_customer_id text,
  stripe_subscription_id text,
  stripe_status text,                        -- mirrored by webhook when live
  -- The v1.0 document this string named was web/partners/agreement.html. It was
  -- drafted 2026-08-06, noindexed, never sitemapped, never submitted to
  -- IndexNow, linked from nowhere, NEVER OFFERED and NEVER ACCEPTED — zero agent
  -- rows, zero non-null agreement_version values and zero zip_claims on the day
  -- it was retired — and deleted 2026-08-08. Git is the archive; find every
  -- revision with `git log --all -- web/partners/agreement.html` (five commits;
  -- the four after the draft are favicon/manifest/font only, terms unchanged).
  -- Do NOT repoint this at a URL. There is no published agreement, and a URL in
  -- a schema comment is how a retired offer quietly starts looking live again.
  -- A restart publishes a NEW version; it does not revive "1.0".
  agreement_version text,                    -- see note above
  agreement_accepted_at timestamptz,
  created_at timestamptz not null default now()
);
alter table public.agents enable row level security;
revoke all on table public.agents from anon, authenticated;

create table if not exists public.zip_claims (
  id uuid primary key default gen_random_uuid(),
  agent_id uuid not null references public.agents(id) on delete cascade,
  zip text not null check (zip ~ '^\d{5}$'),
  status text not null default 'active' check (status in ('active','paused','released')),
  created_at timestamptz not null default now()
);
alter table public.zip_claims enable row level security;
revoke all on table public.zip_claims from anon, authenticated;
-- One live claim per ZIP — "exclusive advertising placement" is the product.
create unique index if not exists zip_claims_active_idx
  on public.zip_claims (zip) where status = 'active';

-- ————— Requests queue —————
create or replace function public.admin_requests()
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  select coalesce(jsonb_agg(jsonb_build_object(
           'id', id, 'name', name, 'email', email, 'phone', phone,
           'zip', zip, 'address', address, 'timeline', timeline, 'note', note,
           'verdict', verdict, 'source', source, 'status', status,
           'status_updated_at', status_updated_at,
           'consent_text', consent_text, 'created_at', created_at,
           'disclosure_version', disclosure_version,
           'disclosure_shown_at', disclosure_shown_at
         ) order by created_at desc), '[]'::jsonb)
    into out
    from public.match_requests;
  return out;
end;
$$;

revoke execute on function public.admin_requests() from public, anon;
grant execute on function public.admin_requests() to authenticated;

create or replace function public.admin_set_request_status(rid uuid, new_status text)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare n int;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  if new_status not in ('new','sent_to_agent','recruiting_broker',
                        'contacted','closed_won','closed_lost') then
    raise exception 'bad status';
  end if;

  update public.match_requests
     set status = new_status, status_updated_at = now()
   where id = rid;
  get diagnostics n = row_count;
  return jsonb_build_object('ok', n = 1);
end;
$$;

revoke execute on function public.admin_set_request_status(uuid, text) from public, anon;
grant execute on function public.admin_set_request_status(uuid, text) to authenticated;

-- ————— Agents queue —————
create or replace function public.admin_agents()
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  select coalesce(jsonb_agg(jsonb_build_object(
           'id', a.id, 'name', a.name, 'email', a.email, 'phone', a.phone,
           'brokerage', a.brokerage, 'license_no', a.license_no,
           'license_state', a.license_state, 'verified', a.verified,
           'stripe_status', a.stripe_status,
           'agreement_version', a.agreement_version,
           'agreement_accepted_at', a.agreement_accepted_at,
           'created_at', a.created_at,
           'claims', coalesce((select jsonb_agg(jsonb_build_object(
                       'zip', c.zip, 'status', c.status) order by c.zip)
                       from public.zip_claims c where c.agent_id = a.id), '[]'::jsonb)
         ) order by a.created_at desc), '[]'::jsonb)
    into out
    from public.agents a;
  return out;
end;
$$;

revoke execute on function public.admin_agents() from public, anon;
grant execute on function public.admin_agents() to authenticated;

create or replace function public.admin_set_agent_verified(aid uuid, v boolean)
returns jsonb
language plpgsql security definer set search_path = public
as $$
declare n int;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;
  update public.agents set verified = v where id = aid;
  get diagnostics n = row_count;
  return jsonb_build_object('ok', n = 1);
end;
$$;

revoke execute on function public.admin_set_agent_verified(uuid, boolean) from public, anon;
grant execute on function public.admin_set_agent_verified(uuid, boolean) to authenticated;

-- ————— DB-side health: is the event pipeline alive? —————
-- Static-file freshness (Redfin period, PMMS as-of, FHFA vintage, publish
-- date) comes from /data/meta.json client-side — the deploy that publishes
-- data IS the record of the last successful refresh. This covers the one
-- thing meta.json cannot: whether events are still arriving.
create or replace function public.admin_events_health()
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
declare out jsonb;
begin
  if not public.is_admin() then raise exception 'forbidden'; end if;

  select jsonb_build_object(
    'last_event_at', (select max(ts) from public.events),
    'events_24h', (select count(*)::int from public.events
                    where ts >= now() - interval '24 hours'),
    'events_total', (select count(*)::int from public.events),
    'oldest_event_at', (select min(ts) from public.events)
  ) into out;
  return out;
end;
$$;

revoke execute on function public.admin_events_health() from public, anon;
grant execute on function public.admin_events_health() to authenticated;
