// Absence gate over EVERY URL WE PUBLISH — derived, never hand-kept.
//
//   node scripts/crawl-gate.mjs http://localhost:5177          # local build
//   node scripts/crawl-gate.mjs https://shouldisellyet.com     # production
//   node scripts/crawl-gate.mjs <base> --sample 200            # more generated pages
//   node scripts/crawl-gate.mjs <base> --list                  # print every URL crawled
//
// WHY THIS EXISTS. Seven surfaces were found publishing withdrawn figures
// across three rounds of checking: page bodies, state indexes, share titles,
// OG image text, homepage case-study files, the sample report page, the press
// page. The last two were static marketing pages, submitted to search engines,
// and they survived every earlier pass for one reason: the test matrix
// enumerated APPLICATION TEMPLATES. A page with no template is a page with no
// row in that matrix, so /report.html and /press.html were never in scope —
// while serving a WATCH rating for a named ZIP and the national verdict mix.
//
// So scope is derived from what the site actually publishes:
//
//   1. A filesystem walk of every *.html under web/.
//   2. Every <loc> in the sitemaps.
//
// A page cannot be forgotten by this gate, because forgetting to create it
// would remove it from the site as well. That is the property the hand-kept
// list did not have.
//
// STATIC PAGES ARE CRAWLED EXHAUSTIVELY. Anything committed under web/ is
// hand-maintained — no generator writes it, so no pipeline change reaches it,
// and it is where both late misses were. There are about a dozen; crawl all of
// them, post-JS, every run. Generated pages are template-driven and covered by
// the unit suite, so they are sampled and the sample size is reported rather
// than hidden.
//
// Exits non-zero on any finding, so CI and the scheduled production run can
// both gate on it.

import { chromium } from "playwright";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { execSync } from "node:child_process";

const BASE = (process.argv[2] || "http://localhost:5177").replace(/\/$/, "");
const argOf = (f, d) => {
  const i = process.argv.indexOf(f);
  return i > -1 ? process.argv[i + 1] : d;
};
const SAMPLE = Number(argOf("--sample", "40"));
const LIST = process.argv.includes("--list");
// Client-rendered pages need a moment after DOMContentLoaded for the
// reading card to appear; the homepage lookup is the reason this is not 0.
const SETTLE = Number(argOf("--settle", "700"));
// fileURLToPath, not URL.pathname — the latter percent-encodes, and this
// repo lives under a directory with a space in its name.
const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const WEB = join(ROOT, "web");

// ————— 1. discover —————

function walkHtml(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    const s = statSync(p);
    if (s.isDirectory()) walkHtml(p, out);
    else if (name.endsWith(".html")) out.push(p);
  }
  return out;
}

function fileToUrl(p) {
  const rel = relative(WEB, p).replace(/\\/g, "/");
  return "/" + rel.replace(/index\.html$/, "").replace(/\.html$/, ".html");
}

function sitemapUrls() {
  const out = [];
  const dir = join(WEB, "sitemaps");
  let names = [];
  try { names = readdirSync(dir).filter((n) => n.endsWith(".xml")); } catch { return out; }
  for (const n of names) {
    const xml = readFileSync(join(dir, n), "utf8");
    for (const m of xml.matchAll(/<loc>([^<]+)<\/loc>/g)) {
      const u = m[1].replace(/^https?:\/\/[^/]+/, "");
      if (!u.endsWith(".xml")) out.push(u);
    }
  }
  return out;
}

// Committed under web/ == hand-maintained. The one discriminator that keeps
// itself current: adding a marketing page means committing it, which puts it
// in scope without anyone remembering to add it anywhere.
function committedPages() {
  try {
    return new Set(
      execSync("git ls-files 'web/**/*.html' 'web/*.html'", { cwd: ROOT })
        .toString().trim().split("\n").filter(Boolean)
        .map((f) => fileToUrl(join(ROOT, f))));
  } catch { return new Set(); }
}

const fsUrls = walkHtml(WEB).map(fileToUrl);
const smUrls = sitemapUrls();
const statics = committedPages();
const discovered = [...new Set([...fsUrls, ...smUrls])].sort();

