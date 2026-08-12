# Marketing queue

Every data refresh ends by writing a to-do list: rows in
`public.marketing_tasks`, each with a schedule slot, a paste-ready caption,
and — the part that makes it a queue rather than a content dump — an
explicit "why this, why now" carrying the actual numbers. Generated
deterministically from the data files and Supabase reads — **no LLM calls
anywhere in the pipeline**, so the same data and the same clock always
produce the same rows.

- Generator: [`pipeline/marketing_tasks.py`](../pipeline/marketing_tasks.py)
- Settings: [`pipeline/marketing_config.py`](../pipeline/marketing_config.py)
- Tokens: [`pipeline/utm.py`](../pipeline/utm.py)
- DB layer: [`supabase/schema-v23.sql`](../supabase/schema-v23.sql)
  (after [`supabase/schema-repair-v20-v21.sql`](../supabase/schema-repair-v20-v21.sql)
  on a fresh environment)

## The one rule that governs everything

**Nothing here posts, emails, or sends anything, ever.** The queue is a
list of things a human may choose to do. The generator writes rows with
`status = 'suggested'`; the admin Marketing tab is where a human marks them
posted, skipped, or rescheduled. If you find yourself wiring an API client
for a social network into this pipeline, stop — that is a different product
decision, made on purpose or not at all.

## The calendar is data, not prose (decided 2026-08-10)

The posting rules — 2 brand posts per channel per week, Sunday 19:30 ET is
the anchor, no metro repeated inside 14 days — live in **the database**:
`marketing_windows` holds the slots, `marketing_slot_conflict()` holds the
caps, and the `marketing_tasks_caps` trigger enforces both on every write.
Three readers agree because there is exactly one rulebook:

1. the Python generator fetches `marketing_windows` at run start and
   refuses in Python first (`REFUSED <dedupe_key> <reason>` on stdout, row
   never written);
2. the admin reschedule picker asks `admin_marketing_slots` and renders the
   refusal reasons;
3. the trigger is the backstop for both, plus any hand-rolled service-role
   write.

`marketing_config.FALLBACK_WINDOWS` is a **mirror of the v23 seed for dry
runs and secretless forks only** — `test_windows_fallback_matches_seed`
parses the seed INSERT out of the SQL file and fails the build on drift.
Changing the calendar is a migration, deliberately: an operator-editable
toggle would make "2 posts a week" mean whatever it meant last Tuesday.

## Priority tiers

Stored on the row as `priority_score` (int, 0–5). Lower is louder.

| tier | rule | type | trigger |
| --- | --- | --- | --- |
| 0 | rate burst | `burst` | 30-yr rate moved ≥ 0.25 pts (`rate_watch.py`, Fridays) — 48-hour window, channel NULL, no asset |
| 1 | records | `post` | `strongest_record()` printed a superlative this month |
| 1 | press pitch | `press_pitch` | research release + a configured outlet batch; channel NULL, third business day 09:00 ET |
| 2 | contrarian gap | `post` | operator narrative set for this period AND the verdict mix points the other way |
| 2 | receipt | `receipt_quote` | fresh press corroboration (≤ 35 days) where we were ahead (`lead_days > 0`) |
| 3 | big-metro flip | `post` | top-30 gathering metro's `share_det` crossed 25.0 upward |
| 4 | geo rotation | `post` | the digest's own angle bank — standing-calendar filler |
| 5 | evergreen | `evergreen` | a horizon week would otherwise be empty; `kind != "miss"` cases only |

A skip-demotion adds 1 (capped at 5) — see below. Null-channel rows (burst,
press pitch) are exempt from every cap by the trigger's own rules: null
channel IS the exemption, not a flag.

## Setting NARRATIVE (monthly operator task)

The contrarian rule needs to know what the headlines are saying; that is an
editorial judgement, so it is typed in by hand each month, in
[`marketing_config.py`](../pipeline/marketing_config.py):

```python
NARRATIVE = {"text": "crash headlines dominating", "period": "2026-08"}
```

`period` must equal the data period the refresh runs for — a stale or empty
period makes the rule sit the month out with a loud stdout line, never a
stale claim in a caption. Optional `"stance"` key: `"bearish"` (default) or
`"bullish"`. The narrative text appears in the card's **why**, never in the
caption — operator prose does not ride into public copy; only the
counter-numbers do.

## How Naomi turns on (and why there is no flag)

