// ShouldISellYet — single source of truth for consumer pricing.
//
// Change a number here and every page updates: static HTML price strings are
// stamped into elements carrying data-price="<key>" on DOMContentLoaded, and
// page scripts read PRICES.* / PRICE_TEXT directly for composed copy.
// (terms.html / privacy.html / refunds.html are deliberately NOT scripted —
// legal text stays literal; update those by hand when prices change.)
//
// TODO (payment provider): Stripe Payment Links / price IDs must match these
// numbers — see LINKS in subscribe.html for exactly which links to create.

const PRICES = {
  ANNUAL: 39,      // EquityWatch, billed annually ($/yr)
  MONTHLY: 5.99,   // EquityWatch, billed monthly ($/mo)
  REPORT: 9.99,    // one-time full report
  UPGRADE: 29,     // annual price for a report buyer upgrading within 30 days
  UPGRADE_WINDOW_DAYS: 30,
};
PRICES.ANNUAL_PER_MO = PRICES.ANNUAL / 12;                        // 3.25
PRICES.SAVE_VS_MONTHLY = Math.floor(PRICES.MONTHLY * 12 - PRICES.ANNUAL); // 32 — floor, never overstate

// "$39" for whole dollars, "$5.99" otherwise
const usd = (n) => "$" + (Number.isInteger(n) ? n : n.toFixed(2));
PRICES.usd = usd;

const PRICE_TEXT = {
  "annual": usd(PRICES.ANNUAL),
  "annual-yr": usd(PRICES.ANNUAL) + "/yr",
  "annual-permo": usd(PRICES.ANNUAL_PER_MO) + "/mo, billed annually",
  "monthly": usd(PRICES.MONTHLY),
  "monthly-mo": usd(PRICES.MONTHLY) + "/mo",
  "monthly-line": "or " + usd(PRICES.MONTHLY) + "/mo billed monthly",
  "save-line": "Save $" + PRICES.SAVE_VS_MONTHLY + " vs monthly",
  "report": usd(PRICES.REPORT),
  "upgrade": usd(PRICES.UPGRADE),
};

document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll("[data-price]").forEach((el) => {
    const t = PRICE_TEXT[el.getAttribute("data-price")];
    if (t) el.textContent = t;
  });
});
