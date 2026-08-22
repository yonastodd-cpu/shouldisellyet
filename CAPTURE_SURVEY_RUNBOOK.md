# Third-party capture survey — runbook

**Status: nothing has been run. No third party has been contacted.**

Counsel has been asked two questions, and they are separate:

1. Should we survey external caches and archives for copies of the surfaces
   that leaked?
2. Should we ask for those copies to be removed?

This runbook and the tool at `scripts/capture-survey/` answer only the first.
The second has its own section below, it is procedure rather than code, and it
does not begin until counsel signs off — because **a removal request is itself
a discoverable act**, and that cost may exceed the benefit.

Nothing in `scripts/capture-survey/` can perform a removal request. One POST is *registered* — Facebook's
`scrape=true` — solely so that its exclusion is on the record: the planner
refuses to emit it and the transport refuses any verb but `GET`. No removal
endpoint is wired to anything, and no credential is read from any source. That is enforced by
`test_capture_survey.py`, not merely intended.

> **A note on where this file lives.** This repository is public.
> `.gitignore` already keeps `AUDIT_REPORT.md`, `LICENSE_AUDIT.md`,
> `GITHUB_PURGE_REQUEST.md` and `DERIVED_USE_INVENTORY.md` out of it, for the
> reason written there: a register of open exposures does not belong in the
> same public place as the exposures. This file is a procedure, not a
> register, so it is closer to `INVALIDATION_RUNBOOK.md`, which is tracked.
> **Decide deliberately rather than by default** — and note that the removal
> section below is a description of steps we have not taken, which reads
> differently in public than in counsel's folder. The tool's *output* is not a
> judgement call: it names retrievable copies and the timestamps to fetch them
> by, and the writer refuses to write it inside this repository at all.

---

## Part 1 — the read-only inventory

### What it surveys

| | |
|---|---|
| **URL set** | The leaked surfaces from the memo's three rounds. Derived from the repository, not typed: `pipeline/data/page_manifest.csv` gives the 51 state hubs and 22,874 ZIP pages with their share stubs, `pipeline/research/research-*.json` gives the released research months. Six one-off pages — the homepage, the markets index `/zip/`, `/report.html`, `/press.html`, `/llms.txt` — are written out in `targets.py`, each tied to the `pipeline/surfaces.py` entry that identified it. |
| **Sources** | Web-archive capture inventory (Internet Archive CDX), search-engine cache presence, social-preview caches on platforms with public debug endpoints. |
| **Windows** | `windows.py`. Open at the start — the earliest archived capture *is* the evidence of when exposure began, and inventing a start date would throw that away. Closed at the moment each thing stopped. |

The exposure windows, and where each date comes from:

| Window | Closes | Precision | Record |
|---|---|---|---|
| `consumer_figures` | 2026-08-20 | day | `REMEDIATION_DATES.md` — "Redfin display stopped — actual … This is the honest date." Not the 19 August first pass: two surfaces were still live on the 20th. |
| `vendor_credits` | 2026-08-21 | day | The memo's third round: the vendor credit stayed on pages that had already stopped showing figures. |
| `research_zip_file` | 2026-08-21T03:22:25Z | second | `REMEDIATION_DATES.md` — per-ZIP research file withdrawn. |

Context, not a window: Redfin ingestion stopped **2026-08-14T13:53:43Z**
(`pipeline/data_pause.INGESTION_STOPPED_UTC`).

**One date to settle before the memo is filed.** The memo places the credits
round on 21 August; commit `29c7d0d`, which removes the credit, is dated 20
August. The tool follows the memo, which is the wider and therefore
conservative reading — it marks more captures in-window, never fewer. Confirm
against the deploy log and correct `windows.py` if the memo moves. The plan
output prints this conflict every time so it cannot be forgotten.

### Run the plan — this is the default and it makes no requests

```
python3 scripts/capture-survey/survey.py
python3 scripts/capture-survey/survey.py --scope core --full
python3 scripts/capture-survey/survey.py --scope all --out ~/counsel/capture-survey
```

It prints the target counts, the windows, every mechanism with its
availability, and the exact URL of every request that would be made. `--out`
additionally writes `capture-survey-plan-{stamp}.csv` — one row per intended
query — which is the thing to send counsel when asking for the go-ahead.