`nextdoor_naomi` exists in the channel enum but has **zero rows in
`marketing_windows`**, and a channel with no windows can never be scheduled
— the conflict check refuses it by construction. That absence is the off
switch. There is no `NAOMI_ACTIVE` constant anywhere, on purpose (decided
2026-08-10): a config flag can be flipped by accident, in a fork, without a
record. Turning the channel on is a **dated migration**, after a signed
agreement exists — quoting `schema-v23.sql` §2:

```sql
insert into public.marketing_windows (channel, dow, at_time, label, anchor)
values ('nextdoor_naomi', 2, '08:30', 'Tuesday morning', false)
on conflict do nothing;
```

Until that INSERT ships, the generator cannot emit the string
`nextdoor_naomi` into any row (`test_naomi_never_generated`), and even
after it ships, only DMV-ZIP facts are eligible for the channel. Her name
never appears in generated copy either way (`NAOMI_NEVER` guard; see
docs/ATTRIBUTION.md, correction dated 2026-08-08).

## The token scheme

One string does three jobs: `dedupe_key` = `utm_campaign` = asset filename
stem. Minted in [`pipeline/utm.py`](../pipeline/utm.py), deterministic from
the triggering fact, always matching `^[a-z0-9][a-z0-9_-]{1,59}$` — the
same regex the `events.utm_campaign` and `marketing_tasks.utm_campaign`
checks enforce.

| rule | token | example |
| --- | --- | --- |
| records | `mq-{period}-record-us` | `mq-2026-08-record-us` |
| contrarian | `mq-{period}-contrarian-us` | `mq-2026-08-contrarian-us` |
| metro flip | `mq-{period}-flip-{cbsa}` | `mq-2026-08-flip-12420` |
| receipt | `mq-receipt-{uuid}` | `mq-receipt-8b6f…` (one per receipt, ever) |
| geo | `mq-{period}-geo-{zip}` | `mq-2026-08-geo-20904` |
| evergreen | `mq-{ws}-ever-{case_id}` | `mq-2026-08-23-ever-boise-2021` |
| burst | `mq-burst-{rate_period}-{ws}` | `mq-burst-2026-07-2026-08-09` |
| press pitch | `mq-{period}-pitch-{batch_slug}` | `mq-2026-08-pitch-national` |

`{ws}` is the Sunday week-start date — marketing weeks are **Sunday-based
ET** (`marketing_week_start` in v23; the Sunday 19:30 anchor opens the
week). The link is always
`https://shouldisellyet.com/?utm_source={channel}&utm_medium={social|email}&utm_campaign={token}`
— utm_source keeps feeding the existing By-channel funnel; utm_campaign is
the nightly performance join key. Inserts go up **one row per POST** with
`on_conflict=dedupe_key` and `Prefer: resolution=ignore-duplicates` — a
re-run mints identical tokens and inserts nothing, and never resets a
status the operator set (ignore, not merge, is the whole design).

## The demotion rule

A metro skipped **not newsworthy** twice inside 60 days runs one priority
tier lower until the older skip ages out. No table for this: the
`marketing_demotions` VIEW derives it from the skip log, so it cannot
drift. The generator reads the view at run time, adds 1 to the tier
(capped at 5), and **discloses it** — the card's final why line reads:

> Heads-up: Austin-Round Rock-San Marcos, TX is running one priority tier
> lower until Oct 8, 2026 — skipped as not newsworthy twice in the last 60
> days (most recently Aug 9).

Machine refusals can never feed this rule: they are not rows, and the view
counts only the operator's `not_newsworthy` picklist value. Burst and press
pitches are never demoted.

## Press pitches

`PRESS_OUTLET_BATCHES` is empty and `PRESS_LIST` is not a CI secret, so no
press tasks generate yet — the rule prints a labelled gap. That is an
operational gap, not a code gap: configure a batch when there is a list
worth pitching. The task's caption/why carry the full drafted email
(`pitch_draft()` verbatim, release link swapped for the tracked one);
sending it stays a human act, always.

## Verifying a change

