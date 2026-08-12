-- ShouldISellYet schema v30 — run AFTER schema-v29.sql (idempotent).
--
-- ————— Backfill post_type on rows that predate it —————
--
-- v28 added post_type; the nine rows already in the queue were generated before
-- it existed and read as "unclassified" in the mix meter, which would have made
-- the operator's first look at the meter a picture of a broken feature rather
-- than of the month's balance.
--
-- The dedupe_key stem IS the rule that produced the row — the generator builds
-- it as mq-{period}-{rule}-{subject} — so this assigns exactly what the
-- generator would assign today. It is derivation, not guesswork.
--
-- 'ever-' is deliberately left unclassified: the track-record post predates the
-- taxonomy and has no type in it. Naming it explicitly here so the gap stays
-- visible rather than being papered over with a near-enough label.
update public.marketing_tasks set post_type = case
    when dedupe_key like 'mq-%-contrarian-%' then 'contrarian'
    when dedupe_key like 'mq-%-flip-%'       then 'metro_mover'
    when dedupe_key like 'mq-%-geo-%'        then 'zip_spotlight'
    when dedupe_key like 'mq-%-record-%'     then 'national_pulse'
    when dedupe_key like 'mq-%-supply-%'     then 'metro_mover'
    when dedupe_key like 'mq-%-price-%'      then 'metro_mover'
    when dedupe_key like 'mq-%-dom-%'        then 'metro_mover'
    when dedupe_key like 'mq-%-season-%'     then 'explainer'
  end
where post_type is null
  and dedupe_key ~ '^mq-.*-(contrarian|flip|geo|record|supply|price|dom|season)-';