const isZipPage = (u) => /^\/zip\/\d{5}\/$/.test(u);
const isShareStub = (u) => /^\/s\/\d{5}\//.test(u);
const isMetro = (u) => /^\/metro\/[^/]+\//.test(u);

// Everything static, every non-templated URL, and a sample of the rest.
const staticUrls = discovered.filter((u) => statics.has(u));
const templated = discovered.filter((u) => isZipPage(u) || isShareStub(u) || isMetro(u));
// Set membership, not Array.includes — this walks ~46,000 URLs, and the
// quadratic version simply never finished.
const templatedSet = new Set(templated);
const other = discovered.filter((u) => !statics.has(u) && !templatedSet.has(u));
const stride = Math.max(1, Math.floor(templated.length / SAMPLE));
const sampled = templated.filter((_, i) => i % stride === 0).slice(0, SAMPLE);
const toCrawl = [...new Set([...staticUrls, ...other, ...sampled])];

// ————— 2. assert —————

const FINDINGS = [];
const offsite = [];
const flag = (url, what, detail) => FINDINGS.push({ url, what, detail });

// A rating attached to a MARKET, as opposed to the vocabulary being explained.
// The legend on the press kit says "HOLD — no lines crossed"; that is
// disclosure. "15,471 ZIPs read HOLD" is the withdrawn national dataset.
const NATIONAL_TOTALS = /[\d,]{4,}\s+ZIPs?\s+read\b|Verdict mix across|[\d,]{4,}\s+scored ZIP codes/i;
const RATING_FOR_A_MARKET =
  /\b(HOLD|WATCH|ACT|STRONG)\b\s*[—-]?\s*(?:in|for)\s+\d{5}|\b\d{5}\b[^.]{0,40}\b(HOLD|WATCH|ACT)\b|(HOLD|WATCH|ACT|STRONG)\s+\d{1,3}(\.\d)?%/;
// Discontinued vendor. Ingestion stopped 2026-08-14, so no surface may credit
// it AS A CURRENT SOURCE. Naming it historically is a different act and a
// required one: the research index's pre-2026 series really is reconstructed
// from Redfin's archived tracker, and dropping that attribution to make a
// grep pass would replace a disclosure problem with a worse one.
//
// So the finding is the present-tense credit, and the historical phrasings are
// allowed BY NAME. A new way of saying it lands as a finding until someone
// decides which kind it is, which is the right default.
const DISCONTINUED = /data provided by\s+redfin|redfin[^.]{0,30}\bis our\b|source:\s*redfin/i;
// Apostrophe-agnostic: the rendered page uses a typographic apostrophe and the
// source a straight one, so a literal match silently fails on the exact string
// it was written for. Normalise before testing rather than writing every
// pattern twice.
const HISTORICAL_OK = [
  /restated from Redfin's archived tracker/i,
  /Redfin Data Center hub data/i,
  /Redfin's archived/i,
];
const flat = (s) => (s || "").replace(/[\u2018\u2019\u02BC]/g, "'");
const isHistorical = (s) => HISTORICAL_OK.some((re) => re.test(flat(s)));

function checkDoc(url, { html, text, title, metas, robots, status }) {
  const head = [title, ...metas].join(" \n ");
  const all = `${head}\n${text}`;

  const credit = all.match(DISCONTINUED);
  if (credit && !isHistorical(all.slice(Math.max(0, all.indexOf(credit[0]) - 120),
                                        all.indexOf(credit[0]) + 120))) {
    flag(url, "credits a discontinued vendor as a current source", credit[0]);
  }
  // Any other mention still has to be one of the sanctioned historical forms.
  const anyMention = all.match(/.{0,50}redfin.{0,50}/i);
  if (anyMention && !credit && !isHistorical(anyMention[0])) {
    flag(url, "names a discontinued vendor in an unrecognised way", anyMention[0].trim());
  }
  const nat = all.match(NATIONAL_TOTALS);
  if (nat) flag(url, "publishes a national total from the withdrawn dataset", nat[0]);

  // Only pages ABOUT ONE MARKET can be said to withhold "their" reading. A
  // metro page or a state hub legitimately mixes released ZIPs with paused
  // ones, so it contains the notice AND ratings at the same time — treating
  // that as a contradiction flagged three healthy pages on the first run.
  const isSingleMarket = /^\/zip\/\d{5}\/$/.test(url) || /^\/s\/\d{5}\//.test(url);
  const withholds = isSingleMarket &&
    /being refreshed|reading is being rebuilt/i.test(text);
  if (withholds) {
    const m = all.match(RATING_FOR_A_MARKET);
    if (m) flag(url, "states a rating while withholding its reading", m[0]);
    if (!/noindex/.test(robots)) {
      flag(url, "withholds its reading but is offered for indexing", robots || "(none)");
    }
  }

  // …and a page that shows a reading must not be hidden from search.
  const showsReading = !withholds && /^\/zip\/\d{5}\/$/.test(url) &&
    /\b(HOLD|WATCH|ACT)\b/.test(text);
  if (showsReading && /noindex/.test(robots)) {
    flag(url, "shows a reading but is noindexed", robots);
  }

  if (status >= 400) flag(url, `HTTP ${status}`, "");
}

