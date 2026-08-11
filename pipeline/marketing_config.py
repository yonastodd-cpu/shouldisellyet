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
# SET 2026-08-10 FOR THE 2026-06 DATA MONTH. This is a claim about what the
# COVERAGE says, not about what the market is doing or what we believe — the
# rule exists to find the gap between the two. Re-read it before each data
# month and change or clear it; a stale narrative is worse than none, which is
# why "period" has to match or the rule sits out on its own.
NARRATIVE = {
    "text": "housing-crash coverage dominating the national headlines",
    "period": "2026-06",
    "stance": "bearish",
}

# The gap only exists when the data disagrees with the stance:
CONTRARIAN_CALM_WSI = 20.0   # bearish narrative + WSI below this = gap
CONTRARIAN_HOT_WSI = 10.0    # bullish narrative + WSI above this = gap

# ——— Publish guards for the queue's copy ———
# A year-over-year median move larger than this is treated as a MIX SHIFT
# (different homes sold), not a market move, and the angle is dropped rather
# than posted. Set from the failure that produced it: 22044 printed "+193.0%"
# off 36 sales because its median went 290k → 855k. A real ZIP-level housing
# market does not appreciate 40% in a year; a basket of houses instead of
# condos does. The operator digest keeps showing these — a strange number is
# informative to a human reading in context. Only the PUBLIC queue drops them.
MAX_PLAUSIBLE_SPY = 0.40

# ——— Big-metro story rule ———
# WHY THIS IS NOT A 25% CROSSING ANY MORE (changed 2026-08-10).
# The rule used to fire when a top-30 metro's deteriorating share crossed 25%
# upward. Checked against the first real queue, it fired ZERO times and could
# not have fired at all: every one of the 25 metros on the gathering list was
# already between 65.7% and 83.3% deteriorating, and had been the month
# before. A threshold every candidate cleared years ago is not a filter, it is
# an off switch — and it was the reason the queue held nothing but tier-4
# filler while the actual news went unposted.
#
# The signal that IS live is velocity.py's own `surge` flag: a metro entering
# the gathering top-10 for the first time in six months. That is genuinely new
# information, computed upstream, and it does not need a hand-set threshold to
# stay meaningful as the market moves. BIG_STORY_MIN_SHARE is a floor, not the
# trigger — it only stops a surge into a mild metro from being called a story.
BIG_METRO_COUNT = 30       # "top-30" = most scored ZIPs on the gathering list
BIG_STORY_MIN_SHARE = 50.0 # a surging metro below this is not yet a story
BIG_STORY_MIN_ZIPS = 20    # and one too small to generalise from is not either

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
# EXACTLY TWO, EVERYWHERE THEY APPEAR: #housingmarket plus one metro tag.
# Four tags read as reach-chasing and are the single clearest tell that a post
# came from a content pipeline rather than a newsroom. Cut from four on
# 2026-08-10; MAX_HASHTAGS lints the result so this cannot creep back.
HASHTAGS = {
    "ig": ("#housingmarket",),
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
# The voice is a wire-service data journalist: neutral, declarative, present
# tense. The data is surprising on its own; an adjective that tries to make it
# surprising is admitting it is not. Everything here is checked against the
# rendered CAPTION (the string that gets pasted), which also catches
# operator-entered narrative text riding in.
HYPE = ("crash", "collapse", "bubble", "plummet", "soar", "skyrocket",
        "alarming", "brace", "red alert", "guarantee", "will fall",
        "act now", "before it's too late", "you need to know",
        "warning signs are building")

# ——— Caption lint ———
# X is not a premium account (X_PREMIUM False), so a post there is 280 chars
# INCLUDING the link and the tags. The long caption is not truncatable into
# that, so the generator writes two captions from the same facts and the
# channel picks. Flip this and X starts using the long one.
X_PREMIUM = False
CAPTION_MAX_SHORT = 280        # X, non-premium
CAPTION_RANGE_LONG = (400, 900)  # IG/FB — the skeleton with room to breathe
MAX_NUMBERS_SHORT = 3          # one hero number, at most two supporting
MAX_NUMBERS_LONG = 3
MAX_HASHTAGS = 2               # #housingmarket + one metro tag, end of post
# "danger line" is ours and worth owning, but it means nothing to a stranger.
# Every caption that uses it must ground it in plain words on first use; the
# linter checks for one of these follow-ons rather than a fixed sentence, so
# each rule can phrase its own definition from the metric it actually moved.
# Checked in the ~90 characters FOLLOWING the term, so a rule can phrase the
# definition from whichever metric actually moved instead of reciting a fixed
# sentence. What is required is that a definition follows closely, not that it
# is worded a particular way.
DANGER_LINE_GLOSSES = ("the level where", "the point where", "where ")
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
