#!/usr/bin/env python3
"""VELOCITY_ENABLED — the approach-velocity panel is off until it is rebuilt.

WHY THIS FILE EXISTS. `public.zip_velocity` is frozen vendor-derived output.
schema-v34.sql added its `source` column with `not null default 'redfin'`, and
every row still reads that; the job that would refresh it
(`pipeline/upsert_velocity.py`) is gated in CI on a `changed` flag that Phase 0
forces to false, so nothing has been written to the table since ingestion
stopped at 2026-08-14T13:53:43Z (`data_pause.INGESTION_STOPPED_UTC`).

Two live code paths still read that table, and one of them is the worst class
of exposure in DERIVED_USE_INVENTORY.md — item C10. `verify-access` joins
`zip_velocity` on every valid purchase token and `web/my-report.html` renders
the result as "Approach velocity — the distance to each danger line". That is
not a figure shown to a passing visitor: it is the withdrawn vendor's
measurements SOLD, as a feature, to a paying customer, right now.

WHY A FLAG AND NOT A `source` PREDICATE. The register's suggested lever was to
add `&source=eq.rentcast` to the query. One predicate is not enough:

  * `upsert_velocity.py` writes no `source` key at all, so rebuilt rows would
    take the column DEFAULT — which is `'redfin'`. An `eq.rentcast` filter
    would then match nothing forever while looking, in review and in the
    diff, exactly like a fix. A filter whose failure mode is silent success
    is the wrong shape for this.
  * The predicate has to be repeated, correctly, in every reader. There are
    three readers today, in two languages, owned by different parts of the
    build.
  * It writes the outgoing vendor's name into the paid product's data path.
    The decision here is "this panel does not serve until it is rebuilt",
    which is a posture, not a vendor string.

So the decision lives here as one boolean and the readers ask it. This is
figures_switch.py's pattern rather than data_pause.py's for the same reason
figures_switch gives: this is a licence/lineage posture that applies to every
ZIP at once, not a per-ZIP release question.

TO RE-ENABLE, IN THIS ORDER:
  1. Teach `upsert_velocity.py` to write an explicit `source` for the rows it
     upserts. Until it does, the column default re-tags rebuilt data as the
     vendor it did not come from, and step 3 republishes the frozen rows.
  2. Refresh the table from the new engine.
  3. Set VELOCITY_ENABLED = True here AND in the two mirrors below, in one
     change. pipeline/test_velocity_switch.py fails until all three agree —
     that test is the only thing making this one switch instead of three.

WHAT THIS SWITCH DOES
  * `supabase/functions/verify-access/index.ts` does not READ `zip_velocity`
    and returns `velocity: null`. The query is GUARDED, NOT DELETED: the
    table, its index and the whole code path survive intact for the rebuild.
    Nothing stored is touched or modified — LEGAL_HOLD.md.
  * `web/my-report.html` keeps the section, its heading and its place in the
    report's numbering, and renders NOTICE_TITLE / NOTICE_BODY where the rows,
    the state sentence, the traces and the score used to be. The layout does
    not collapse: a paid report that silently loses a section it advertised is
    a worse answer to the customer than one that says what happened.
  * The velocity ALERT toggle goes with it. An alert is a standing promise to
    email a state transition computed from the same suppressed rows, so
    leaving the toggle live would keep the panel's data path selling itself
    after the panel stopped rendering.

WHAT THIS SWITCH DOES NOT REACH. Recorded here rather than discovered during
an incident. Each is a separate owner's file and none is guarded by this flag:

  * `supabase/functions/save-watch/index.ts:118` — a SECOND live read of
    `zip_velocity`, used to baseline a velocity watch at save time. Suppressed
    here only indirectly, because my-report no longer offers the toggle; a
    direct POST still reaches it.
  * `pipeline/check_watches.py:379` — reads `zip_velocity` for every existing
    velocity watch and can send the alert email at B36. Dormant only because
    the workflow forces `changed=false`; re-enabling ingestion re-arms it.
  * `web/data/velocity-aggregates.json` (register B19) and
    `pipeline/velocity/velocity-{month}.json` (B6) — the public/press
    aggregate layer, a different file set with its own consumers.

WHY THE NOTICE READS THE WAY IT DOES. It says the panel is being rebuilt on a
new data source and that it will return. It does not name the outgoing vendor
— a customer-facing notice is not the place to litigate a data licence — and
it does not say "shortly" or "check back", because the copy it REPLACES said
exactly that. `renderVelocity`'s existing empty-row branch reads "computed on
the next data refresh — check back shortly", which is true of an unseeded ZIP
and false here: this is a rebuild, not a late job, and telling a paying
customer to check back tomorrow for a number that is not coming is the
specific failure this wording prevents.

Run: python3 -m pytest pipeline/test_velocity_switch.py -q
"""

# ————— the switch —————
#
# A module attribute, not an environment read, for data_pause.py's reason: the
# two mirrors below cannot read an environment either, and a flag whose copies
# are set three different ways is a flag that gets flipped in two of them.
# Tests monkeypatch this attribute; read it through shows_velocity() rather
# than importing the name, so a monkeypatch reaches every caller.
VELOCITY_ENABLED = False

# The identifier the mirrors declare. Named once here so the sync test
# looks for one string instead of two hand-typed ones.
JS_CONST = "VELOCITY_ENABLED"

# The mirrors, repo-relative — client/edge files that cannot import this
# module. web/my-report.html LEFT this list on 2026-08-28: the report's
# approach-velocity panel was rebuilt to compute client-side from the
# record's own current-basis history (velFromHistory), so the page no longer
# has a zip_velocity renderer to guard — it never reads the verify-access
# velocity payload at all, which test_velocity_switch now pins directly.
# verify-access keeps the guard: the frozen table stays unread on the paid
# endpoint until a genuine zip_velocity rebuild flips this switch.
MIRRORS = (
    "supabase/functions/verify-access/index.ts",
)

# Reader-facing. See "WHY THE NOTICE READS THE WAY IT DOES" above.
NOTICE_TITLE = "This section is being rebuilt"
NOTICE_BODY = ("Approach velocity is being rebuilt on a new data source and "
               "will return to your report. Everything else here is unaffected.")

# Wording that must NOT appear in the notice, each pinned by the test because
# each was a live mistake available to make: the vendor name (never named on a
# serving surface), and the lateness words carried over from the unseeded-ZIP
# copy this notice displaces.
NOTICE_FORBIDDEN = ("redfin", "check back", "shortly", "next data refresh")


def shows_velocity():
    """May any approach-velocity number be read, served or rendered?

    Takes no arguments, deliberately — figures_switch.shows_figures()'s
    reasoning applies unchanged. `zip_velocity` is frozen in its entirety, so
    a per-ZIP variant would imply a per-ZIP release question that does not
    exist here. If one ever does, that is a different function.
    """
    return VELOCITY_ENABLED


def notice_html(css_class="rebuild-notice"):
    """The reader-facing block that stands in for the panel. Empty when live."""
    if VELOCITY_ENABLED:
        return ""
    return (f'<div class="{css_class}" role="status">'
            f'<b>{NOTICE_TITLE}.</b> {NOTICE_BODY}</div>')
