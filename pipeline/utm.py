"""
ShouldISellYet — marketing UTM strings. One module, one shape.

ONE STRING, THREE JOBS (decided 2026-08-10): a task's campaign token is its
`dedupe_key`, its `utm_campaign`, and its asset filename stem. The token is
deterministic from the TRIGGERING FACT — a data month, a metro code, a
receipt uuid — never from a counter or a clock, so a re-run of the generator
mints byte-identical tokens and the on_conflict upsert stays a no-op.

THE SLUG CONTRACT. Every token must match SLUG_RE, which is byte-identical
to the utm_campaign checks on public.events and public.marketing_tasks
(supabase/schema-v23.sql) and to the capture regex in web/track.js /
supabase/functions/track/index.ts. Four surfaces, one shape — change one,
change all four in the same commit, or posted links silently stop counting.

utm_source stays the CHANNEL label ('ig' | 'x' | 'fb' | 'nextdoor' |
'press') so the admin funnel's existing By-channel read keeps working;
utm_campaign carries the token and is the nightly performance join key
(marketing_perf_refresh). utm_medium is link hygiene only ('social' or
'email') and carries no attribution weight.
"""

import json
import re
from pathlib import Path

SITE = "https://shouldisellyet.com"

# Keep byte-identical to the utm_campaign checks in supabase/schema-v23.sql
# and the capture regexes in web/track.js + supabase/functions/track/index.ts.
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,59}$")

# The token scheme, one line per triage rule (contract §5.0).
#   {period}      data month 'YYYY-MM' (zip_velocity.period convention)
#   {ws}          the Sunday week-start date the task fills (marketing weeks
#                 are Sunday-based ET — see marketing_week_start in v23)
#   {uuid}        press_corroboration.id, in full (36 chars; token = 47) —
#                 one receipt mints one task in its lifetime, ever
#   {rate_period} the rate stamp the burst was measured against
SCHEME = {
    "record":     "mq-{period}-record-us",
    "contrarian": "mq-{period}-contrarian-us",
    "flip":       "mq-{period}-flip-{cbsa}",
    "receipt":    "mq-receipt-{uuid}",
    "geo":        "mq-{period}-geo-{zip}",
    "evergreen":  "mq-{ws}-ever-{case_id}",
    "burst":      "mq-burst-{rate_period}-{ws}",
    "pitch":      "mq-{period}-pitch-{batch_slug}",
}


def slug(s):
    """Lower-case slug of an arbitrary string (batch names, case ids).
    Anything outside [a-z0-9_-] collapses to a single hyphen."""
    s = re.sub(r"[^a-z0-9_-]+", "-", str(s).lower()).strip("-")
    return s[:60]


def token(kind, **parts):
    """Mint the token for one triage rule. Raises on a malformed result —
    better to drop a candidate loudly in the generator than to POST a row
    the utm_campaign check would refuse anyway."""
    t = SCHEME[kind].format(**{k: slug(v) for k, v in parts.items()})
    if not SLUG_RE.match(t):
        raise ValueError(f"token violates the slug contract: {t!r}")
    return t


# marketing_tasks.channel value -> utm_source label. 'nextdoor_naomi' is the
# channel's internal name; the funnel label stays the network's ('nextdoor').
# 'press' is not a channel — it is the source label for pitch-email links
# (channel NULL on the row), and the one case where utm_medium is 'email'.
SOURCE = {"ig": "ig", "x": "x", "fb": "fb",
          "nextdoor_naomi": "nextdoor", "press": "press"}


def utm_url(channel, tok, target="/"):
    """The tracked link for one task.

    target is the DEEP destination — /metro/{slug}/, /research/{yyyy-mm}/,
    /zip/{zip}/ — and defaults to the homepage only so an unmigrated caller
    still produces a valid URL. A post that lands on the homepage throws its
    own click away: someone who tapped a sentence about Grand Rapids arrives
    somewhere that does not mention Grand Rapids. lint_caption() refuses a
    homepage target, so the default cannot ship by accident.
    """
    if not SLUG_RE.match(tok):
        raise ValueError(f"utm_url given a non-slug token: {tok!r}")
    if not target.startswith("/") or "?" in target or "#" in target:
        raise ValueError(f"utm_url given a bad target: {target!r}")
    medium = "email" if channel == "press" else "social"
    return (f"{SITE}{target}?utm_source={SOURCE[channel]}"
            f"&utm_medium={medium}&utm_campaign={tok}")


def metro_slug(cbsa):
    """CBSA code -> /metro/{slug}/, or None when that metro has no page.

    Reads the map build_metro.py commits, so a link can only point at a page
    that was actually generated — the lint proves the destination exists
    rather than trusting a slug rule to agree with the builder.
    """
    global _SLUGS
    if _SLUGS is None:
        p = Path(__file__).parent / "data" / "metro_slugs.json"
        try:
            _SLUGS = {v: k for k, v in json.loads(p.read_text()).items()}
        except Exception:
            _SLUGS = {}
    s = _SLUGS.get(str(cbsa or ""))
    return f"/metro/{s}/" if s else None


_SLUGS = None


def metro_tag(cbsa_name):
    """'Austin-Round Rock-San Marcos, TX' -> '#AustinTX'. Deterministic —
    first city word of the CBSA title plus its first state code. Used by the
    per-channel hashtags in marketing_tasks.py (and post_pack.py's copy of
    the rendered line comes from the stored row, never re-derived)."""
    city = re.sub(r"[^A-Za-z]", "", cbsa_name.split(",")[0].split("-")[0])
    st = cbsa_name.split(",")[-1].strip().split("-")[0][:2]
    return f"#{city}{st}"