```bash
# Everything green, including the seed-mirror and Naomi guards:
python3 -m pytest pipeline/ -q

# The plan, offline — WOULD-INSERT / REFUSED lines, exit 0 without secrets:
env -u SUPABASE_URL -u SUPABASE_SERVICE_KEY \
  python3 pipeline/marketing_tasks.py --dry-run --now 2026-08-10T14:00:00Z

# No banned construction can survive generation (expect 0):
python3 pipeline/marketing_tasks.py --dry-run --now 2026-08-10T14:00:00Z \
  | grep -icE "powered by|in partnership with|official partner"

# The DST pin — Sunday 19:30 ET is 23:30Z in August, 00:30Z+1d in January:
python3 -m pytest pipeline/test_marketing_tasks.py::test_et_slots_dst_and_std -q
```

## Decision notes

- **2026-08-10 — windows in the DB, not in config.** The first draft of the
  generator carried a `CHANNEL_WINDOWS` constant and the admin tab would
  have carried a second copy; both were deleted in favour of
  `marketing_windows` + one conflict function. Two copies of a calendar
  disagree eventually; a trigger cannot be out-argued.
- **2026-08-10 — refusals are not rows.** An unschedulable task in the
  queue is over-scheduling wearing a disguise, and it would consume caps on
  the next run. Dropped candidates regenerate from durable data at the next
  refresh; the REFUSED stdout line is the record.
- **2026-08-10 — `mtl_prose` is imported, never reimplemented.** A median
  months-to-line of 0.0 renders "already at its danger line" — the
  generator additionally refuses any rendered string matching
  `\b0(\.0)? months?\b`, because these strings end up in press emails.
- **2026-08-10 — the pack manifest is the deploy contract.** The generator
  writes `pipeline/marketing/pack-{period}.json` (token, type, asset path,
  public render scalars per task); `post_pack.py --render` rebuilds the
  public card PNGs from it on every deploy. Aggregates only — the paid
  per-ZIP layer never reaches an asset.

## The asset lifecycle (decided 2026-08-10)

Two halves, split the way the rest of the pipeline splits: network at refresh,
pure render at deploy.

1. **Refresh** — `marketing_tasks.py` writes the rows *and* a committed
   manifest, `pipeline/marketing/pack-{period}.json`, holding one entry per
   task: its token, its type, its `asset_path`, and the public scalars its
   card needs.
2. **Every deploy** — `post_pack.py --render` reads that manifest and draws
   `web/assets/mkt/{period}/{token}.png`. No network, no clock, no Supabase.
   The same manifest always produces the same bytes.

**The cards are public, and that is correct.** `web/` is uploaded wholesale,
so every card has a URL. They exist to be posted to Instagram — publishing
them is the point, not a leak. They are gitignored all the same, because they
are re-rendered on every deploy; committing them would be committing a build
artifact.

Nothing personal can reach a card: every renderer takes explicit public
scalars, never a dict passthrough — the same contract `og_card.py` enforces in
its signature. A record card copies the research release's own WSI image
rather than drawing a second one, so the number on the card and the number on
the release page cannot diverge.

Cards reuse `build_research._social_frame` with its footer overridden. One
frame, one brand, one place to change it.

## What the digest says now

Section 3 used to end with a filename in `<code>` pointing at
`archive/{period}/` — a directory that is gitignored, expires with the
90-day Actions artifact, and was never a link. It now ends with the queue:

> **Your marketing queue: 4 tasks this week** → open the queue
> 1. WSI hit 62.2% — the lowest share since December 2025.
> 2. …

If the queue cannot be read — no Supabase config, a failed request,
`schema-v23` not applied — the digest says **"Marketing queue unavailable
this refresh"** and never "0 tasks". A zero is a measurement; a gap is not.
`test_growth_digest.py` holds that line.

## Verifying the whole chain

```bash
# The plan, offline, with no secrets — WOULD-INSERT / REFUSED lines, exit 0:
env -u SUPABASE_URL -u SUPABASE_SERVICE_KEY \
  python3 pipeline/marketing_tasks.py --dry-run --now 2026-08-10T14:00:00Z

# The cards, from the committed manifest — byte-identical on a re-run:
python3 pipeline/post_pack.py --render

# The digest section, without touching Supabase or sending anything:
python3 pipeline/growth_digest.py --demo --out /tmp/mqd
grep -c "archive folder" /tmp/mqd/digest-*.html    # must be 0

python3 -m pytest pipeline/ -q
```

## Receipts: why the queue starts without them (2026-08-10)