Scopes:

| `--scope` | Targets | Stage-1 requests | Wall clock at 1s apart |
|---|---|---|---|
| `core` | 60 | 115 | ~2 min |
| `priority` *(default)* | 140 | 275 | ~5 min |
| `all` | 45,808 | 91,611 | ~25 h |

`priority` is `core` plus the ZIPs already ranked in
`scripts/og-priority-urls.txt`. **That ranking is a housing-supply proxy, not
a traffic ranking** — Search Console had no impression data when it was built
— and that caveat travels with any finding drawn from it.

### Reading the plan honestly

Of the three sources, **one can be surveyed without a credential.**

| Source | Mechanism | Can we run it? |
|---|---|---|
| Web archive | CDX capture index; stored snapshot body | **Yes.** Public, no credential. |
| Search cache | Google `cache:` operator | No — retired in 2024, no successor. |
| Search cache | Search Console URL Inspection | No — needs OAuth for the property. Also reports *our* index coverage, not a third party's cached copy. |
| Search cache | Bing cached page | No — needs a per-result document id from a paid Web Search API response; not addressable from a URL alone. |
| Search cache | Automated `site:` query | No — automated querying of a search interface. Needs the same sign-off as Part 2. |
| Social preview | Facebook Graph `og_object` read | No — needs an app access token. This is the only social-preview read that is genuinely a read. |
| Social preview | Facebook `scrape=true` | **Excluded by design.** It is a mutation — see Part 2. |
| Social preview | LinkedIn Post Inspector | No — no public read API, and inspecting *refreshes* the cache, so it is a mutation too. |
| Social preview | X Card Validator | No — retired. |

That is a finding, not a gap in the tool. The searchcache and socialpreview
CSVs are written anyway, one row per URL per mechanism, each saying which
mechanism could not be run and why. **"No credential-free way exists to find
out" is a factual answer; a missing row is not.**

### Run the collection — only after counsel says yes to question 1

```
python3 scripts/capture-survey/survey.py --collect --out ~/counsel/capture-survey
python3 scripts/capture-survey/survey.py --collect --scope all --source webarchive \
    --out ~/counsel/capture-survey
```

`--collect` is the only flag that opens the network. Without it nothing in the
tree loads an HTTP client at all. `--out` is required — a survey whose output
is only on a terminal is not an exhibit — and it must be **outside this
repository**; the writer refuses otherwise, and refuses to overwrite an
existing file.

Two stages. Stage 1 asks the capture index what exists for each URL, under
both spellings — a capture of `/s/77494` is invisible to an exact query for
`/s/77494/`, and both spellings were in circulation. Stage 2 fetches stored
snapshot bodies to answer whether a withdrawn figure is actually **visible**,
which is the column that matters. By default stage 2 fetches every in-window
capture plus the first capture after the window closes. That last one is the
control: it is what shows the archive holding a clean copy afterwards, which
is the difference between "we found old copies" and "we found old copies and
here is where they stop".

`--bodies none` runs stage 1 only, if the point is just to size the problem.

### The output

One CSV per source, same schema, so the three can be opened side by side:

```
url, url_variant, surface, memo_round, tier, source, mechanism, availability,
capture_utc, capture_id, in_window, windows_matched, http_status, mime,
digest, retrieval_url, figures_visible, visibility_verdict, evidence,
checked_utc, note
```

`figures_visible` is **yes / no / unknown**, and `visibility_verdict` carries
the reasoning behind it:

- `figures_visible` — a specific market's number is on the page;
- `rating_visible` — a rating word where it can only be a reading;
- `vocabulary_only` — the page names HOLD / WATCH / ACT but publishes no
  reading. **Not a leak.** `/zip/` and `/press.html` describe the product and
  were correct as written; a survey that flags them is one counsel has to be
  talked out of;
- `clean` — nothing withdrawn found;
- `not_fetched` — no body was retrieved; the `note` column says why.

The published danger lines (`−2%`, `+30%`, and the rest) are subtracted before
the scan. They are ours, identical on every page, and stating them is the
product. The literals are kept byte-identical to `scripts/smoke-browser.mjs`
so the survey and the deploy gate cannot disagree about the same bytes.

