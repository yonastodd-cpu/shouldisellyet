# Warning-Sign Index — the three options, built and waiting

**Status: nothing has changed.** The index publishes today exactly as it did
yesterday. This document describes three futures that are now *built* — a flag
flip, a rebuild, and they are live. It does not choose between them. That
choice is counsel's.

**Nothing here deletes anything.** `pipeline/research/history.json` — 173
monthly values, March 2012 to July 2026, every one computed from Redfin data —
is untouched in every mode, as `LEGAL_HOLD.md` requires. These options change
only what is *published*. Where a mode stops publishing a value, the stored
value stays.

**The Redfin credit stays while the data does.** No mode strips attribution
from something still being published. Stripping the credit while continuing to
publish would be the worse fault, so the credit follows the data.

---

## The two switches

| Flag | Values | Default | Where |
|---|---|---|---|
| `INDEX_MODE` | `full` · `truncated` · `paused` | `full` | `pipeline/research.py` |
| `INDEX_LICENSE` | `current` · `restricted` | `current` | `pipeline/research.py` |
| `INDEX_CUTOFF` | a month, `YYYY-MM` | `2026-08` | `pipeline/research.py` |

Set as environment variables in CI, read once at import, monkeypatchable in
tests — the same shape as `pipeline/data_pause.py` and
`pipeline/realtor_crosscheck.py`. **Flipping one is a variable change plus a
rebuild**, not a code edit and not an instant switch: this is a static site,
so every surface is baked at build time. An unrecognised value **stops the
build** rather than falling back to the default, because the dangerous
fallback is the one that republishes what we were asked to stop publishing.

`INDEX_CUTOFF` defaults to **2026-08**, the first month on the current
vendor's basis: RentCast readings went live with tranche-1 on 20 Aug 2026, and
July 2026 is the last Redfin-basis index value. If counsel draws the line
somewhere else, that is a variable, not a project.

---

## `INDEX_MODE=full` — the default, today's behaviour

**What it does:** publishes the whole series, 2012-03 → present, with the
disclosed 2020-06 source seam drawn as a break in the chart and labelled in
the CSV's `series` column.

**What a reader sees:** the site as it is now. Verified: a default build is
**byte-identical** to the build before this switch existed — same files, same
bytes, including the charts and share cards.

**What it does not do:** nothing changes. This is the status quo, held
deliberately until there is an answer.

---

## `INDEX_MODE=truncated` — the current vendor's era only

**What it does:** publishes index values **from `INDEX_CUTOFF` forward only**.
The chart, the history CSV, the release pages, the hub, the share cards, the
`<title>`, the meta description and the JSON-LD all regenerate from the cutoff.
The stored history is not modified.

**What a reader sees:**

- A chart that starts at the cutoff and carries, printed inside the image:
  *"History before August 2026 was computed from a prior vendor's data and is
  no longer distributed; the series restarts on the current basis."*
- The same sentence on the release page beside the chart, on the hub, on the
  methodology page, in `LICENSE.txt`, and in a new `SERIES-BREAK.txt` in every
  release folder. **No silent splice**: a truncated series that says nothing
  reads as a young index, and that would be its own misstatement.
- `wsi-history.csv` starting at the cutoff, rows still labelled by `series`.
- Releases **before** the cutoff keep their URLs, their state and metro
  aggregates, their downloads and their place in the hub's release table — but
  their index value is withheld and the break note stands in its place. A June
  page still headlining 61.9% while the CSV refuses to carry June would be
  incoherent, and a reader would be right to notice.
- With today's data and the default cutoff, **no v1 value is publishable at
  all** — July 2026 is the last one and it is pre-cutoff. `wsi-history.csv`
  ships as a header row and nothing else until the first v2 month lands. That
  is the honest reading of "truncate to the current vendor's era", not a bug.

**What it does not do:** it does not modify or delete `history.json`, does not
remove any page or URL, does not change any aggregate (state and metro warning
shares are unaffected), and does not restate history under new thresholds.

---

## `INDEX_MODE=paused` — index withheld while under review

**What it does:** withholds every index value everywhere while keeping the
research section standing.

**What a reader sees:**

- Research pages render as usual **minus the index**: state map, state
  paragraphs, metro league tables, flip counts, streaks and downloads all
  stay. In their place at the top: *"The Warning-Sign Index is under review
  and is not being published this month. The aggregates on this page are
  unaffected."*
- The chart URL survives and the image carries that sentence, so a link from
  an old article resolves to an explanation and not a broken image.