The receipt rule works — `test_receipt_rules` covers it, and a fixture renders
the card correctly — but it generated nothing on the first fills, and that is
correct rather than broken. `press_corroboration` is empty, and a receipt is
not something the pipeline can compute. Every row asserts that a **named
outlet published a specific headline on a specific date**, and the card turns
that assertion into a public post that quotes it:

> On Jun 20 our index flagged Boise City, ID. On Jul 31, Idaho Statesman
> reported it: "Boise home sellers face longest waits since 2022." A 41-day
> head start is the kind sellers can actually use.

A seeded or guessed row here is a fabricated citation published as marketing,
on the one surface whose whole pitch is that nothing is quoted from memory.
So the table stays empty until a human logs real coverage. The form is on the
**Markets to Market** tab, panel 2; it refuses to save without a URL and an
article date, and computes `lead_days` itself rather than accepting one.

**THE LEAD TIME IS CAPPED BY OUR OWN RECORD, NOT BY THE PRESS.** `flag_date`
means "when WE first said it", and the earliest date we can prove is
**2026-08-02** — when `verdicts-2026-05.json`, the first committed verdict
snapshot, entered the repo. A receipt logged today can therefore claim at most
an 8-day head start, however long ago the market actually turned. That number
grows one day per day and cannot be hurried; claiming more would mean dating a
flag we cannot show. This is the same discipline the track-record cases follow
(`tools/cases.yml`: no case publishes unless it reproduces), applied to the
present tense.

Practical consequence: expect receipts to start firing meaningfully around
late 2026, once the snapshot history is deep enough for a real lead. Until
then, log coverage as it appears — the rows accumulate, `lead_days` is
computed per row, and the admin panel's median lead time is the number that
eventually becomes the marketing claim.

## Caption design (redesigned 2026-08-10)

The first queue read like research notes pushed to social. Every caption now
comes out of one assembler, `compose()`, so the shape is structural rather
than a thing each rule remembers:

    HOOK       one sentence, the single most surprising fact, hero number
    CONTRAST   the surface-vs-underneath tension — our signature move
    EVIDENCE   one line on why THIS month
    CTA        one link, the short one
    ATTRIB     ShouldISellYet Research · data through {month} + two hashtags

**Two lengths, both written — never truncated.** X is not a premium account
(`X_PREMIUM = False`), so a post there is 280 characters including the link and
the tags, and the long caption does not survive being cut: the contrast is the
one move the brand has, and truncation lands mid-contrast. Each rule supplies a
tight hook and contrast as well, and `caption_short` is BUILT. The admin card
shows whichever one that channel will actually post, with the other behind a
disclosure.

**Number discipline.** At most three numbers, one of them the hero, in the
hook. Thousands separators keep a figure whole (`25,000` is one number a reader
holds, not two) and a year after a month name is a date, not a statistic —
counting those made clean captions fail. Small ordinals are spelled as words:
"the third month in a row" reads, and "3rd" spends one of the three numbers on
a figure nobody needs precisely.

### The linter is not a retry loop

There is no LLM in this pipeline and the templates are pure functions, so
"regenerate on failure" would return the identical string forever. What
`lint_caption()` does instead is attach the reason to the row, and the admin
card shows it in an amber band above the actions — a problem found after
posting is not one the operator can act on. It checks length against the
channel's real limit, exactly one link, at most two hashtags, at most three
numbers, the attribution line, and that "danger line" is defined in plain words
within ~90 characters of its first use.

It lints against the REAL short link. An earlier version measured a stand-in
20 characters shorter and passed a 299-character post as clean.

### The short link is a real page

`/go/{token}/` is a generated static redirect to the full tracked URL, written
by `post_pack.py --render` — the same trick `/s/{zip}` uses on a host with no
server. The obvious alternative (show the bare domain, keep the tracked link in
the admin Copy button) silently breaks the performance loop: the operator
pastes the caption, the posted link carries no campaign token, and
`perf_checks` measures nothing for the life of the post. The link a reader taps
and the link the nightly join counts are the same link.

The token stays in the path. A prettier slug would need a map that can drift,
collide between metros, or 404 a post that is already public.

### Internal notes stay internal

The analyst bullets ("#3 of 25 on the gathering list", "the dial that moved")
were never part of a caption — they are `why_detail`, admin-only. They now sit
below the caption behind a disclosure labelled INTERNAL NOTES — NOT PART OF THE
POST, so nobody reviewing a card can mistake them for copy.

## The card (redesigned 2026-08-10)

