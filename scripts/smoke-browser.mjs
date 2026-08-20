// Browser smoke test — the check that every other gate structurally cannot do.
//
//   node scripts/smoke-browser.mjs http://localhost:5177
//   node scripts/smoke-browser.mjs https://shouldisellyet.com
//
// WHY THIS EXISTS. On 2026-08-19 the homepage ZIP lookup threw a TypeError
// inside a setTimeout. A visitor entering a ZIP saw the spinner vanish and
// NOTHING replace it — no verdict card, no waitlist card. Every one of the
// 22,874 ZIP pages funnels into /?zip=NNNNN, so that was the whole front door.
//
// Every deploy through it was green. Unit tests passed, the page-count gate
// passed, curl returned 200 on every URL. None of them execute JavaScript, and
// the failure existed only once the page ran. A browser is the only instrument
// that can see this class of break, which is why it is worth the dependency.
//
// Exits non-zero on failure so CI can gate on it.

import { chromium } from "playwright";

const BASE = (process.argv[2] || "http://localhost:5177").replace(/\/$/, "");
// A ZIP with a standing page. Paused today, so it must render the notice.
const ZIP = process.argv[3] || "20601";

// Released-path coverage. Nothing is released in production, so these paths
// are unreachable in a normal build — which is exactly why a bug in one of
// them survived every gate. scripts/smoke-released.sh stages a release
// locally with fixture readings and passes the ZIPs here.
const argFor = (flag) => {
  const i = process.argv.indexOf(flag);
  return i > -1 ? process.argv[i + 1] : null;
};
const RELEASED = argFor("--released");   // expects a full reading
const THIN = argFor("--thin");           // released, but too little data to read

const RATINGS = /\b(HOLD|WATCH|ACT)\b/;

// DISCLOSURE IS NOT A LEAK. Every page explains the danger lines the engine
// scores against — "the year-over-year price trend (−2%), how long homes take
// to sell (+40% year over year)". Those are OUR published thresholds, identical
// on every page, and stating them is the point: a reader is told the rule
// before they are told the result. What must never appear is THIS ZIP's own
// measured value. These literals are subtracted before the scan; anything left
// that looks like a figure is the ZIP's.
const DISCLOSED = [
  "−20%",
  "−15%",
  "-15%",
  "-20%",
  "+30%",
  "+10%",
  "-2%",
  "30%",
  "20%",
  "+5%",
  "10%",
  "-5%",
  "−2%",
  "−5%",
  "15%",
  "5%",
  "2%",
];
const stripDisclosed = (s) => DISCLOSED.reduce((acc, d) => acc.split(d).join(""), s);
// A market figure as a reader would see one: a percentage, a day count, a
// months-of-supply value, a price.
const FIGURE = /[-−+]?\d[\d,]*\.?\d*\s*(%|days?\b|mo\b|months? of supply)|\$\s?\d[\d,]{2,}/;

const failures = [];
const checks = [];
function check(name, ok, detail = "") {
  checks.push({ name, ok, detail });
  if (!ok) failures.push(`${name}${detail ? " — " + detail : ""}`);
}

const browser = await chromium.launch();
const page = await browser.newPage();

const consoleErrors = [];
const pageErrors = [];
// Third-party resource failures are environmental, not defects: the analytics
// beacon 400s from a localhost origin because the function pins CORS to the
// site. Counting those would make the smoke test fail on every local run and
// train everyone to ignore it. Uncaught exceptions are captured separately by
// the pageerror handler below, and those are never noise.
const THIRD_PARTY = /supabase\.co|challenges\.cloudflare|googleapis|gstatic|zippopotam/;
page.on("console", (m) => {
  if (m.type() !== "error") return;
  const text = m.text();
  // "Failed to load resource" and CORS rejections both. The analytics beacon
  // pins CORS to the site origin, so every local run produces one.
  const where = m.location()?.url || "";
  if (/Failed to load resource|blocked by CORS|Access-Control-Allow-Origin/i.test(text) &&
      (THIRD_PARTY.test(text) || THIRD_PARTY.test(where))) return;
  // Say WHICH resource. "Failed to load resource: 404" with no URL is an
  // error message that cannot be acted on — it cost a CI round-trip to learn
  // that the answer was knowable all along.
  consoleErrors.push(where ? `${text} [${where}]` : text);
});
page.on("pageerror", (e) => pageErrors.push(String(e)));