- The share card carries the notice instead of the number — a withdrawn value
  left in a 1200×630 unfurl is not a withdrawn value.
- No index value in the `<title>`, the meta description, the JSON-LD graph, or
  `/research/wsi.json`. The homepage and the admin dashboard feature-detect
  that file and degrade quietly, by design.
- The history file URL stops being published, and every withdrawn URL is
  listed in `/research/gone.json` with `"status": 410`.

**The 410 caveat, stated plainly.** The site is served by GitHub Pages, which
serves static files and **cannot return a status per path**. `gone.json` is
the manifest a serving layer needs; until something reads it, those URLs
simply stop being published (a 404, which says "never here", not "withdrawn").
Making 410 real needs one of: a CDN/edge rule in front of Pages reading
`gone.json`, or a move to a host that can set status codes. That is a hosting
change, outside this build — it is named here so nobody assumes it is done.

**What it does not do:** it does not delete the stored history, does not
remove a single page or release URL, does not touch the aggregates, and does
not stop the index being *computed* — only published. Reversing it is the same
flag flip in the other direction.

---

## The v2 index (scaffolded, not yet running)

July 2026 is the last Redfin-basis value. The successor — the share of ZIPs
crossing the **v2 danger lines on the RentCast active-listing basis** — is
wired as a **separate named series**, not a continuation:

- Its own file, `pipeline/research/history-v2.json` (does not exist yet;
  absent reads as an empty series and changes nothing).
- Its own label in the CSV's `series` column: `v2-active-listings`. v1 rows
  keep their own labels; nothing is relabelled or appended.
- Its own stroke on the chart, in its own colour, with a hard vertical rule
  and the words **"new basis — different index"** where it starts. The two
  lines are never joined: v2 measures different signals against different
  lines over a different universe, and a connecting segment would draw a
  market move that never happened.

**It does not do:** compute anything. Nothing writes `history-v2.json` yet.
This is the shape it must arrive in, built before the data so the first v2
month cannot be quietly appended to the old series.

---

## `INDEX_LICENSE=restricted` — quotation, not republication

**What it does:** narrows the grant in `LICENSE.txt` **and** in the three
on-page places that also state it (the methodology page's "Use and citation",
the note under the download buttons, the footer on every research page). All
four move together — the broadest wording anywhere is the one a reader relies
on, so narrowing three of four narrows nothing.

**The narrowed wording, as it ships in `LICENSE.txt`:**

> You may quote these indicators — individual figures and short extracts — in
> journalism, research, analysis, and commentary, with attribution: "Source:
> ShouldISellYet (shouldisellyet.com)". Republication is NOT granted: these
> files, and the series they contain, may not be reproduced in whole or in
> substantial part, mirrored, re-hosted, or included in another publication's
> own data offering. Quotation with attribution needs no further permission;
> anything beyond quotation needs ours, in writing —
> press@shouldisellyet.com.

**What it does not do:** it does not loosen anything that is already
restricted. The existing limits — no redistribution as a dataset, no competing
data product, no rights granted in any third party's underlying data — ride in
the paragraph below the grant and apply in both widths. It also says nothing
about past releases already downloaded under the wider terms.

---

## What none of this covers

Deliberately out of scope, and each needs a decision or an edit elsewhere:

- **Outbound copy.** `pipeline/growth_digest.py` (the monthly journalist mail)
  and `pipeline/marketing_tasks.py` (the marketing queue) read the research
  JSON directly and quote the index value. They do not consult these flags, so
  a paused or truncated index would still be pitched by email. Those files
  belong to another workstream; the fix is one `RS.publishes_month()` check in
  each.
- **`web/press.html`**, hand-maintained, currently offers "the full index
  history" for download. Under `paused` or `truncated` that sentence stops
  being true.
- **Per-ZIP readings.** Untouched here. Those are governed by
  `pipeline/data_pause.py`.
- **The mixed-lineage question.** The v2 danger lines were themselves
  calibrated against Redfin-derived data (`DERIVED_USE_INVENTORY.md`), so
  every live reading is mixed-lineage. No mode in this document changes that,
  and none of them should be read as claiming otherwise.

## Checking it yourself

```
python3 pipeline/build_research.py                          # full (default)
INDEX_MODE=truncated python3 pipeline/build_research.py     # + INDEX_CUTOFF=YYYY-MM
INDEX_MODE=paused    python3 pipeline/build_research.py
INDEX_LICENSE=restricted python3 pipeline/build_research.py
python3 -m pytest pipeline/test_index_options.py -q
```