The old card was two title lines and a footer borrowed from the research
release's `_social_frame`, with body text starting at y=300 and 900px of
nothing under it. Sharing one frame across two jobs was the earlier call; it
cost the marketing cards their hierarchy, so marketing now draws its own.
`_social_frame` is untouched and still serves the research releases.

    masthead    SHOULDISELLYET RESEARCH · JUNE 2026   + a heavy rule
    market      Grand Rapids, MI  /  full CBSA name beneath, small
    field 1     1 — WHERE THEY ARE HEADED
    hero        76%  at 250pt, navy, ~40% of the card
                + the danger-line definition in plain words
    field 2     2 — WHERE THEY STAND TODAY
    counter     63% still rate HOLD today  (HOLD in the verdict green)
    note        the same ZIP codes, counted two ways — they do not sum
    footer      SHOULDISELLYET                      shouldisellyet.com

**Hierarchy without a second typeface.** Only IBM Plex Mono ships with this
repo — CI must render identical bytes, so a font has to be committed — so the
steps are size and weight: 21 eyebrow / 22 field label / 56 market / 250 hero.
Adding a serif is a one-file change (drop a TTF in `pipeline/fonts/` and point
`font()` at it) if that trade ever looks worth it.

**The accent is navy, never red.** Red reads as fire. This is a smoke detector.

**No sparkline, and not for want of trying.** A six-month share series per
metro is computable from the committed `velocity-{period}.json` files, but a
metro drops off the gathering list in months where it does not qualify —
Grand Rapids has four of six points. A line with holes misrepresents a trend,
so the card carries no chart.

### Why the two figures are laid out the way they are

76% moving toward a danger line and 63% rating HOLD are the SAME ZIP codes
measured two ways, and they routinely sum past 100. A caption has room to say
so; a card does not. Three things stop the arithmetic, in the order a reader
meets them: the denominator is named once above both ("two measures of the
same 76 ZIP codes"), each figure sits under a numbered label posing a
different QUESTION, and a closing line says the two overlap and do not sum.
Someone who still adds them has been told three times.

### The contrarian card is a chart, and that is a deliberate exception

Every other card here refuses one. The per-metro series has holes — a metro
drops off the gathering list in months it does not qualify — and a line with
gaps misrepresents a trend. The NATIONAL series has no such problem: 73
continuous points, read through `research.national_series(segment="continuous")`
so it can never cross the 2020-06 source seam.

It earns the exception because **the story is a shape, not a figure**. "Fewer
neighborhoods are showing warning signs than last month" is an argument about
direction, and no single number can make it: 62.2% on the way down is
indistinguishable from 62.2% on the way up. The line shows the rise, the turn,
and the three months since — the whole claim, before a word is read.

The falling segment is drawn in the verdict green. A falling warning share is
good news, and colouring it like the rest of the line would hide the one thing
the card exists to say. Still no red anywhere.

Below four usable points the card falls back to stating the number plainly. A
line drawn from three points is not a trend.

**run_length is read, never recomputed.** The card first claimed "the fifth
month in a row" against a truth of three, because it counted every declining
step in the twelve-month window instead of consecutive ones from the end. That
number has one home — `research.detect_records()` — and the card, the caption
and the release page all read it from there. `test_run_length_is_read_not_recomputed`
fails the build if the derivation comes back.

## Where a click lands (PR 1, 2026-08-10)

Every post used to open the homepage. Someone who tapped "76% of the ZIP codes
we track in Grand Rapids are moving toward a danger line" arrived somewhere
that does not mention Grand Rapids — the click was spent and nothing kept the
promise that earned it.

    caption shows   shouldisellyet.com/go/{token}/
    redirects to    /metro/grand-rapids-mi/?utm_source=x&…&utm_campaign={token}
    which is        a page about Grand Rapids

`link_target` resolves **most-specific-first**: the ZIP's page if the post is
about a ZIP, else the metro's, else the month's report. Resolving metro-first
sent posts about 20001 to Washington DC's page. The homepage is refused by the
caption lint AND by a CHECK constraint on the column — a convention would
drift, so it is a rule in two places.

`pipeline/build_metro.py` generates 608 metro pages on every deploy from
committed data, plus `/metro/` and the `/methodology` short route (the page
itself has lived at `/research/methodology.html` since the research build
shipped; this is the quotable path to it, not a second copy).

**What already existed, and was wired rather than rebuilt:** `/research/{yyyy-mm}/`,
`/zip/{zip}/`, `/?zip=`, the methodology page, and the `/go/{token}/` short
links. Only the metro page was missing.

### The paywall is not crossed by these pages

Per-ZIP approach velocity — the projected months until a ZIP reaches a danger
line, and its 3-month pace — is the **paid product**. So a metro page shows
each ZIP's public dial values against their published danger lines (the same
numbers every `/zip/` page shows) and never the projection. Metro-level
velocity is public and appears as one figure.

