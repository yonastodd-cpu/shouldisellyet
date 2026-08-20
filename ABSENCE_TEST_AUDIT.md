# Absence-test coverage — matrix and the gaps that produced it

Prompt C, 2026-08-19. The design principle, learned expensively: **enumerate
SURFACES and assert absence everywhere, never enumerate PAGES and assert the
presence of a notice.**

Nine surfaces were found publishing withdrawn figures over a single day. Not
one was found by a test. Each was found by someone looking, and the pattern was
identical every time — the pause was applied where somebody remembered to apply
it.

## The nine, and what each proved

| # | Surface | Why the existing tests missed it |
|---|---|---|
| 1 | ZIP page body prose | The pause branch cleared title, meta, OG, dials and FAQ **around** the facts list without clearing it. Tests asserted the notice was present, never that figures were absent. |
| 2 | State hub rows | The hub builds its own rows in `main()`, outside the branch that blanks a page. |
| 3 | Share stubs `/s/{zip}` | No pause check existed at all. |
| 4 | `og:image:alt` on those stubs | Interpolated inline in the template rather than assigned in the branch — **missed by the first pass of its own fix.** |
| 5 | Four case files | Reachable, downloaded by every homepage visit, **linked from a fetch rather than a page**. |
| 6 | ~3,400 per-ZIP OG images | **Linked from nowhere.** Pages had pointed at the brand card since day one; the images kept generating and kept deploying. |
| 7 | 609 metro pages | A separate generator with its own population, never pause-gated, publishing per-ZIP ratings, price columns, and counts that were false ("0 of 83 rate HOLD"). |
| 8 | Story page | Three SVG charts of a monthly series plus prose figures. The chart **is** the page, so it could not be blanked in place. |
| 9 | Homepage figure and prose | A chip, an `alt` attribute, a caption, and body text naming the vendor. An `onerror` hid it **client-side** — the markup still went to anything reading HTML. |

**Six of the nine were reachable but linked from nowhere.** A test that renders
pages and inspects them is structurally incapable of finding those, which is why
artifact surfaces are enumerated and checked separately from page surfaces.

**The ninth also hid a crash.** The ZIP lookup threw a `TypeError` inside a
`setTimeout`, so a visitor saw the spinner vanish and nothing replace it. Unit
tests passed, the page-count gate passed, `curl` returned 200 on every URL —
none of them execute JavaScript.

## The matrix

`pipeline/surfaces.py` holds the list. `test_provisioning.py` asserts every
entry maps to a test that exists, so an entry added without one fails the build.

| Surface | Kind | Asserted by |
|---|---|---|
| zip page body | page | `test_pause_leaks::test_paused_zip_page_publishes_no_prose_figures` |
| zip page head/meta/OG | page | `test_pause_leaks::test_paused_zip_page_metadata_carries_no_verdict` |
| zip page JSON-LD | page | `test_data_pause::test_a_paused_zip_page_leaks_no_verdict_anywhere` |
| state hub rows | page | `test_pause_leaks::test_paused_state_hub_lists_no_verdict_words` |
| share stub | page | `test_pause_leaks::test_paused_share_stub_has_no_verdict_or_metric` |
| share stub og:image:alt | page | same test — extended after it was missed once |
| metro page rows | page | `test_artifact_leaks::test_metro_membership_uses_the_wider_scored_population` |
| story page | page | `test_artifact_leaks::test_build_reads_case_data_from_outside_the_artifact` |
| per-ZIP OG images | artifact | `test_artifact_leaks::test_og_directory_holds_no_per_zip_card_while_paused` |
| case study files | artifact | `test_artifact_leaks::test_no_purged_case_file_is_in_the_artifact` |
| case index.json | artifact | `test_artifact_leaks::test_the_case_index_that_remains_is_derived_only` |
| bulk `/data/zips` | artifact | `test_provisioning::test_unreleased_records_carry_only_a_state` |
| purge manifest files | artifact | `test_artifact_leaks::test_purge_manifest_lists_every_moved_file` |
| reading endpoint | artifact | `test_market_reading_fn::test_every_selected_field_is_one_we_intend_to_publish` |
| **homepage body + alt** | **runtime** | `scripts/smoke-browser.mjs` |
| **zip lookup renders** | **runtime** | `scripts/smoke-browser.mjs` |

## The browser gate

`scripts/smoke-browser.mjs` runs the built site in Chromium and asserts what
static checks cannot: that a ZIP lookup **answers** — verdict card or waitlist
card, either is fine, neither is not — with no uncaught exception.

Proven against the real bug: the crash was reintroduced locally and the smoke
test failed with exactly `verdict=none waitlist=none` and
`TypeError: Cannot read properties of undefined (reading 'soft')`. Restored, it
passes 16/16 against production and against a local build.

It runs in CI at step 23, **before** the artifact upload at step 24, so a
browser failure blocks publication.

### Disclosure is not a leak

Every page states the danger lines the engine scores against — "the
year-over-year price trend (−2%)". Those are our published thresholds, identical
on every page, and stating them is the product: a reader is told the rule before
the result. The smoke test subtracts those literals before scanning, so what
remains that looks like a figure is the ZIP's own. This distinction bit three
separate tests during this work, each fixed by narrowing the assertion rather
than weakening it.

### Third-party noise is not a defect

The analytics beacon 400s from a localhost origin because the function pins CORS
to the site. Counting that as a failure would make the smoke test fail on every
local run and train everyone to ignore it. Uncaught exceptions are captured
separately and are never filtered.

## Still open

- **Per-`dataStatus` assertions for released ZIPs.** Nothing is released, so
  `ok` and `insufficient_data` cannot be exercised end to end yet. The smoke
  test asserts the paused path only. Extend it with Tranche 1, and assert that
  a released page's figures come from the reading path and that its
  `last-updated` date renders.
- **A post-deploy run.** The gate tests the build before upload, not the
  deployed URL. Those are the same bytes today, but a CDN or Pages
  configuration failure would not be caught. A second invocation against
  `https://shouldisellyet.com` after `deploy-pages` would close it.
- **The story renderer is untested.** Its 11 tests skip because their input is
  private data. Harmless while the page is a static notice; it ships untested
  the moment it un-pauses.
- **A methodology mismatch, unrelated to leaks but found here.** ZIP pages
  disclose the v1 thresholds ("+40% year over year"); the recalibrated engine
  uses +10%. Copy and engine must agree before Tranche 1 — Prompt 5's job.
