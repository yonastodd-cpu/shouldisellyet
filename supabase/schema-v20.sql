-- ShouldISellYet schema v20 — run AFTER schema-v19.sql (idempotent).
--
-- price_mode on events: which price led the page when a purchase CTA was
-- clicked (PRICE_DISPLAY_MODE in web/prices.js). Lets the funnel compare
-- monthly_led vs annual_led if the flag is ever flipped. Nullable — only
-- purchase_click events carry it, and only from pages that load prices.js.
-- No identifier, no content: a display-mode label, same posture as plan.
alter table public.events
  add column if not exists price_mode text
  check (price_mode is null or price_mode in ('monthly_led', 'annual_led'));
