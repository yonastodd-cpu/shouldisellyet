// ShouldISellYet — single source of truth for consumer pricing.
//
// Change a number here and every page updates: static HTML price strings are
// stamped into elements carrying data-price="<key>" on DOMContentLoaded, and
// page scripts read PRICES.* / PRICE_TEXT directly for composed copy.
//
// terms.html / refunds.html are deliberately NOT scripted. Legal text must be
// correct with JavaScript off and in any archived copy, so those prices stay
// literal — but they can't be allowed to drift, so pipeline/test_prices.py
// parses this file and fails the build if a legal page disagrees with it.
// Update those two by hand when a price changes; the test tells you if you
// missed one.
//
// TODO (payment provider): Stripe Payment Links / price IDs must match these
// numbers — see LINKS in subscribe.html for exactly which links to create.

// Plan display name — the ONE place the brand string lives for scripted
// pages. Stamped into [data-plan-name] elements on DOMContentLoaded, exactly
// like prices into [data-price].
// TODO: rename pending trademark screen — swap this constant only. New copy
// must not hardcode the name: say "monitoring" or "alerts on your numbers"
// generically, and use [data-plan-name] where the brand must appear.
const PLAN_NAME = "MyMarketCheckup";

const PRICES = {
  ANNUAL: 29,      // MyMarketCheckup, billed annually ($/yr) — the highlighted default
  MONTHLY: 3.99,   // MyMarketCheckup, billed monthly ($/mo)
  REPORT: 5.99,    // one-time full report
  UPGRADE: 23,     // annual price for a report buyer upgrading within 30 days
  UPGRADE_WINDOW_DAYS: 30,
};
// Which price LEADS every pricing surface. "monthly_led" | "annual_led".
// Flip here and every surface follows: the homepage featured card, the
// unlock bar, the alerts-strip CTA, and the subscribe page's default billing
// selection. purchase_click events carry the live mode (price_mode, added by
// track.js) so the admin funnel can compare modes if this is ever flipped.
// ONE surface JS cannot reach: subscribe.html's static meta description
// cites both prices in lead order — flipping this flag needs that one
// hand-edit, noted there.
const PRICE_DISPLAY_MODE = "monthly_led";
window.PRICE_DISPLAY_MODE = PRICE_DISPLAY_MODE;

PRICES.ANNUAL_PER_MO = PRICES.ANNUAL / 12;                        // 2.4166… → "$2.42"
// 1 − 29/(3.99×12) = 39.4% → "39%". Computed, so a price change can't strand it.
PRICES.SAVE_PCT = Math.round((1 - PRICES.ANNUAL / (PRICES.MONTHLY * 12)) * 100);
// Exact to the cent: $3.99 x 12 − $29 = $18.88. Rounded, not floored — floor()
// was here to avoid overstating a fractional saving, but at these numbers the
// fraction IS most of the appeal and dropping it understates by $0.88.
PRICES.SAVE_VS_MONTHLY = Math.round((PRICES.MONTHLY * 12 - PRICES.ANNUAL) * 100) / 100;

// "$29" for whole dollars, "$5.99" otherwise
const usd = (n) => "$" + (Number.isInteger(n) ? n : n.toFixed(2));
PRICES.usd = usd;

const PRICE_TEXT = {
  "annual": usd(PRICES.ANNUAL),
  "annual-yr": usd(PRICES.ANNUAL) + "/yr",
  "annual-permo": usd(PRICES.ANNUAL_PER_MO) + "/mo, billed annually",
  "monthly": usd(PRICES.MONTHLY),
  "monthly-mo": usd(PRICES.MONTHLY) + "/mo",
  // Annual leads every surface, so monthly is the alternate line everywhere.
  // "annual-alt" is its mirror, kept for any surface that ever leads monthly.
  "monthly-line": "or " + usd(PRICES.MONTHLY) + "/mo billed monthly",
  "annual-alt": "or " + usd(PRICES.ANNUAL) + "/yr — save " + usd(PRICES.SAVE_VS_MONTHLY),
  "save-line": "Save " + usd(PRICES.SAVE_VS_MONTHLY) + " vs monthly",
  "report": usd(PRICES.REPORT),
  "report-once": usd(PRICES.REPORT) + " once",
  "upgrade": usd(PRICES.UPGRADE),
};

// Mode-aware tokens — the ONLY way a surface should render the lead price.
{
  const monthlyLed = PRICE_DISPLAY_MODE === "monthly_led";
  PRICE_TEXT["mode-lead"] = monthlyLed ? usd(PRICES.MONTHLY) : usd(PRICES.ANNUAL);
  PRICE_TEXT["mode-lead-unit"] = monthlyLed ? "/mo" : "/yr";
  // Exactly one quiet alternative under the big number — nothing else.
  PRICE_TEXT["mode-alt"] = monthlyLed
    ? "or " + usd(PRICES.ANNUAL) + "/yr — save " + PRICES.SAVE_PCT + "%"
    : "or " + usd(PRICES.MONTHLY) + "/mo billed monthly";
  PRICE_TEXT["mode-cta"] = PRICE_TEXT["mode-lead"] + PRICE_TEXT["mode-lead-unit"];
}

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-price]").forEach((el) => {
    const t = PRICE_TEXT[el.getAttribute("data-price")];
    if (t) el.textContent = t;
  });
  document.querySelectorAll("[data-plan-name]").forEach((el) => {
    el.textContent = PLAN_NAME;
  });
});