// ————— 3. crawl —————

const browser = await chromium.launch();
const page = await browser.newPage();
let crawled = 0;

for (const url of toCrawl) {
  let status = 0;
  try {
    // domcontentloaded plus a settle, not networkidle: several pages keep a
    // connection open (analytics, font loading, the reading fetch), so
    // networkidle times out on pages that are perfectly fine — and a gate that
    // cries wolf on 69 healthy URLs is a gate people learn to ignore.
    const resp = await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded", timeout: 30000 });
    status = resp ? resp.status() : 0;
    await page.waitForTimeout(SETTLE);

    // A client-side redirect can leave the origin under test. The /go/ stubs
    // redirect to absolute production URLs, so crawling a local build followed
    // them to the live site and reported the live site's state as the local
    // build's — a false pass or a false fail depending on which was stale.
    // Assert on what we are actually looking at.
    const landed = page.url();
    if (!landed.startsWith(BASE)) {
      offsite.push({ url, landed });
      continue;
    }
  } catch (e) {
    flag(url, "did not load", String(e).slice(0, 80));
    continue;
  }
  const doc = await page.evaluate(() => ({
    html: document.documentElement.outerHTML.length,
    text: document.body ? document.body.innerText.replace(/\s+/g, " ") : "",
    title: document.title || "",
    metas: [...document.querySelectorAll("meta[name], meta[property]")]
      .map((m) => `${m.getAttribute("name") || m.getAttribute("property")}=${m.content}`),
    robots: (document.querySelector('meta[name="robots"]') || {}).content || "",
  }));
  checkDoc(url, { ...doc, status });
  crawled++;
}
await browser.close();

// ————— 4. report —————

console.log(`\ncrawl gate — ${BASE}`);
console.log(`  discovered      ${discovered.length.toLocaleString()} published URLs`);
console.log(`    static (all)  ${staticUrls.length}`);
console.log(`    other (all)   ${other.length}`);
console.log(`    templated     ${templated.length.toLocaleString()}  → sampled ${sampled.length}`);
console.log(`  crawled         ${crawled.toLocaleString()}`);
if (offsite.length) {
  console.log(`  left the origin ${offsite.length} (client-side redirect to another host)`);
  for (const o of offsite.slice(0, 5)) console.log(`      ${o.url} → ${o.landed.slice(0, 60)}`);
}

// The misses that motivated this gate. If the crawler cannot reach them the
// run proves nothing, so this is an assertion rather than a note.
const MUST_REACH = ["/report.html", "/press.html", "/", "/methodology.html", "/terms.html"];
const missing = MUST_REACH.filter((u) => !toCrawl.includes(u));
if (missing.length) {
  console.error(`\nFATAL: the crawl set is missing ${missing.join(", ")} — ` +
    "these are the pages this gate exists for. A clean run without them is meaningless.");
  process.exit(2);
}
console.log(`  reached         ${MUST_REACH.join(", ")}`);

if (LIST) {
  console.log("\n  URLs crawled:");
  for (const u of toCrawl) console.log(`    ${u}`);
}

if (FINDINGS.length) {
  console.error(`\n${FINDINGS.length} finding(s):`);
  for (const f of FINDINGS) console.error(`  ${f.url}\n    ${f.what} — ${f.detail}`);
  process.exit(1);
}
console.log("\nclean\n");
