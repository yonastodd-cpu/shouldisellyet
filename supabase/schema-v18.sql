-- ShouldISellYet schema v18 — run AFTER schema-v17.sql (idempotent).
--
-- Form-hardening T2: the rate-limit counter table and its atomic check.
--
-- PRIVACY SHAPE. Keys are opaque hashes computed in the edge functions:
-- sha256(salt + UTC-date + ip) — the salt is secret and the date component
-- rotates the whole keyspace daily, so a key can never be joined back to an
-- address or across days. RAW IPs NEVER REACH THIS TABLE, consistent with the
-- analytics design (events stores no identifier either). Email-keyed limits
-- hash the normalized address the same way. Rows expire operationally: the
-- weekly events_maintenance job deletes anything older than 48h, and the
-- window logic below never reads a row older than its own window anyway.

create table if not exists public.rate_limits (
  key          text primary key,
  window_start timestamptz not null,
  count        int not null default 1
);

alter table public.rate_limits enable row level security;
revoke all on table public.rate_limits from anon, authenticated;

-- One atomic call per request: insert-or-bump, reset when the window lapsed,
-- and report whether the caller is still under the cap. SECURITY DEFINER so
-- only the function owner touches the table; execute is service-role only —
-- the anon key can neither read counts nor burn windows.
create or replace function public.rate_limit_hit(p_key text, p_window_seconds int, p_max int)
returns boolean
language plpgsql security definer set search_path = public
as $$
declare c int;
begin
  insert into public.rate_limits as rl (key, window_start, count)
  values (p_key, now(), 1)
  on conflict (key) do update set
    count = case when rl.window_start < now() - make_interval(secs => p_window_seconds)
                 then 1 else rl.count + 1 end,
    window_start = case when rl.window_start < now() - make_interval(secs => p_window_seconds)
                        then now() else rl.window_start end;
  select count into c from public.rate_limits where key = p_key;
  return c <= p_max;
end;
$$;

revoke execute on function public.rate_limit_hit(text, int, int) from public, anon, authenticated;
