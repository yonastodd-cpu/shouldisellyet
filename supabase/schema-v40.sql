-- v40 — research state moves out of the public repository.
--
-- WHY. pipeline/research/levels-{month}.json and streaks.json are pipeline
-- state: research.load_levels(prev) reads the prior month to count how many
-- ZIPs crossed into WATCH or ACT. They were also COMMITTED, and this repository
-- is public, so they published ~25,000 ZIP-to-rating pairs per month — about
-- 20,000 of them for markets whose own pages decline to state a rating. The
-- release page says "We do not publish the list"; these files did.
--
-- They cannot simply be deleted: the monthly build needs the prior month, and
-- LEGAL_HOLD.md forbids destroying Redfin-derived material. So the state moves
-- here, where it is reachable by the build and by nobody else.
--
-- SHAPE. One row per artifact rather than one row per ZIP. 25,372 rows a month
-- would be 300k rows a year for data that is always read whole, and PostgREST
-- has already returned a large result SHORT once in this project (977 of 1,000
-- readings, schema-v38's note). A single jsonb payload of ~390 KB moves in one
-- request and cannot half-arrive.
--
-- ACCESS. Service role only. There is deliberately no anon or authenticated
-- policy: the entire point of the move is that this data stops being publicly
-- readable, and a table that anyone can select is the same exposure with extra
-- steps. RLS is enabled with no permissive policy, so PostgREST refuses every
-- request that is not made with the service key.

create table if not exists public.research_state (
  key         text        primary key,   -- 'levels-2026-07' | 'streaks'
  payload     jsonb       not null,
  rows        integer     not null,      -- entry count, so a truncated write is visible
  updated_at  timestamptz not null default now()
);

comment on table public.research_state is
  'Monthly research pipeline state (per-ZIP levels, streak counts). Moved out of '
  'the public repo 2026-08-23. Service role only — see schema-v40.sql.';

comment on column public.research_state.rows is
  'Number of entries in payload. Stored alongside so a short write is detectable '
  'without parsing the blob — a silently truncated levels file would understate '
  'the monthly flip count and nothing else would notice.';

alter table public.research_state enable row level security;

-- No policy is created on purpose. RLS with no permissive policy denies every
-- request except the service role, which bypasses RLS. If a future change adds
-- a policy here, it re-opens exactly the hole this migration closed.

revoke all on public.research_state from anon, authenticated;