`retrieval_url` re-fetches the exact capture behind any row, so every finding
can be checked by hand.

### Honest limits — say these out loud in any summary

- **The archive is not the internet.** A URL with no captures has not been
  shown to be uncached; it has been shown not to be in *that* archive.
- **The search engines cannot be checked at all** without a credential we do
  not hold, and Google's cached-page mechanism no longer exists.
- **The social platforms cannot be read** without a token, except by actions
  that refresh the cache — which changes the thing being measured.
- **A preview already delivered into a conversation is a screenshot.** No
  survey and no removal reaches WhatsApp, iMessage, Telegram or Slack.
- **We cannot enumerate what was shared.** The site kept no record; only that
  share stubs were generated for all 22,874 ZIPs.
- **`--scope all` is 45,808 URLs and about 25 hours.** A partial run that
  looks complete is worse than a small one that says its scope. The tool
  flags any URL whose capture list hit the row cap.
- **The survey is itself logged.** Every request identifies itself in
  `User-Agent` — deliberately, because a survey conducted behind an anonymous
  agent is a worse fact than one conducted openly. Counsel should approve the
  string before the first run.

### One thing the plan turned up

At `--scope all` the plan cross-checks the target set against the built
sitemap. One published URL falls outside it: **`/methodology.html`**. It is
not on the memo's list because it was not withdrawn — but
`DERIVED_USE_INVENTORY.md` (C3, E4, E8) records that its backtest table has
former-vendor lineage and is still live. That is a live-exposure question, not
a capture-survey question, and it is flagged here so it is not mistaken for an
omission.

---

# Part 2 — removal requests

# ⚠️ REQUIRES COUNSEL SIGN-OFF. DO NOT BEGIN ANY STEP BELOW.

**Nothing in this part is automated, and nothing in `scripts/capture-survey/`
can perform it.** These are manual steps, written down now so that a "yes"
can be acted on the same day, and left manual so that no flag, no default and
no future edit can start one by accident.

## The caveat, which applies to every procedure in this part

> **A removal request is a discoverable act.** It is a dated, written
> communication in which we identify material, identify ourselves, and ask a
> third party to destroy it. It creates a record at the platform and a record
> here. It may be read as an admission that the material should not have been
> published, and it tells the platform — and anyone who later asks the
> platform — precisely which URLs we consider a problem and when we concluded
> that.

This is repeated under every platform below. It is repeated on purpose: the
decision is per-platform, and the caveat does not get weaker the further down
the list you read.

Before any request:

1. **Counsel signs off in writing**, per platform, naming the URLs.
2. **The factual survey is complete first.** Ask for removal of things shown
   to exist. A request listing URLs we never checked is a request that
   describes our own uncertainty.
3. **Record the decision either way** in `REMEDIATION_DATES.md`, with a UTC
   timestamp, when it happens — including a decision *not* to request. Per
   `LEGAL_HOLD.md` rule 4, dates come from the record.
4. **Preserve before requesting.** `LEGAL_HOLD.md` is in force. Anything we
   ask a third party to remove must first be captured into the preservation
   archive at `/Users/yonastodd/SISY-LEGAL-HOLD-2026-08-22/`, with its
   SHA-256 in `PRESERVATION_MANIFEST.md`. **Asking a third party to destroy
   material we have not preserved ourselves is the one sequence that must
   never happen.**

## Internet Archive (web.archive.org)

**Discoverability: a removal request here is a discoverable act.** See above.

- **Mechanism.** Email `info@archive.org` from an address at the domain,
  identifying the site, the URL patterns, and the basis. There is no
  self-service form and no API.
- **What can be asked for.** Exclusion of URL patterns from public playback.
  Captures are generally excluded from view, not destroyed.
- **`robots.txt` no longer does this.** The archive stopped honouring
  `robots.txt` for exclusion years ago. Do not add rules expecting them to
  work; a rule that does nothing but appears in our own history is a fact
  someone has to explain later.
- **Weigh first.** The archive is the most likely place a capture of any of
  these URLs actually exists, which cuts both ways: it is the highest-value
  request and the most legible one.
