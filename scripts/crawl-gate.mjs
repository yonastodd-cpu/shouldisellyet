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
// WHAT IT ASSERTS. Two families, both on the RENDERED document — innerText
// plus <title> plus every meta content — because that is the only place the
// template, the copy map and the record meet. A source grep sees one of the
// three and has to guess the other two.
//
//   The withdrawn dataset (original). A vendor credited as a current source, a
//   national total from the paused figures, a page stating a rating while
//   withholding its reading, and the indexing contradictions either way round.
//
//   The copy sweep of 2026-08-22 (§the copy sweep, below). Seven wordings came
//   off the site in one pass — "verdict", four ways of calling a licensed feed
//   public, the vendor names, the "time to sell" dial label, a frozen date in a
//   vintage slot, "reported sales" on an engine that cannot see a sale, and a
//   fourth rating word outside HOLD / WATCH / ACT — plus one cross-page
//   assertion: the ZIP coverage counts on the homepage, /zip/ and /press.html
//   must all equal the build's own inputs (§1b), not merely equal each other.
//   Five of the seven were emitted by a generator, which is why they survived
//   review: seeing them meant reading the template, the copy map and a record
//   together.
//
// EVERY ASSERTION HERE HAS BEEN MUTATION-TESTED — the violation reintroduced
// on a clean corpus, the gate required to fail with the right finding on the
// right URL, then restored and required to go green again. An assertion that
// cannot fail is worse than no assertion, because it is a green tick over an
// unchecked claim, and this project has already shipped exactly that. If you
// add a check, break it on purpose before you trust it.
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
// Two more surface kinds, both about WHERE A THING MAY BE SAID rather than
// about crawl scope. /methodology.html is the one page that names the data
// vendor and tells the migration's history; /research/ carries the pre-2026
// series that really is restated from an archived tracker. Neither widens the
// crawl set — they narrow an allowance to the surface that earned it.
const METHODOLOGY = "/methodology.html";
const isResearch = (u) => u.startsWith("/research/");
// The three surfaces that state how much of the country is live. Named, not
// derived: the assertion is that these specific pages agree with the build,
// and a page dropping its coverage sentence is itself a finding.
// /methodology.html hardcodes 5,000 / 22,874 the same way the other three do,
// so it drifts the moment a tranche releases. Added 2026-08-22 after an audit
// found it outside this list.
const COVERAGE_PAGES = ["/", "/zip/", "/press.html", "/methodology.html"];

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

// ————— 1b. the build's own numbers —————
//
// Derived from the same committed files the build derives them from, for the
// same reason the URL set is derived from the sitemap: a number the gate types
// is a fourth place to be wrong.
//
//   pages    rows in pipeline/data/page_manifest.csv with page=1 — the URL
//            contract, one row per ZIP that gets a standing page.
//   released ZIPs in a tranche with a released_utc (pipeline/tranches.json),
//            intersected with the manifest. This is data_pause.released_zips()
//            in JavaScript, and it is deliberately the RELEASE CONTRACT rather
//            than the render: build_pages additionally requires each released
//            ZIP's record to carry the v2 basis, so a build can render fewer.
//            When it does, that gap is data_pause.wrongly_promoted() — a
//            release that did not happen — and the right response is a finding,
//            not quietly accepting the smaller number as the truth.
//   words    every rating word in pipeline/data/verdict_copy.json. That file is
//            the single copy map: build_pages imports it and overwrites
//            KINDS[*].tag from it, build_metro reads it, and web/verdict-copy.js
//            is generated from it for the homepage. One wrong word there is a
//            wrong word on every surface at once.
//
// These reads are load-bearing, so they throw rather than defaulting. A gate
// whose source of truth silently becomes {} is a gate that passes everything,
// which is worse than not having the assertion at all.
function readBuildInputs() {
  const csv = readFileSync(join(ROOT, "pipeline", "data", "page_manifest.csv"), "utf8");
  const lines = csv.trim().split(/\r?\n/);
  const head = lines[0].split(",").map((s) => s.trim());
  const zi = head.indexOf("zip"), pi = head.indexOf("page");
  if (zi < 0 || pi < 0) throw new Error("page_manifest.csv has no zip/page column");
  const pages = new Set();
  for (const line of lines.slice(1)) {
    const c = line.split(",");
    if ((c[pi] || "").trim() === "1") pages.add((c[zi] || "").trim());
  }

  const tj = JSON.parse(readFileSync(join(ROOT, "pipeline", "tranches.json"), "utf8"));
  const released = new Set();
  for (const t of tj.tranches || []) {
    if (!t.released_utc) continue;              // unreleased == not published
    for (const z of t.zips || []) released.add(String(z));
  }

  const copy = JSON.parse(readFileSync(join(ROOT, "pipeline", "data", "verdict_copy.json"), "utf8"));
  const words = new Map();                      // level -> the word readers see
  for (const [level, v] of Object.entries(copy)) {
    if (level.startsWith("_") || !v || !v.word) continue;
    words.set(level, String(v.word));
  }

  const live = [...released].filter((z) => pages.has(z)).length;
  if (!pages.size) throw new Error("page_manifest.csv listed no pages");
  if (!words.size) throw new Error("verdict_copy.json defined no rating words");

  // The generators do NOT compute "live" from the tranche file alone \u2014
  // data_pause.shows_data(zip, basis) also requires the ZIP's private record to
  // carry the released basis, and those records live in .build/readings, which
  // is gitignored build output. A job that rebuilds WITHOUT provisioning them
  // (CI's verify step does exactly that \u2014 provisioning runs in a different
  // job) computes live = 0, so coverage_line() degrades to prose rather than
  // publishing "0 of 22,874". That is the correct behaviour.
  //
  // Without this signal the gate demanded a figure the build had deliberately
  // withheld, and failed a deploy whose output was right. 2026-08-22.
  let readings = 0;
  try { readings = readdirSync(join(ROOT, ".build", "readings")).length; } catch { readings = 0; }
  return { total: pages.size, live, words, readings, degraded: readings === 0 };
}