### Two figures, again

The hero is two labelled measures side by side — "where they stand today"
(rating share) and "where they are headed" (velocity share) — for the same
reason the card carries them that way. A post leading with 76% that landed on
a page whose hero read 30% would have broken its own promise, and the two
overlap and sum past 100.

The page also counts the same population as the post: ZIPs without a usable
verdict are excluded, which is the filter `build_pages.py` already applies.
Before that fix the page said 78 ZIP codes while the post said 76.

## The voice charter, enforced (PR 2, 2026-08-10)

Most of the charter already shipped with the caption redesign. PR 2 closed the
three rules that were stated but not checked, so a future template edit cannot
quietly reintroduce them.

**Acronyms never lead.** An index name in the hook asks a stranger to care
about our vocabulary before we have given them a reason to care about the
number. The hook states the plain-language meaning; the acronym may appear once,
later, in parentheses, and is optional. Checked on the first sentence.

**All-caps is not tone.** Shouting is refused anywhere in the post. The
exceptions in `CAPS_ALLOWED` each earn it: HOLD / WATCH / ACT / STRONG are the
product's own vocabulary and the site defines them; ZIP, US and the state codes
are how people write the places they live.

**A percentage never sits beside its own denominator.** "76% of its 76 scored
ZIPs" reads as a typo to everyone who is not us — state a count or a share,
never both. Tolerance is 3 points.

`why_headline` is exempt from all of this, deliberately: it is the admin card's
title, read by one operator who knows what WSI means, and precision there is
worth more than accessibility. Only `caption` and `caption_short` reach the
public, and the jargon table is enforced against real generated output rather
than trusted to the templates (`test_jargon_never_reaches_a_public_field`).

Nothing in the live queue violated any of the three when they were switched on —
the copy was already right. The rules exist so it stays that way.

## Three a week, and the windows to hold them (2026-08-10)

The cap went from 2 to 3 per channel per week, to make room for the post
taxonomy: its quota table wants roughly 18–22 posts a month, and 2/week across
three channels tops out near 24 with no slack — low-priority types would have
been refused every week rather than occasionally.

**Raising the number alone would have done nothing.** The real limit is
`min(cap, windows the channel has)`, and ig and fb had exactly two windows —
Sunday 19:30 and Wednesday 08:30. So schema-v27 adds a Friday 08:30 window to
both before raising the cap. The two changes belong in one migration for that
reason. X already carried three (it has Tuesday as well) and is unchanged.

The cap is a **matched set** and moves together or not at all:
`marketing_slot_conflict` (enforcement) · `admin_marketing_week`'s guidance
(what the operator is told) · `MAX_WEEKLY_PER_CHANNEL` (the Python refusal) ·
`FALLBACK_WINDOWS` (the dry-run mirror). `test_weekly_cap_matches_the_sql_that_enforces_it`
fails the build if the Python and the SQL disagree — otherwise the generator
plans a post the database rejects, which reads as a mystery failure in CI.

Note that with three windows and a cap of three, the cap is currently
non-binding: R1 (no window) or R4 (slot taken) refuses first. It stays as
defence in depth and starts binding the moment a fourth window is added.

## thread_position

A recap thread is a lead plus three to five replies plus a closer, and the
model is one row per POST. Operator decision: `thread_position`, not a
parent/child id.

`thread_key` groups the rows; `thread_position` is 0 for the lead and 1..n for
the replies in order. Both NULL for a standalone post, which is almost all of
them, and a CHECK makes the pair all-or-nothing — a position with no thread is
a reply to nothing.

**Why position and not a parent uuid.** The generator inserts one row per POST
request precisely so a refused row cannot roll back its siblings, so a parent
id would have to dangle until the lead lands. An order needs nothing to exist
first and cannot point at a row that was never written. `(thread_key,
thread_position)` is unique, so a re-run cannot double a reply.
