"""
ShouldISellYet — Marketing Queue configuration.

Everything an operator edits to steer the marketing queue lives here, so
pipeline/marketing_tasks.py never needs touching for a retarget. Read
docs/MARKETING.md before changing anything: the generator REFUSES rather
than over-schedules, so a cap typo silently shrinks the queue — each dropped
candidate prints a `REFUSED <dedupe_key> <reason>` line to the CI log.

THE CALENDAR IS NOT HERE, on purpose. Posting windows live in the DATABASE
(public.marketing_windows, supabase/schema-v23.sql §2) because three readers
must agree on them — this generator, the admin tab's reschedule picker, and
the marketing_tasks trigger. FALLBACK_WINDOWS below is a dry-run mirror of
the v23 seed and nothing more. There is no Naomi flag here either (decided
2026-08-10): a channel with zero rows in marketing_windows can never be
scheduled, so the windows table IS the off switch — turning nextdoor_naomi
on is a dated migration INSERT, never a config edit. See docs/MARKETING.md.

Shared thresholds are imported from growth_config, never duplicated:
RATE_BURST_POINTS has exactly one home.
"""

from growth_config import RATE_BURST_POINTS, is_dmv  # noqa: F401 — re-exported

# ——— The monthly narrative (contrarian-gap rule input) ———
# Set BOTH fields for each data month, or leave them empty. "period" must
# equal the period the refresh runs for ("2026-08"); empty or stale means the
# contrarian rule sits the month out with a loud stdout line — never a stale
# claim in a caption. Freshness is a contract, not a convention.
# Optional third key "stance": what the HEADLINES are saying, not what we
# think — "bearish" (crash-coverage dominating; the default when omitted) or
# "bullish" (boom/FOMO coverage dominating).
NARRATIVE = {"text": "", "period": ""}

# The gap only exists when the data disagrees with the stance:
CONTRARIAN_CALM_WSI = 20.0   # bearish narrative + WSI below this = gap
CONTRARIAN_HOT_WSI = 10.0    # bullish narrative + WSI above this = gap

# ——— Big-metro flip rule ———
BIG_METRO_COUNT = 30    # "top-30" = most scored ZIPs on the gathering list
BIG_FLIP_SHARE = 25.0   # share_det crossing this upward is the flip

# ——— Receipts ———
RECEIPT_LOOKBACK_DAYS = 35   # a receipt older than one cycle is stale news

# ——— Press pitches ———
# Each batch becomes ONE press_pitch task per research release (channel NULL
# — a pitch email is not a brand post). Empty list + no PRESS_LIST env means
# the rule prints a labelled gap and generates nothing: an operational gap,
# not a code gap. Emails are NOT stored here — the task carries the drafted
# email; the operator addresses and sends it by hand.
PRESS_OUTLET_BATCHES = []    # e.g. [{"slug": "national", "name": "National desks"}]

# ——— Scheduling ———
# Four Sunday-start ET weeks: the current one plus three. Raised from 2 on
# 2026-08-10 when the queue was first filled — two weeks is enough to keep a
# rolling schedule topped up once the queue is running, but the first fill
# wants a month on the board so the operator can see the shape of the rotation
# (and so an empty week shows up as an evergreen slot rather than as nothing).
HORIZON_WEEKS = 4
MIN_LEAD_HOURS = 2      # never plan a slot closer than this to the run

# Caps — MIRRORS of marketing_slot_conflict R2/R3 in supabase/schema-v23.sql.
# Python refuses first (REFUSED lines, row never written); the trigger is the
# backstop. Change the SQL, change these, in the same commit.
MAX_WEEKLY_PER_CHANNEL = 2
METRO_COOLDOWN_DAYS = 14

# ——— Burst play ———
# The threshold itself is growth_config.RATE_BURST_POINTS (imported above).
BURST_WINDOW_HOURS = 48
BURST_SLOT_TIMES_ET = ("09:00", "19:30")   # first instant inside the window

# ——— Hashtags (stored pre-rendered on the row; Copy copies verbatim) ———
HASHTAGS = {
    "ig": ("#housingmarket", "#realestate", "#homeselling", "#housingdata"),
    "x":  ("#housingmarket",),
    "fb": (),               # FB hashtags don't aid reach; keep captions clean
    "nextdoor_naomi": (),   # no hashtag culture on Nextdoor; reads as spam
}

# ——— Copy guards (generator-side refusals; exit stays 0) ———
# BANNED mirrors the marketing_tasks_no_affiliation_claim constraint in
# supabase/schema-v23.sql and docs/ATTRIBUTION.md "Banned constructions" —
# the DB refuses these at insert; the generator refuses them first so the
# row never leaves Python. Matched triple: this tuple, the SQL constraint,
# the ATTRIBUTION.md list.
BANNED = ("powered by", "in partnership with", "partnered with",
          "official partner", "official data source", "endorsed by",
          "sponsored by")
# HYPE: constructions that turn a smoke detector into a doom account. Checked
# on rendered CAPTIONS (the strings that get pasted into public channels) —
# which also protects against operator-entered narrative/quote text.
HYPE = ("crash", "collapse", "plummet", "guarantee", "will fall",
        "act now", "before it's too late")
# NAOMI_NEVER: Naomi Todd is a real, independent licensed agent with no
# corporate affiliation to this site (docs/ATTRIBUTION.md, correction dated
# 2026-08-08). Her name and company never appear in generated copy.
NAOMI_NEVER = ("naomi", "ntrealty", "samson properties")

# ——— Dry-run mirror of the v23 posting calendar ———
# KEEP IN SYNC with the seed INSERT in supabase/schema-v23.sql §2. The
# database is the rulebook — the generator fetches marketing_windows at run
# start; this constant exists only so --dry-run and no-env forks plan
# against the same calendar. test_windows_fallback_matches_seed parses the
# seed INSERT out of the SQL file and fails on any drift. dow: 0 = Sunday
# (Postgres extract(dow) and JS getDay() convention).
FALLBACK_WINDOWS = [
    {"channel": "ig", "dow": 0, "at_time": "19:30", "label": "Sunday anchor", "anchor": True},
    {"channel": "fb", "dow": 0, "at_time": "19:30", "label": "Sunday anchor", "anchor": True},
    {"channel": "x",  "dow": 0, "at_time": "19:30", "label": "Sunday anchor", "anchor": True},
    {"channel": "ig", "dow": 3, "at_time": "08:30", "label": "Wednesday morning", "anchor": False},
    {"channel": "fb", "dow": 3, "at_time": "08:30", "label": "Wednesday morning", "anchor": False},
    {"channel": "x",  "dow": 2, "at_time": "08:30", "label": "Tuesday morning", "anchor": False},
    {"channel": "x",  "dow": 3, "at_time": "08:30", "label": "Wednesday morning", "anchor": False},
]