let TRUTH;
try {
  TRUTH = readBuildInputs();
} catch (e) {
  console.error(`\nFATAL: cannot read the build's own numbers — ${e.message}\n` +
    "The coverage and vocabulary assertions have no source of truth without " +
    "them, and a gate that skips its assertions reports a clean run it did not " +
    "earn. Fix the inputs rather than the gate.");
  process.exit(2);
}

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
  // Added 2026-08-22, decided rather than waived. /research/methodology.html
  // carries a dated changelog row explaining how the Warning-Sign Index was
  // BUILT: "Continuous series begins June 2020 (Redfin Data Center hub, ~25k
  // scored ZIPs/month)". That is provenance for a frozen historical index, not
  // a claim about a current source \u2014 and deleting it to make this gate pass
  // would misstate how the index was constructed, which is the worse fault.
  // Anchored to the changelog sentence so a present-tense credit that happens
  // to name the hub still lands as a finding.
  /series begins[^)]{0,40}Redfin Data Center hub/i,
  // Same paragraph, second mention: "The 2012-2019 tail is reconstructed from
  // Redfin's legacy market tracker ... excluded from every record, delta, and
  // superlative." Dated, past, and explicitly fenced off from every current
  // claim. Sibling of the /restated from Redfin's archived tracker/ pattern
  // above \u2014 the research note says it two ways and the gate knew only one.
  /reconstructed from Redfin's legacy market tracker/i,
];
const flat = (s) => (s || "").replace(/[\u2018\u2019\u02BC]/g, "'");
const isHistorical = (s) => HISTORICAL_OK.some((re) => re.test(flat(s)));

