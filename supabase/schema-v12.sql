-- ShouldISellYet schema v12 — run AFTER schema-v11.sql (idempotent).
--
-- Admin dashboard auth. admin.html is a static file on GitHub Pages — the
-- HTML is public and always will be, so the page is not the boundary. THIS
-- is the boundary: every read the dashboard does goes through a
-- security-definer RPC that first checks the caller's JWT email against the
-- allowlist below. The anon key alone gets 42501 on the tables, "forbidden"
-- from the RPCs, and an authenticated-but-unlisted login gets the same
-- "forbidden". Losing the admin.html URL costs nothing; losing a listed
-- email's inbox is what would matter (which is true of any magic-link auth).
--
-- ADMIN_EMAILS config = rows in this table. Add an admin:
--   insert into public.admin_emails (email) values ('person@example.com');
-- Remove one:
--   delete from public.admin_emails where email = 'person@example.com';

create table if not exists public.admin_emails (
  email text primary key,
  added_at timestamptz not null default now()
);

alter table public.admin_emails enable row level security;
revoke all on table public.admin_emails from anon, authenticated;

-- The one check every admin RPC starts with. SECURITY DEFINER so it can read
-- admin_emails past RLS; STABLE so the planner can collapse repeated calls
-- inside one statement. Case-insensitive because email casing is cosmetic.
create or replace function public.is_admin()
returns boolean
language sql stable security definer set search_path = public
as $$
  select exists (
    select 1 from public.admin_emails
    where lower(email) = lower(coalesce(auth.jwt() ->> 'email', ''))
  );
$$;

-- Functions default to EXECUTE for PUBLIC — revoke first, then grant only
-- what the dashboard needs. anon never calls these; a signed-in session is
-- the floor, the allowlist check inside is the actual gate.
revoke execute on function public.is_admin() from public, anon;
grant execute on function public.is_admin() to authenticated;

-- Smallest possible probe: "am I an admin?" admin.html calls this right
-- after sign-in to decide between the dashboard and the door. Also the
-- pattern every later admin RPC copies — guard first, work second.
create or replace function public.admin_ping()
returns jsonb
language plpgsql stable security definer set search_path = public
as $$
begin
  if not public.is_admin() then
    raise exception 'forbidden';
  end if;
  return jsonb_build_object('ok', true);
end;
$$;

revoke execute on function public.admin_ping() from public, anon;
grant execute on function public.admin_ping() to authenticated;