// ————— 1. the homepage answers a ZIP at all —————
// NOT networkidle: the page runs recurring timers, so the network never goes
// idle and the wait times out on a perfectly healthy page.
await page.goto(`${BASE}/?zip=${ZIP}`, { waitUntil: "domcontentloaded", timeout: 45000 });
// Wait for an ANSWER rather than a fixed delay — either card appearing is the
// success condition, and racing a hardcoded sleep against a 1.6s animation
// floor is how a smoke test becomes flaky.
await page
  .waitForFunction(() => {
    const shown = (id) => {
      const el = document.getElementById(id);
      return el && !el.hidden && getComputedStyle(el).display !== "none";
    };
    return shown("verdict") || shown("waitcard");
  }, { timeout: 15000 })
  .catch(() => {});   // swallow: the assertion below reports it properly

const state = await page.evaluate(() => {
  const vis = (id) => {
    const el = document.getElementById(id);
    if (!el) return "missing";
    return el.hidden ? "hidden" : getComputedStyle(el).display;
  };
  const verdict = document.getElementById("verdict");
  return {
    verdict: vis("verdict"),
    waitlist: vis("waitcard"),
    crunch: vis("crunch"),
    verdictText: verdict ? verdict.innerText.replace(/\s+/g, " ").trim() : "",
    bodyText: document.body.innerText.replace(/\s+/g, " "),
  };
});

// THE assertion the crash would have failed. Either card is acceptable; what
// is not acceptable is neither — a visitor staring at nothing.
const answered = state.verdict === "block" || state.waitlist === "block";
check("zip lookup renders an answer", answered,
  `verdict=${state.verdict} waitlist=${state.waitlist} crunch=${state.crunch}`);

check("no uncaught page errors", pageErrors.length === 0, pageErrors.slice(0, 2).join(" | "));
check("no console errors", consoleErrors.length === 0, consoleErrors.slice(0, 2).join(" | "));

// ————— 2. what the answer may contain, while paused —————
if (state.verdict === "block") {
  check("paused card carries the notice",
    /being refreshed|rebuilding/i.test(state.verdictText),
    state.verdictText.slice(0, 80));
  check("paused card publishes no rating", !RATINGS.test(state.verdictText),
    (state.verdictText.match(RATINGS) || [])[0] || "");
  check("paused card publishes no figure", !FIGURE.test(stripDisclosed(state.verdictText)),
    (stripDisclosed(state.verdictText).match(FIGURE) || [])[0] || "");
}

// The homepage body as a whole. The ninth surface was prose and an alt
// attribute here, not the verdict card.
check("homepage body publishes no market figure", !FIGURE.test(stripDisclosed(state.bodyText)),
  (stripDisclosed(state.bodyText).match(FIGURE) || [])[0] || "");

const alts = await page.$$eval("img[alt]", (els) => els.map((e) => e.alt));
check("no image alt text carries a figure",
  !alts.some((a) => FIGURE.test(a)),
  alts.find((a) => FIGURE.test(a)) || "");

// ————— 3. a generated ZIP page, rendered —————
await page.goto(`${BASE}/zip/${ZIP}/`, { waitUntil: "domcontentloaded" });
const zipPage = await page.evaluate(() => ({
  body: document.body.innerText.replace(/\s+/g, " "),
  robots: (document.querySelector('meta[name="robots"]') || {}).content || "",
  title: document.title,
}));
check("paused zip page shows the notice", /refresh|rebuil/i.test(zipPage.body));
check("paused zip page publishes no figure", !FIGURE.test(stripDisclosed(zipPage.body)),
  (stripDisclosed(zipPage.body).match(FIGURE) || [])[0] || "");
check("paused zip page is noindexed", zipPage.robots.includes("noindex"), zipPage.robots);
check("paused zip page title carries no rating", !RATINGS.test(zipPage.title), zipPage.title);

// ————— 4. purged files are not reachable —————
//
// Skipped while a release is staged: a released ZIP legitimately regains its
// preview card and its record regains a reading, so these would fail on
// correct behaviour.
const stagedRelease = Boolean(RELEASED || THIN);
for (const path of stagedRelease ? [] : [
  "/data/cases/boise-2021.json",
  "/data/cases/boise-2021.png",
  "/og/2026-06/20601.png",
]) {
  const r = await page.request.get(`${BASE}${path}`);
  check(`purged file is gone: ${path}`, r.status() === 404, `HTTP ${r.status()}`);
}

// THE BULK FILE MUST NOT EXIST. Records are one file per ZIP now, so a state
// blob coming back means the switch regressed and the browser is downloading
// hundreds of readings to show one again.
const bulk = await page.request.get(`${BASE}/data/zips/MD.json`);
check("no bulk state file is served", bulk.status() === 404, `HTTP ${bulk.status()}`);