// \u2014\u2014\u2014\u2014\u2014 the copy sweep of 2026-08-22, made permanent \u2014\u2014\u2014\u2014\u2014
//
// Seven wordings came off the site in one pass. Every one of them had already
// survived a review, because reviewing a page you wrote reads the sentence you
// meant rather than the sentence there \u2014 and five of the seven were emitted by
// a generator, so a reviewer would have had to read the template, the copy map
// and the record together to see it. These assert on the RENDERED result, which
// is the only place all three meet.
//
// The window helper is shared: several of these are legitimate when negated or
// when they are describing the site's own history, and a check that cannot tell
// "we do not use public data" from "computed from public data" teaches people
// to delete the sentence that fixed the problem.
const near = (s, i, w = 120) => s.slice(Math.max(0, i - w), i + w).replace(/\s+/g, " ").trim();
const NEGATED = /\b(?:not|never|no longer|rather than|isn't|is not|was not|instead of|used to|previously|stopped)\b[^.;]{0,60}$/i;
const isNegated = (s, i) => NEGATED.test(s.slice(Math.max(0, i - 90), i));

// 1. "VERDICT". It promised a ruling this site does not issue, and the sweep
// took it out of every reader-facing string \u2014 titles, meta descriptions, body
// copy, share text, llms.txt. It stays in the ENGINE: level names, JSON keys,
// verdict_v2.py, verdict_copy.py, window.VERDICT_COPY, the CSS custom property
// --fs-verdict. None of those reach innerText, a <title> or a meta content,
// which is why this can be a flat word match on the rendered document instead
// of a source grep that would have to understand JavaScript to be right.
const VERDICT_WORD = /\bverdicts?\b/i;

// 2. PROVENANCE. The market statistics behind a reading are a licensed
// commercial feed. Four phrasings called them public, which is not a loose word
// \u2014 "public" is exactly what a reader checks when they ask whether they could
// get this themselves. The genuinely public inputs keep their names and their
// wording: FHFA, Census and GeoNames are cited where they are used and say
// "public domain", which this does not match.
const PUBLIC_PROVENANCE =
  /\bpublic\s+(?:housing-market\s+data|market\s+data|data|signals)\b/gi;

// 3. THE DISCONTINUED VENDOR, and the current one.
//
// The existing pair of checks above reads all.match(...) \u2014 the FIRST mention \u2014
// so a page whose first mention is a sanctioned historical one passed with any
// number of unsanctioned mentions after it. research/methodology.html is
// exactly that page. This re-reads EVERY mention, and adds the rule the old
// check had no way to express: the sanctioned historical forms are sanctioned
// WHERE THE HISTORY IS. /methodology.html tells the migration's story;
// /research/ carries the pre-2026 series that really is restated from the
// archived tracker. On a ZIP page, a hub, press.html or the homepage there is
// no history to tell, so a historical phrasing there is a vendor credit
// wearing a disclaimer.
//
// The CURRENT vendor joins the discontinued one, for a different reason.
// CITE_V2 stopped naming it on 22,874 ZIP pages, 51 hubs and the markets index
// because the licence bars use of the mark "in advertising, publicity or any
// other commercial manner" (see build_pages.CITE_V2). The name survives in
// exactly one place, and this is what keeps it there.
//
// DELIBERATE GAP, recorded rather than hidden: Realtor.com is not in this list.
// Its cross-check is off behind realtor_crosscheck.shows_crosscheck(), but the
// research footers still credit it as a listing-data source, and whether that
// credit is live or stale is a licensing question this gate cannot settle.
// Adding it here would flag four healthy-looking pages on a guess.
const DISCONTINUED_VENDOR = /\bredfin\b/gi;
const CURRENT_VENDOR = /\brentcast\b/gi;

// 4. THE MIDDLE DIAL. It counts days a listing that is STILL FOR SALE has been
// on the market. Methodology section 2: that is not time-to-contract, and
// across unsold listings it runs longer than one. The old label named a
// quantity the data cannot see.
//
// Case matters here. "is it time to sell?" is a question a homeowner actually
// asks and a headline the metro pages carry on purpose; the ban is on the
// phrase used as the NAME OF A MEASUREMENT. So: the all-caps dial label, the
// sentence-case row label, and the phrase carrying a figure \u2014 never the
// question, which is spelled out as an exception so that removing the
// exception is a visible act.
const TIME_TO_SELL_LABEL = /(?<!IS IT )\bTIME TO SELL\b/;
const TIME_TO_SELL_MEASURE = /\bTime to sell\b(?!\?)|\btime to sell\s*,?\s*(?:vs\.?|y\/y|up|down|at|by|of)\b/;
// \u2026with one exemption, on the surface that owns a sold-basis measurement.
// The Warning-Sign Index runs on a deliberately FROZEN v1 basis so the series
// stays comparable month to month, and its definition table \u2014 the one that says
// "the table below describes this index only" \u2014 really does list months of
// supply, median SALE price and time to sell. Those are sold-basis signals the
// current engine no longer computes, and restating them accurately is the
// disclosure. Rewording that table to satisfy a grep would replace a naming
// problem with a falsified definition, which is the same trade the vendor
// allowlist above refuses. The ALL-CAPS dial label stays banned here too: a
// research page has a definition table, not a dial.
const timeToSellAllowed = (u) => isResearch(u);

// 5. A FROZEN DATE IN A VINTAGE SLOT. A date beside "Data through" or "updated"
// is a claim about the numbers in front of the reader. Three surfaces rendered
// meta.json's stamp there instead \u2014 "updated 2026-08-10" on 22,874 meta
// descriptions, "Data through 2026-06" on every ZIP page and hub \u2014 a build date
// and a withdrawn month, two months stale, beside August readings. The rule the
// sweep settled on: a vintage is SPELLED from the reading's own month ("Data
// through August 2026") or it is absent. So the finding is the raw ISO shape in
// that slot, whatever its value \u2014 which catches 2026-08-10 and 2026-06 by
// construction, and catches next quarter's frozen constant too.
const FROZEN_STAMP =
  /\b(?:data through|last updated|updated|refreshed|current through|as of)\b[^.<>\n]{0,24}\b20\d\d-\d\d(?:-\d\d)?\b/i;

// 6. REPORTED SALES. The v2 engine reads active listings and never sees a
// closed sale, so no page has ever been gated on one. "\u2026with enough reported
// sales to score" was the coverage sentence on /zip/ and all 51 hubs, and "too
// few reported sales" was the waitlist copy on three more surfaces. Both state
// a rule the site does not have, which is worse than stale: it is a reason a
// reader is given for why their ZIP is missing, and it is not the reason.
const REPORTED_SALES = /\b(?:enough|too few|few|no)\s+reported sales\b|\breported sales to score\b|\breported sales\b/i;

// 7. THE VOCABULARY. HOLD / WATCH / ACT / STRONG is the whole published
// taxonomy \u2014 methodology section 4 states all four.
//
// Resolved 2026-08-22, having first got it backwards. verdict_v2.LEVELS maps
// `strong` -> "ACT", and that looks like the canonical display word. It is not:
// it is the ACTION CLASS (\u201Cdo something now\u201D), and ACT is already the word for
// the danger case. Badging a strong seller\u2019s market ACT would tell a screen
// reader, a search snippet and a shared link the OPPOSITE of what it means, and
// that is the exact bug an earlier round fixed by unifying six maps on STRONG.
// So STRONG is published and documented, and this gate guards against a FIFTH
// word rather than against the fourth. Two checks, two failure modes:
//
//   (a) the copy map itself. Checked once, at the source, so the finding names
//       the one file to edit rather than the 22,874 pages that read it.
//   (b) the shape on the page. Matches the CONSTRUCTIONS the site states a
//       rating in, not a list of banned words \u2014 the next fourth word will not
//       be spelled STRONG.
const TAXONOMY = ["HOLD", "WATCH", "ACT", "STRONG"];
const RATING_SLOT = new RegExp([
  String.raw`(?:the |a |its )?(?:reading|rating)\s+(?:is|:)\s*`,   // "the reading is X"
  String.raw`housing market check:\s*`,                            // OG + share-stub title
  String.raw`\b\d{5}:\s*`,                                         // og:image:alt
  String.raw`\b\d{5}\s*\u00B7\s*`,                                      // state-hub row
  // A meta value opening on the word \u2014 "description=STRONG \u2014 Hyattsville\u2026",
  // which is the search snippet. Anchored to the head's own `name=value` line
  // shape, NOT a bare "=": prose contains equals signs, and the loose version
  // read "WSI = ZIP markets at WATCH or ACT" as a rating called ZIP.
  String.raw`(?:^|\n)\s*[A-Za-z0-9:_.-]+=\s*`,
].map((p) => `(?:${p})([A-Z][A-Z'\u2019]{2,})\\b`).join("|"), "g");

// 8. THE COVERAGE COUNTS. Three surfaces state how much of the country is live
// and they used to state it three ways: the homepage summed meta.national.counts
// ("33,000+ ZIP codes", Redfin-derived and frozen), /zip/ printed the manifest
// length under the wrong noun, press.html was typed by hand. All three now have
// to equal \u00A71b, which is computed from the build's inputs \u2014 so three pages
// agreeing with each other while disagreeing with the site is still a finding.
const COVERAGE_PAIR = /([\d][\d,]*)\s+of\s+(?:the\s+)?([\d][\d,]*)\s+(?:U\.S\.\s+)?ZIP codes/gi;
// Any ZIP figure at all on those pages, so a stray fourth number cannot ride
// along beside a correct pair.
const ANY_ZIP_COUNT = /\b([\d][\d,]{2,})\s*\+?\s+(?:U\.S\.\s+)?ZIP\s+(?:codes|markets)\b/gi;
const num = (s) => Number(String(s).replace(/,/g, ""));

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

  checkCopySweep(url, all);
  if (COVERAGE_PAGES.includes(url)) checkCoverage(url, all);
}

