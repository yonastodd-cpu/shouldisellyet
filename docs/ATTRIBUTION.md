# Attribution rules

**Read this before editing any source citation, the sources strip, or the
"built on the same public market data" line.** These rules exist for
compliance *and* for trust: we credit where numbers come from, and we never
imply a relationship that does not exist.

## The governing rule

> Source attribution uses **data grammar**, never **brand grammar.**

We name where the numbers come from. We never imply partnership,
endorsement, sponsorship, or any official relationship with Redfin or any
other source. No source name or logo may appear adjacent to the
ShouldISellYet logo, in the header/brand area, or in a "powered by"
construction.

## Redfin — the exact citation

```
Data provided by Redfin, a national real estate brokerage
```

- **Exactly once per surface, linked to <https://www.redfin.com>.** Required
  on every page or email that displays Redfin-derived market data, and
  present nowhere else on it. A second copy is not extra compliance — it is
  the duplicate this rule exists to prevent.
- The wording is verbatim. Do not paraphrase it to "Data from Redfin",
  "Redfin data", "Source: Redfin", "from public Redfin data", or anything
  else.
- **Text only.** No Redfin logo, wordmark, or brand image — the repo
  contains none, and none may be added.
- This wording must not be edited without re-checking the Redfin Data
  Center's current citation guidance. If their terms change, change this
  file in the same commit.

### Where it lives — one per surface

Where a page has a stamp beside its data, the stamp carries the citation and
the footer carries none. Where there is no stamp, the footer carries it.

| Surface | Placement | File |
| --- | --- | --- |
| Homepage | results stamp (runtime) | `web/index.html` → `citeHTML()` |
| Personal report | report stamp (runtime) | `web/my-report.html` → `citeHTML()` |
| Sample report | report stamp | `web/report.html` |
| Press page | body text | `web/press.html` |
| Generated ZIP page | stamp (`CITE`; footer passes `cite=""`) | `pipeline/build_pages.py` |
| State hub / markets index | footer (no stamp on these) | `pipeline/build_pages.py` |
| Verdict-change alert email | footer line | `pipeline/notify_changes.py` |
| Growth Ops digest | footer line | `pipeline/growth_digest.py` |
| Data layer (plain text, no markup) | — | `pipeline/fetch_data.py` → `meta.attribution` |

**Carrying none, on purpose** — no Redfin-derived market data is displayed:
`subscribe.html`, `partners.html`, `privacy.html`, `refunds.html`, the
`/s/{zip}` share stubs, and both `stripe-webhook` purchase emails.

`terms.html` names Redfin once inside a methodology clause ("Ratings are
computed from public market data (including data from Redfin…)"). That is
contract text describing how the product works, not an attribution, so it
stays and is exempt from the one-per-surface count.

The pipeline writes the citation as **plain text** into
`web/data/meta.json`. A data file should not carry markup, so the two render
sites call `citeHTML()` to add the required link. If you add a third render
site, use the same helper — don't hand-write the anchor.

**Pages that show no source-derived numbers do not carry the citation.**
Adding it there would be noise, not compliance — and it dilutes the credit
on the pages that genuinely need it.

## Other sources

The sources strip on the homepage lists **only feeds actually wired into
the product today**. If a source is removed from the pipeline, remove it
from the strip in the same commit; if one is added, add it.

Currently: Redfin Data Center · Realtor.com residential listings ·
Federal Housing Finance Agency (FHFA) · Freddie Mac Primary Mortgage Market
Survey.

Note on the mortgage rate: the publisher is **Freddie Mac (PMMS)**. FRED is
only a fallback *transport* for that same series — crediting FRED as the
source would name the wrong publisher.

The strip carries this line verbatim:

> We compute our verdicts from public market data. No source sponsors,
> endorses, or partners with this site.

## The one marketing line

> Built on the same public data the industry's economists publish —
> Redfin, Realtor.com, FHFA — recomputed for your ZIP and your numbers.

- **One placement only** (pricing section). Do not repeat it elsewhere.
- It is a claim about *data*, not about a relationship.
- Never shorten it to "powered by Redfin", "with Redfin", or similar.
- Never place it under or beside our own logo.

## Banned constructions (anywhere in the repo)

"powered by", "in partnership with", "partnered with", "official partner",
"official data source", "endorsed by", "sponsored by" — in copy, alt text,
meta tags, structured data, README badges, or commit-visible comments,
when referring to a data source.

(Unrelated and fine: NTRealty is a genuinely affiliated brokerage of this
site, and that relationship is disclosed in `terms.html`. That's a real
disclosure about our own business, not a data-source claim.)

## Operator task — not automated, and it cannot be

Keep a compliance record of the terms as published: save an
[archive.org](https://web.archive.org/) capture of the Redfin Data Center
page and keep a dated screenshot alongside this `docs/` folder. Redo it
whenever their terms page changes.

**This genuinely can't be automated.** Redfin rate-limits datacenter IPs —
the refresh workflow's attempt gets a bot wall ("Are You a Robot?", HTTP
429), not the page. The workflow checks the response content and refuses to
save a block page as if it were a record, warning instead. So the only
reliable capture is a human on a normal browser connection.
