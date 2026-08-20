"""THE SURFACE LIST. Every place this site can publish a figure.

ADD TO THIS LIST when you add a page template, a metadata field, a generated
asset, or any file that ships inside web/. A meta-test asserts each entry maps
to a test that asserts ABSENCE there, so an entry added without a test fails
the build — which is the point.

WHY A LIST AT ALL. Nine surfaces were found publishing withdrawn figures, one
at a time, over a single day. Not one was found by a test; each was found by
someone looking. The pattern was always the same — the pause was applied where
somebody remembered to apply it — and the fix for that is not more care, it is
an enumeration that fails when it is incomplete.

Six of the nine were reachable but linked from NOWHERE: case files, preview
images, a bulk JSON endpoint. A test that renders pages and checks them cannot
see those, which is why `artifact` surfaces are listed separately from `page`
surfaces and checked differently.

One of the nine could only be caught by executing the page: the ZIP lookup
threw inside a timer and rendered nothing while every static check passed.
Those are marked runtime.
"""

# kind: "page"     — rendered HTML, checked by asserting on built output
#       "artifact" — a file that ships in web/ whether or not anything links it
#       "runtime"  — only a browser executing the page can see a failure
SURFACES = [
    ("zip page body",        "page",     "test_pause_leaks.py::test_paused_zip_page_publishes_no_prose_figures"),
    ("zip page head/meta/OG", "page",    "test_pause_leaks.py::test_paused_zip_page_metadata_carries_no_verdict"),
    ("zip page JSON-LD",     "page",     "test_data_pause.py::test_a_paused_zip_page_leaks_no_verdict_anywhere"),
    ("state hub rows",       "page",     "test_pause_leaks.py::test_paused_state_hub_lists_no_verdict_words"),
    ("share stub /s/{zip}",  "page",     "test_pause_leaks.py::test_paused_share_stub_has_no_verdict_or_metric"),
    ("share stub og:image:alt", "page",  "test_pause_leaks.py::test_paused_share_stub_has_no_verdict_or_metric"),
    ("metro page rows",      "page",     "test_artifact_leaks.py::test_metro_membership_uses_the_wider_scored_population"),
    ("story page",           "page",     "test_artifact_leaks.py::test_build_reads_case_data_from_outside_the_artifact"),
    ("homepage body + alt",  "runtime",  "scripts/smoke-browser.mjs"),
    ("per-ZIP OG images",    "artifact", "test_artifact_leaks.py::test_og_directory_holds_no_per_zip_card_while_paused"),
    ("case study files",     "artifact", "test_artifact_leaks.py::test_no_purged_case_file_is_in_the_artifact"),
    ("case index.json",      "artifact", "test_artifact_leaks.py::test_the_case_index_that_remains_is_derived_only"),
    ("bulk /data/zips",      "artifact", "test_provisioning.py::test_unreleased_records_carry_only_a_state"),
    ("purge manifest files", "artifact", "test_artifact_leaks.py::test_purge_manifest_lists_every_moved_file"),
    ("reading endpoint",     "artifact", "test_market_reading_fn.py::test_every_selected_field_is_one_we_intend_to_publish"),
    ("zip page stamp/credit", "page",    "test_pause_leaks.py::test_paused_zip_page_credits_no_vendor"),
    ("markets index /zip/",  "page",     "test_data_pause.py::test_only_released_zips_are_submitted_for_indexing"),
    ("zip lookup renders",   "runtime",  "scripts/smoke-browser.mjs"),
    # The two committed static pages. No generator writes them, so no pipeline
    # change ever reached them and the pause never applied: while every ZIP
    # page said its reading was being refreshed, /report.html served a WATCH
    # for a named ZIP with the full withdrawn dial set, and /press.html served
    # the national verdict mix. Both were in the submitted sitemap — two of its
    # three URLs — and report.html was advertised in llms.txt as showing "a
    # real ZIP". Found on 2026-08-20, after ten other surfaces had been closed.
    ("sample report page",   "page",     "test_pause_leaks.py::test_the_sample_report_publishes_no_reading"),
    ("press kit page",       "page",     "test_pause_leaks.py::test_the_press_kit_publishes_no_withdrawn_figure"),
    ("sample report runtime", "runtime", "scripts/smoke-browser.mjs"),
]