// The seven wordings, asserted on the rendered document. Split out of checkDoc
// only so the pause/indexing logic above stays readable — it is the same `all`,
// the same flag(), and it runs on every crawled URL.
// One finding per page per wording. A generator emits the same string into the
// head, the OG tags and the body, so an un-capped check reports one mistake
// four times and buries the next one — the same "gate people learn to ignore"
// the settle-vs-networkidle note above is about.
function checkCopySweep(url, all) {
  const v = all.match(VERDICT_WORD);
  if (v) flag(url, "shows the word \"verdict\" in reader-facing text", near(all, all.indexOf(v[0]), 70));

  for (const m of all.matchAll(PUBLIC_PROVENANCE)) {
    // "It is not public data" is the sentence that fixed this. Flagging the
    // fix is how a gate gets its own disclosure deleted.
    if (isNegated(all, m.index)) continue;
    flag(url, "calls the licensed market feed public", near(all, m.index, 80));
    break;
  }

  // The existing pair of vendor checks above reads the first mention only.
  // Suppressed here rather than duplicated, so one bad credit is one finding.
  const alreadyFlagged = FINDINGS.some((f) => f.url === url && /vendor/.test(f.what));
  for (const m of all.matchAll(DISCONTINUED_VENDOR)) {
    if (alreadyFlagged) break;
    const win = near(all, m.index);
    if (!(url === METHODOLOGY || isResearch(url))) {
      flag(url, "names the discontinued vendor outside /methodology.html and /research/", win);
      break;
    }
    if (!isHistorical(win)) {
      flag(url, "names the discontinued vendor in an unrecognised way", win);
      break;
    }
  }
  for (const m of all.matchAll(CURRENT_VENDOR)) {
    if (url === METHODOLOGY) break;
    flag(url, "names the market-data vendor outside /methodology.html", near(all, m.index, 80));
    break;
  }

  const tts = all.match(TIME_TO_SELL_LABEL) ||
              (timeToSellAllowed(url) ? null : all.match(TIME_TO_SELL_MEASURE));
  if (tts) flag(url, "labels the dial \"time to sell\" — it measures time on market",
                near(all, all.indexOf(tts[0]), 70));

  const stamp = all.match(FROZEN_STAMP);
  if (stamp) flag(url, "states a data vintage as a raw date stamp", stamp[0].trim());

  const sales = all.match(REPORTED_SALES);
  if (sales) flag(url, "gates coverage on reported sales the engine cannot see",
                  near(all, all.indexOf(sales[0]), 70));

  // (b) the shape on the page…
  let vocab = false;
  for (const m of all.matchAll(RATING_SLOT)) {
    const word = m.slice(1).find(Boolean);
    if (!word || TAXONOMY.includes(word)) continue;
    flag(url, `publishes "${word}" as a rating — the taxonomy is ${TAXONOMY.join(" / ")}`,
         near(all, m.index, 70));
    vocab = true;
    break;                      // one page, one vocabulary; the rest is echo
  }
  // …and, only if the shapes missed it, the words the copy map actually holds.
  // This is what catches a fourth word in a table cell or a hub row, where
  // there is no construction around it to match on. Second, not first, so the
  // finding a reader gets names the place the word was published rather than
  // the fact that it exists — §(a) in the report already says that once.
  for (const w of vocab ? [] : new Set(TRUTH.words.values())) {
    if (TAXONOMY.includes(w)) continue;
    const at = all.search(new RegExp(`\\b${w}\\b`));
    if (at < 0) continue;
    flag(url, `renders the off-taxonomy rating word "${w}"`, near(all, at, 70));
    break;
  }
}