// And the per-ZIP file carries only what an unreleased ZIP should.
if (!stagedRelease) {
  const one = await page.request.get(`${BASE}/data/z/${ZIP}.json`);
  check("per-ZIP record is served", one.ok(), `HTTP ${one.status()}`);
  if (one.ok()) {
    const rec = await one.json();
    check("unreleased record carries only a state code",
      Object.keys(rec).every((k) => k === "st"), Object.keys(rec).join(","));
  }
}

// ————— 5. the released paths —————
//
// Only reachable when a release is staged. Skipped otherwise rather than
// failed: a normal run against production has nothing released and that is
// the correct state, not a defect.
if (RELEASED) {
  await page.goto(`${BASE}/zip/${RELEASED}/`, { waitUntil: "domcontentloaded" });
  const r = await page.evaluate(() => ({
    body: document.body.innerText.replace(/\s+/g, " "),
    robots: (document.querySelector('meta[name="robots"]') || {}).content || "",
    title: document.title,
    charts: document.querySelectorAll("svg").length,
  }));
  check("released page shows a rating", RATINGS.test(r.title) || RATINGS.test(r.body),
    r.title.slice(0, 60));
  check("released page shows its figures", FIGURE.test(stripDisclosed(r.body)),
    (stripDisclosed(r.body).match(FIGURE) || [])[0] || "none found");
  check("released page is NOT noindexed", !r.robots.includes("noindex"), r.robots || "(none)");
  check("released page does not show the pause notice",
    !/being refreshed|rebuilding/i.test(r.body));
}

// The twelve-month series is consumed by the HOMEPAGE preview (sparkSVG /
// renderPreview), not the ZIP page — build_pages emits no SVG at all. This
// assertion originally targeted the ZIP page and was simply wrong about where
// the chart lives; it now checks where the series is actually rendered, which
// is the surface the one-point bug would have shown up on.
if (RELEASED) {
  await page.goto(`${BASE}/?zip=${RELEASED}`, { waitUntil: "domcontentloaded", timeout: 45000 });
  await page.waitForFunction(() => {
    const el = document.getElementById("verdict");
    return el && !el.hidden && getComputedStyle(el).display !== "none";
  }, { timeout: 15000 }).catch(() => {});
  const home = await page.evaluate(() => {
    const pv = document.getElementById("preview");
    return {
      verdictText: (document.getElementById("verdict") || {}).innerText || "",
      metricsLen: (document.getElementById("v-metrics") || {}).innerHTML?.length ?? 0,
      previewHidden: pv ? pv.hidden : null,
      sparkPoints: (document.querySelectorAll("#preview polyline, #preview path").length),
    };
  });
  check("homepage shows the released reading", RATINGS.test(home.verdictText),
    home.verdictText.replace(/\s+/g, " ").slice(0, 70));
  check("homepage renders its dials", home.metricsLen > 0, `${home.metricsLen} chars`);
  check("homepage preview is shown", home.previewHidden === false, String(home.previewHidden));
  check("homepage preview draws the series", home.sparkPoints > 0, `${home.sparkPoints} shapes`);
}

if (THIN) {
  await page.goto(`${BASE}/zip/${THIN}/`, { waitUntil: "domcontentloaded" });
  const r = await page.evaluate(() => ({
    body: document.body.innerText.replace(/\s+/g, " "),
    robots: (document.querySelector('meta[name="robots"]') || {}).content || "",
    title: document.title,
  }));
  // HOLD is verdict_v2's safe default when it cannot read a market, not a
  // finding. Publishing it as one is the failure this covers.
  check("thin page does not claim a rating", !RATINGS.test(r.title), r.title.slice(0, 70));
  check("thin page says so plainly", /not enough|too few/i.test(r.body),
    r.body.slice(0, 80));
  check("thin page publishes no figure", !FIGURE.test(stripDisclosed(r.body)),
    (stripDisclosed(r.body).match(FIGURE) || [])[0] || "");
  check("thin page stays noindexed", r.robots.includes("noindex"), r.robots || "(none)");
}

await browser.close();

const width = Math.max(...checks.map((c) => c.name.length));
for (const c of checks) {
  console.log(`  ${c.ok ? "PASS" : "FAIL"}  ${c.name.padEnd(width)}${c.detail ? "  " + c.detail.slice(0, 90) : ""}`);
}
console.log(`\n${checks.length - failures.length}/${checks.length} passed against ${BASE}`);
if (failures.length) {
  console.error(`\n${failures.length} failure(s):`);
  for (const f of failures) console.error(`  - ${f}`);
  process.exit(1);
}
