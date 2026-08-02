# Growth Ops digest

Every data refresh ends by emailing one digest: where verdicts flipped, what
to post, what to pitch, and which ZIPs are warm. Generated deterministically
from the data files and Supabase counts — **no LLM calls anywhere in the
pipeline**, so the same data always produces the same digest.

- Generator: [`pipeline/growth_digest.py`](../pipeline/growth_digest.py)
- Settings: [`pipeline/growth_config.py`](../pipeline/growth_config.py)
- Weekly rate job: [`pipeline/rate_watch.py`](../pipeline/rate_watch.py)

## The privacy rule

**The digest reports counts per ZIP and nothing else.** Never a subscriber
name, email, address, or any personal financial input (home value, mortgage
balance, equity, walk-away, rate, PITI, purchase price).

This is enforced in code, not just intended: the Supabase reads select only
`zip`, `plan`, `status`, `watches` and `created_at` — the contact columns are
never in the query. If you add a section, add it the same way.

To verify after a change:

```bash
python3 pipeline/growth_digest.py --dry-run --out /tmp/d
grep -icE "@[a-z]+\.(com|io)|first_?name|last_?name|calc_inputs" /tmp/d/digest-*.html
```

Expect `0`. (The words "emails" and "addresses" *do* appear — in the footer
sentence stating what the digest never contains.)

## What's in it

| # | Section | Playbook action |
| --- | --- | --- |
| 1 | Flip counts + DMV flips listed individually | **Call or post this week** on anything local |
| 2 | Local angle bank — 5 paste-ready facts | **Social post**, verbatim |
| 3 | Press hook of the month + CSV | **Press pitch** to a local reporter |
| 4 | Subscriber-adjacent flips | **Group post** where those people already are |
| 5 | Warm ZIPs (improving + real users) | **`/partners` agent recruitment** |
| 6 | Rate vs. last month | **Burst play** when it clears ±0.25 pts |
| 7 | 30-day scorecard | If flat, sections 1–6 are the levers |

Each section header carries its own "So what" line in the email, so the action
travels with the data.

## Angle bank selection rules

Five facts. Rules are applied **in order**, each drawing from the **DMV pool
first, then national**, and a ZIP is used at most once so five rules yield five
distinct places:

1. Largest year-over-year change in days-on-market
2. Lowest months of supply
3. Largest 12-month price change, either direction
4. A ZIP that flipped this month
5. The seasonal note, if the current month is some ZIP's historically fastest

If a rule finds nothing, the next one fills the slot; leftovers are topped up
from the national pool.

**Thin-ZIP guard:** ZIPs with fewer than `MIN_SOLD_FOR_ANGLE` (15) reported
sales are excluded. In a ZIP with four sales, one unusual house swings the
median enough to produce a headline number that isn't real — and these
sentences are meant to be pasted without checking.

## Editing it

All in [`growth_config.py`](../pipeline/growth_config.py), no code changes:

- **`DIGEST_RECIPIENTS`** — default recipients. In CI the
  `OPS_DIGEST_RECIPIENTS` secret (comma-separated) overrides it, which is the
  easy way to add someone without a commit.
- **`DMV_PREFIXES`** — ZIP prefixes treated as the home market. Drives both
  ordering (DMV first everywhere) and the "local" count in the subject line.
  Add a prefix to widen; it's matched with `startswith`.
- **`RATE_BURST_POINTS`** — the move that counts as a marketing window
  (default 0.25), used by both the monthly digest and the weekly job.
- **`ANGLE_COUNT`**, **`MIN_SOLD_FOR_ANGLE`** — angle bank size and the
  thin-ZIP floor.

## The weekly rate watch

`.github/workflows/rate-watch.yml`, Fridays 14:00 UTC (after Freddie Mac's
Thursday PMMS release). **It emails only when the rate has moved ≥0.25 points
since the last digest's stamp.** Silence is the normal, correct outcome — a
job that emails weekly gets ignored within a month.

Test both paths without waiting for the market:

```bash
python3 pipeline/rate_watch.py --dry-run --force-rate 6.70   # small move → silent
python3 pipeline/rate_watch.py --dry-run --force-rate 6.20   # big move → would email
```

## Snapshots, and why they're in the repo

Month-over-month diffing needs last month's verdicts.
`pipeline/snapshots/verdicts-{YYYY-MM}.json` (387 KB, zip → verdict level) is
**committed**, deliberately.

The obvious home would be `archive/{YYYY-MM}/` next to the raw files — but
those are gitignored workflow artifacts that **expire after 90 days**, so a
verdict history kept there would silently vanish and break the diff every
quarter. In-repo costs ~4.7 MB/year and never disappears.

CI commits the snapshot after each refresh. If that push fails the run still
succeeds; the next digest just renders as a **baseline** and says so.

## Failure behaviour

- **A digest failure cannot fail the data refresh.** The step is
  `continue-on-error`; the site data and deploy are already good by then.
- If it fails, a fallback email goes out — *"refresh succeeded; digest
  failed"* with a link to the run log. That step is also non-fatal, so a
  Resend outage can't cascade.
- **Missing Supabase tables degrade to a labelled gap**, never a crash and
  never a misleading zero. Sections 4 and 5 print "Not available" and the
  reason appears in a **Gaps this run** box at the foot of the email.
- A first run with no prior snapshot sends a **baseline** digest that states
  there are no flips *because there's nothing to compare to*.

## Known gap

**No analytics are installed on the site** — no Plausible, GA, Umami, or
anything else. So the scorecard's "Visits by `utm_source`" renders
`not tracked yet`, and the UTM tags on the ZIP pages and share links are
currently being collected by nobody. Installing any privacy-friendly analytics
with a queryable API would light up that row; the digest already has the slot.