- **Scope discipline.** Ask for the specific patterns the survey found —
  `/research/{month}/zip-flips-{month}.csv` is a different request from
  `/zip/*`. A broad request covering URLs we have not shown to be captured
  reads as a request to erase the site.

## Google

**Discoverability: a removal request here is a discoverable act.** See above.

- **Cached copies: nothing to ask for.** The cached-page feature is gone.
- **Search results for our own property.** Search Console → Removals →
  Temporary Removals hides a URL from results for about six months. It is our
  own property, so it is a self-service setting rather than a request to a
  third party — the least discoverable option in this document. It does not
  remove anything from anyone's storage.
- **Refresh Outdated Content** applies to pages that changed. Our pages
  changed rather than disappearing, so this is the right tool if the goal is
  to get a stale snippet re-crawled.
- **Note the interaction with the pause.** `data_pause.robots_meta()` already
  serves `noindex` on affected pages, crawlable on purpose — a blocked page is
  never crawled, so the `noindex` is never read and the URL lingers. Do not
  add `robots.txt` blocks on top of a removal request; they work against each
  other.

## Bing

**Discoverability: a removal request here is a discoverable act.** See above.

- Bing Webmaster Tools → Content Removal, for our own verified property.
  Removes URLs and cached copies from Bing results.
- Same character as Google's temporary removal: our own property, a setting
  rather than a letter.

## Facebook / Meta

**Discoverability: a removal request here is a discoverable act — and this
one is a request *and* a mutation.** See above.

- **`POST /?id={url}&scrape=true`** (the Sharing Debugger's "Scrape Again")
  tells Meta to refetch the page and replace what it holds. It is the only
  real programmatic purge of the ones in this document.
- **It is deliberately absent from the tool.** It is registered in
  `sources.py` with `mutating=True` and the planner refuses to emit it, so
  that a survey cannot perform one by accident. `scripts/rescrape-og.sh`
  already exists and drives it; use that, under sign-off, not this tree.
- **It needs an app access token.** No token is wired into
  `scripts/capture-survey/`, and a test asserts none ever is.
- **What it does and does not do.** It replaces Meta's cached preview. It does
  not touch a preview already delivered into someone's feed or messages.
- **Sequencing.** The pages already changed `og:image` from
  `/og/{period}/{zip}.png` to `/og/default.png`, and the old per-ZIP image
  URLs now 404. A re-scrape therefore fetches genuinely new metadata. Do not
  add a cache-bust parameter — see `INVALIDATION_RUNBOOK.md` for why it would
  be misleading here.

## LinkedIn

**Discoverability: a removal request here is a discoverable act.** See above.

- Post Inspector, one URL at a time, in a browser. Inspecting refreshes the
  cached preview. There is no API and no batch form.
- Practically this means a hand-worked list. Take it from the survey's
  `figures_visible = yes` rows, highest exposure first.

## X / Twitter

**Discoverability: a removal request here is a discoverable act.** See above.

- The Card Validator is retired. There is no forced refresh and no read.
- Caches expire on their own, typically within about a week
  (`INVALIDATION_RUNBOOK.md`). Given the withdrawal dates in Part 1, that
  window has passed. **Waiting was the remedy and it has already run.**
  There is most likely nothing to ask for, which is worth stating in the memo
  rather than leaving as an open item.

## WhatsApp, iMessage, Telegram, Slack

**No procedure exists. There is nobody to ask.**

These cache per-client or per-conversation with no public purge. Expiry is the
only remedy, and a preview already delivered into a conversation is a
screenshot that cannot be recalled. Say so plainly rather than listing a step
that does not exist.

---

## Verification and record-keeping

After anything in Part 2:

1. Re-run the survey read-only against the affected URLs and keep both CSVs —
   before and after. The writer refuses to overwrite, so both survive by
   default.
2. Re-run the production audit for the consumer surfaces:
   `python3 scripts/audit-og.py scripts/og-priority-urls.txt`
3. Append to `REMEDIATION_DATES.md`, UTC, when it shipped and how it was
   verified.
4. Keep every CSV with counsel's material. **Not in this repository.**
