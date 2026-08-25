# Go-live clearance report

**Certified commit `36f54ac` (`36f54ac3e7440d1343b29fbaecfdb6ca1be985ea`) · 2026-08-25T18:09:44Z · deployed and verified in production.**
**Reindexing NOT performed — held at the eyeball checkpoint.**

## Fix list

| # | Item | Prior state | Action | Evidence |
|---|---|---|---|---|
| 1 | Velocity panel | **Live exposure.** `verify-access` read `zip_velocity` with no filter or flag; all rows carry the prior vendor's tag. Served to paying customers on every valid token. | `VELOCITY_ENABLED=false` across verify-access, my-report, save-watch, check_watches, upsert_velocity. Table untouched. | Gate C |
| 2 | Watch alerts | **Regression, worse than HEAD.** The basis guard's inference was inverted — absence of `basis` is the state of the entire live book, not a fresh save — so every legacy watch would have been stamped current and scaled across bases. | Defaults to `LEGACY_BASIS`; unstamped watches rebaseline and notify. | Auditor's repro: email now shows $150,000, not $350,000 |
| 3 | Figures kill switch | Reached generated pages only; docstring overclaimed "any surface". | Extended to the endpoint and report pages; left **OFF**. Docstring corrected. | `test_figures_switch` |
| 4 | Warning-Sign Index | Published a 173-month prior-vendor series plus chart, map, aggregates and 51 per-state paragraphs. | **Fully dark.** Truncation was impossible — every month on record is prior-vendor, so truncating yields zero points. | Gate A |
| 5 | Prior-vendor credits | Two linked research credits plus seven other mentions. Disclosure prose **did not exist**. | Name removed everywhere; disclosure **added** to methodology §7. | `test_basis_disclosure` (both directions) |
| 6 | Case panel / backtest ladder | Precomputed from prior-vendor case files. | Suppressed; ladder absent. | Gate A, E |
| 7 | Sample report | — | "no purchased report is affected" already absent; CTAs honest. | Gate B |
| 8 | Strings and counts | `33,000+` on homepage; vendor name outside methodology. | Counts render from one source: **5,000 / 22,874** identical on `/`, `/zip/`, `/press.html`. | Gate A, item-8 check |
| 9 | Research downloads | Aggregates published on a prior-vendor basis. | Withheld with everything else. History file and aggregates return **404**. | Gate A, D |

## Gates

| Gate | Result | Evidence |
|---|---|---|
| **A** Sitemap + filesystem crawl | **PASS** | 46,450 URLs discovered, 111 crawled, JS preflight 9 files — `clean` |
| **B** Authenticated / paid | **PASS** | `/report.html`, `/my-report.html` — no prior-vendor value in rendered output |
| **C** DB tripwire | **PASS** after a red | Every `zip_velocity` access guarded within its own function scope |
| **D** Build output vs purge manifest | **PASS** | No manifest path reachable; endpoint serves one ZIP per request |
| **E** OG / metadata, 20 pages | **PASS** | 20/20 clean in `<title>`, `<meta>`, JSON-LD |

Gate C went red first, on the velocity **writer**. Not waived: it writes no
`source` key while schema-v34 defaults to the prior vendor, so a later
`source=eq.rentcast` filter would have served nothing forever while looking
exactly like a fix. The gate's own method was also wrong — a fixed 400-character
lookback missed a guard sitting 888 characters earlier — and now parses function
scope instead.

## Suite

**585 passed, 3 skipped, 0 failed** at the certified commit. Thirteen contracts
re-pinned to the new behaviour; none relaxed. Two were made *stronger*: the
national percentile moved from flag-gated to refused unconditionally, and the
credit test became conditional so it still fails if a figure ever publishes
uncredited. Mutations verified on all three.

## Closing statement

**As of 2026-08-25T18:09:44Z, no prior-vendor-lineage figure is reachable on any surface;
private holdings preserved unchanged under LEGAL_HOLD.**

Verified against production, not the working tree, with comments, scripts and
stylesheets stripped — CSS class names like `.verdict-tag` are identifiers and
exempt, as is the FAQ phrase "a good time to sell".

## Deliberately deferred — counsel's, none blocking operation

- **Archive retention and deletion.** Held; no decision taken.
- **The current vendor's grant.** Three published instruments, one held. The Platform terms are still unobtained.
- **Purchaser notice.** Whether anyone who bought a report on the prior basis should be told.
- **Restoring the index history.** Possible if counsel clears it; the file is preserved and the mode is a flag.
- **Repository history.** Removing files from HEAD leaves them fetchable by commit reference. Same question as ticket #4688700.
