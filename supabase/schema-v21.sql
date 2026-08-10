-- ShouldISellYet schema v21 — run AFTER schema-v20.sql (idempotent).
--
-- annual_upsell_shown_count: how many alert emails have carried the
-- monthly→annual upsell block for this subscriber. The block renders in AT
-- MOST the first two alerts, then never again — a recurring upsell inside a
-- trusted alert stream erodes the stream (the whole product is that these
-- emails only ever say something worth hearing). Enforced by the sender
-- (notify_changes.py) reading and incrementing this counter.
alter table public.subscribers
  add column if not exists annual_upsell_shown_count int not null default 0;