// Cross-page consistency. Every ZIP figure on the homepage, /zip/ and
// press.html must equal §1b — not merely equal each other.
function checkCoverage(url, all) {
  const pairs = [...all.matchAll(COVERAGE_PAIR)];
  // A build with no provisioned readings legitimately renders prose instead of
  // a pair. Skip the "must state a figure" assertion there \u2014 never silently
  // (see the banner below), and never skip the two checks that follow, which
  // still catch a figure disagreeing with the build.
  if (!pairs.length && !TRUTH.degraded) {
    flag(url, "states no live/total ZIP coverage figure",
         `expected "${TRUTH.live.toLocaleString()} of ${TRUTH.total.toLocaleString()} ZIP codes"`);
  }
  for (const p of pairs) {
    if (num(p[1]) === TRUTH.live && num(p[2]) === TRUTH.total) continue;
    flag(url, "renders a ZIP coverage pair that is not the build's",
         `page says ${p[1]} of ${p[2]}; the build's inputs say ` +
         `${TRUTH.live.toLocaleString()} of ${TRUTH.total.toLocaleString()}`);
  }
  for (const m of all.matchAll(ANY_ZIP_COUNT)) {
    const n = num(m[1]);
    if (n === TRUTH.live || n === TRUTH.total) continue;
    flag(url, "states a ZIP count that is neither the live nor the total figure",
         `${m[0].trim()} — the build's inputs say ${TRUTH.live.toLocaleString()} live ` +
         `of ${TRUTH.total.toLocaleString()}`);
  }
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

console.log(`  build inputs    ${TRUTH.live.toLocaleString()} live of ` +
  `${TRUTH.total.toLocaleString()} standing ZIP pages · rating words ` +
  `${[...new Set(TRUTH.words.values())].join(", ")}`);
if (TRUTH.degraded) {
  console.log("  coverage        SKIPPED — .build/readings is empty, so the build " +
    "renders coverage as prose. Figures that ARE stated are still checked.");
}

// THE VOCABULARY, AT ITS SOURCE. Asserted once rather than 22,874 times: every
// surface takes its word from pipeline/data/verdict_copy.json, so a fourth word
// there is a fourth word everywhere, and the finding should name the one file
// to edit. The per-page check in checkCopySweep() still runs — this one says
// what is wrong, that one says how far it got.
for (const [level, word] of TRUTH.words) {
  if (TAXONOMY.includes(word)) continue;
  flag("pipeline/data/verdict_copy.json",
       `defines "${word}" as a rating word — the published taxonomy is ${TAXONOMY.join(" / ")}`,
       `level "${level}". verdict_v2.LEVELS maps it to an action class already in ` +
       "the taxonomy; the qualifier belongs beside the word, not in place of it");
}

// The misses that motivated this gate. If the crawler cannot reach them the
// run proves nothing, so this is an assertion rather than a note.
// /zip/ joins them for the coverage assertion: it is the surface that computes
// the count on every build, so a run that never reached it has checked the two
// hand-written copies against each other and called that agreement.
const MUST_REACH = ["/report.html", "/press.html", "/", "/methodology.html", "/terms.html", "/zip/"];
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

// ————— static preflight over shipped JS —————
// The crawler reads document.body.innerText after domcontentloaded, so copy
// that only enters the DOM when a renderer runs is invisible to it, and
// /my-report.html is session-gated so it is never crawled at all. That is
// exactly where the 2026-08-22 sweep missed web/market-render.js: it kept
// "TIME TO SELL" and described time-to-contract on the PAID product, and every
// rendered-output assertion in this file passed anyway. Grep the source too.
const JS_FORBIDDEN = [
  [/\bTIME TO SELL\b/, "the retired dial label"],
  [/\bpublic (?:market data|housing-market data|data|signals)\b/i, "data is licensed, not public"],
  [/\b(?:days from listing to contract|homes sold in the latest month)\b/i,
   "closed-sale language \u2014 the v2 engine cannot see a sale"],
  [/\bRedfin\b/, "discontinued vendor named in shipped JS"],
];
const jsDir = join(ROOT, "web");
for (const name of readdirSync(jsDir).filter((n) => n.endsWith(".js"))) {
  // Strip block comments, then line comments INCLUDING trailing ones \u2014 the
  // first cut of this only removed full-line // and two trailing comments
  // naming a discontinued vendor tripped it. The [^:] guard keeps "https://"
  // intact; without it every URL in the file became a comment.
  const src = readFileSync(join(jsDir, name), "utf8")
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/[^\n]*/g, "$1");
  for (const [re, why] of JS_FORBIDDEN) {
    const hit = src.match(re);
    if (hit) FINDINGS.push({ url: `web/${name}`, what: "forbidden string in shipped JS",
                             detail: `${JSON.stringify(hit[0])} \u2014 ${why}` });
  }
}
console.log(`  js preflight    ${readdirSync(jsDir).filter((n) => n.endsWith(".js")).length} file(s)`);

if (FINDINGS.length) {
  console.error(`\n${FINDINGS.length} finding(s):`);
  for (const f of FINDINGS) console.error(`  ${f.url}\n    ${f.what} — ${f.detail}`);
  process.exit(1);
}
console.log("\nclean\n");
