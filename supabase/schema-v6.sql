-- ShouldISellYet schema v6 — run AFTER schema-v5.sql (idempotent).
--
-- Structured address. Until now `subscribers.address` held whatever single
-- line the customer typed on the subscribe page, and the ZIP was recovered
-- downstream by regexing the last 5-digit group out of it. The ZIP is the key
-- to every verdict on this site, so it can't be a parse result.
--
-- These columns are the canonical store. web/address.js is the only thing that
-- writes them from the browser (via the insert-only anon policy) and the
-- column names match its field names on purpose — see toRow()/fromRow() there.

alter table public.subscribers
  add column if not exists address_street text,
  add column if not exists address_unit   text,
  add column if not exists address_city   text,
  add column if not exists address_state  text;

-- `zip` already exists and stays the authoritative ZIP (it is checked
-- ^\d{5}$ in schema.sql). No new zip column: one ZIP, one place.

-- The old freeform `address` column is KEPT, not dropped. It holds the only
-- address we have for every row written before this migration, and dropping it
-- would delete customer data to tidy a schema. New writes leave it null; the
-- backfill below moves what can be moved safely.
comment on column public.subscribers.address is
  'DEPRECATED: freeform pre-v6 address. Read-only legacy; new writes use address_* columns.';

-- Backfill: only the unambiguous part. A legacy line like
--   "1234 Aspen Knolls Way, Silver Spring, MD 20906"
-- can have its street segment taken (everything before the first comma) with
-- reasonable confidence. City/state are NOT guessed here — a wrong city that
-- looks filled-in is worse than an empty field the customer can complete,
-- because nothing will ever prompt them to fix it.
update public.subscribers
   set address_street = trim(split_part(address, ',', 1))
 where address is not null
   and trim(address) <> ''
   and address_street is null;

create index if not exists subscribers_email_zip_idx
  on public.subscribers (email, zip);
