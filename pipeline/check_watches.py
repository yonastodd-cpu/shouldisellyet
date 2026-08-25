"""
ShouldISellYet — personal-number watch alerts.

Separate from notify_changes.py (which watches the ZIP-level HOLD/WATCH/ACT
verdict for everyone on the monitor plan). This watches a subscriber's OWN
numbers — walk-away number, equity, or lock-in cost — against a threshold
they set, using the calculation inputs they explicitly opted to save via the
save-watch edge function (see supabase/functions/save-watch/index.ts).

A subscriber can watch up to three metrics at once (one toggle per number on
the report), stored as a jsonb array in `subscribers.watches` — this module
evaluates every entry in that array independently.

BASIS. Every dollar metric here is the subscriber's own saved home value
carried forward by how the ZIP median has moved since they saved it. That
ratio only means something while numerator and denominator measure the same
quantity, and on 2026-08-14 they stopped: the old median is a closed-sale
figure, the new one an asking price (schema-v35 spells this out on
`market_stats.list_median_price`). So a watch now records the basis its
baseline was taken on, `scale_value()` REFUSES to divide across two bases
instead of returning a meaningless number, and a watch whose basis no longer
matches the reading is re-based onto the current one and the subscriber is
told — see `rebaseline_watch()` and `render_rebaseline_email()`.

Runs in the GitHub Action right after fetch_data.py, using the freshly
published web/data/. If Supabase/Resend secrets aren't configured, dry-runs
and never fails the pipeline — same convention as notify_changes.py.

Usage:
  python pipeline/check_watches.py --data web/data

Required env (GitHub Actions secrets, already used by notify_changes.py):
  SUPABASE_URL, SUPABASE_SERVICE_KEY, RESEND_API_KEY
Optional:
  ALERT_FROM  default: "ShouldISellYet <support@shouldisellyet.com>"
"""

import argparse
import data_pause as PAUSE
import velocity_switch as VELOCITY
from shard_layout import require_shards
import json
import os
import sys
import urllib.request
from pathlib import Path

SITE = "https://shouldisellyet.com"
METRIC_LABEL = {
    "walkaway": "walk-away number",
    "equity": "equity",
    "lockin": "lock-in cost",
    "rate": "market 30-year rate",
    "rategap": "rate gap (market vs. yours)",
    "gain": "estimated gain",
}

# Percent-valued metrics format as "6.25%" in emails, point-valued as
# "1.5 points"; everything else is dollars.
PERCENT_METRICS = {"rate"}
POINT_METRICS = {"rategap"}

# The metrics whose value rides on the ZIP median — and so on which quantity
# that median IS. `rate` and `rategap` are pure market numbers; `lockin` is
# payment arithmetic on the saved balance and rate. None of those three touch
# a median, so none of them has a basis question, none can produce a
# cross-basis ratio, and none may be sent a "recalculated on a new data
# source" notice for a number that did not change how it is computed.
MEDIAN_METRICS = {"walkaway", "equity", "gain"}


# ——— Pure calculation logic (mirrors web/my-report.html's client JS) ———

def pmt(principal, rate_pct, years=30):
    """Standard monthly mortgage payment (principal & interest only)."""
    n = years * 12
    i = rate_pct / 100 / 12
    if not (principal and principal > 0):
        return 0.0
    if not (i > 0):
        return principal / n
    return principal * i * (1 + i) ** n / ((1 + i) ** n - 1)


def latest_price(entry):
    """Most recent non-null monthly price from a ZIP entry's history, or None."""
    p = (entry or {}).get("h", {}).get("p") or []
    for v in reversed(p):
        if v is not None:
            return v
    return None


# ——— Basis: which quantity a median IS ———
#
# `data_pause.LEGACY_BASIS` ("" — absence is the marker) is the closed-sale
# median of the retired provider. `data_pause.RELEASED_BASIS` ("active
# listings") is the median ASKING price of the current one. They track the
# same market and are not the same number, so a ratio built from one of each
# is not an approximation — it is arithmetic on two different quantities.
#
# The failure this guards against, concretely: every subscriber watching a
# dollar number "below" a threshold has a baseline denominator from the old
# basis. Swap in an asking-price numerator and their value steps up for
# reasons that have nothing to do with their market, and the whole book of
# "above" alerts fires in one batch. The 2026-08-14 guard suppressed that
# first batch by rewriting the watch's `basis` — but it carried the baseline
# median through untouched, so the mismatched ratio simply kept running
# afterwards, quietly, for as long as the watch lived.
#
# A basis this module has never recorded is NOT read off the reading in front
# of it. See baseline_basis() for what absence is taken to mean and why that
# is a statement of fact rather than a guess.
#
# HOW MANY WATCHES THIS AFFECTS IS NOT KNOWN HERE. Nothing in the schema
# records when a watch, or the calc_inputs baseline behind it, was written —
# save-watch refreshes calc_inputs in place on every save and stamps no
# timestamp — so the database cannot answer it exactly either. The closest it
# gets, and the query to run with the service key (read-only, no writes):
#
#   select
#     count(*) filter (where w->>'baselineBasis' is null)   as basis_unrecorded,
#     count(*) filter (where w->>'baselineBasis' = '')      as basis_legacy,
#     count(*) filter (where w->>'baselineBasis' = 'active listings')
#                                                           as basis_current,
#     count(*) filter (where w->>'baselineBasis' is null
#                       and coalesce(w->>'baselineMedian',
#                                    s.calc_inputs->>'baselineMedian') is not null)
#                                                           as would_scale,
#     count(*) filter (where s.created_at
#                             < timestamptz '2026-08-14 13:53:43+00')
#                                                           as row_predates_cutover,
#     count(distinct s.id)                                  as subscribers
#   from public.subscribers s
#   cross join lateral jsonb_array_elements(s.watches) as w
#   where s.status in ('active','report')
#     and w->>'metric' in ('walkaway','equity','gain');
#
# `would_scale` is the figure that matters: watches with an unrecorded
# baseline basis AND a median to divide by, i.e. the ones that would have
# formed a cross-basis ratio the moment a tranche was released.
# `row_predates_cutover` is a proxy on the SUBSCRIBER row's creation, not on
# the watch — treat it as an upper bound on age, not as the answer.


class CrossBasisError(ValueError):
    """A scale was asked for across two different bases.

    Deliberately not catchable-into-a-number: the only valid responses are to
    re-base the watch onto the current basis and tell the subscriber
    (`rebaseline_watch`), or to leave it alone. Never to shrug and divide.
    """

    def __init__(self, baseline_basis, current_basis):
        self.baseline_basis = baseline_basis
        self.current_basis = current_basis
        super().__init__(
            f"refusing to scale a baseline taken on basis "
            f"{baseline_basis!r} by a median on basis {current_basis!r}"
        )


def scale_value(baseline_value, baseline_median, current_median,
                baseline_basis=PAUSE.LEGACY_BASIS,
                current_basis=PAUSE.LEGACY_BASIS):
    """Home value carried forward by the ZIP median's move since the watch
    was saved.

    Falls back to the unscaled baseline when either median is unavailable
    (e.g., the ZIP has no price history) — no ratio is formed there, so no
    basis question arises and the subscriber's own saved figure comes back
    untouched. When a ratio WOULD be formed and the two medians were taken on
    different bases, raises CrossBasisError rather than returning a number.

    Both bases default to LEGACY_BASIS so that pre-migration callers, whose
    medians really were both closed-sale figures, keep their meaning.
    """
    if baseline_value is None:
        return None
    if not baseline_median or not current_median:
        return baseline_value
    if baseline_basis != current_basis:
        raise CrossBasisError(baseline_basis, current_basis)
    return baseline_value * (current_median / baseline_median)


def baseline_basis(w):
    """The basis one watch's baseline median was taken on.

    Absence means LEGACY_BASIS, and that is a fact about when these rows were
    written rather than an optimistic default: every watch on the book was
    saved while the legacy reading was the only one published — ingestion has
    been stopped since 2026-08-14 and no tranche has been released — and the
    one case that could be otherwise, a watch saved after a release and never
    yet processed, is stamped by record_baseline_basis() before this is
    consulted.

    The watch's own `basis` key is emphatically NOT a stand-in. `basis`
    describes the last READING processed, and the 2026-08-14 migration arm
    rewrote it while leaving the baseline median untouched — trusting it is
    precisely how the cross-basis ratio survived that guard.
    """
    return w["baselineBasis"] if "baselineBasis" in w else PAUSE.LEGACY_BASIS


def watch_baseline(w, inputs):
    """(value, median) this watch scales from.

    The subscriber-level calc_inputs snapshot, overridden by the per-watch
    figures a rebaseline writes. Per-watch on purpose: calc_inputs is shared
    by all three of a subscriber's watches and set_watches() only ever writes
    the `watches` column, so re-basing one watch must not silently move
    another's baseline or reach for a write path this module does not have.
    """
    value = w["baselineValue"] if "baselineValue" in w else inputs.get("value")
    median = w["baselineMedian"] if "baselineMedian" in w else inputs.get("baselineMedian")
    return value, median


def watch_inputs(w, inputs):
    """calc_inputs with this watch's own baseline spliced in, for compute_metric."""
    value, median = watch_baseline(w, inputs)
    return {**inputs, "value": value, "baselineMedian": median}


def record_baseline_basis(w, entry_basis):
    """Write `baselineBasis` onto a watch that has never carried one.

    Requirement one of the fix: the baseline stores the basis it was taken
    on, in the row, rather than being inferred every run from a global
    assumption that quietly expires the day a tranche is released.

    Two cases, and they resolve differently.

      * No `basis` key either — this module has never processed the watch, so
        my-report.html read its baselineMedian out of the same published data
        this run is reading. That reading's basis IS its basis, and recording
        it moves no number.

      * `basis` present but no `baselineBasis` — processed before this
        function existed, so the baseline is legacy (see baseline_basis).
        It is recorded as legacy, NOT as whatever `basis` says: `basis` was
        rewritten by the 2026-08-14 arm while the baseline median was carried
        through untouched, and copying it here would bless exactly the
        cross-basis ratio this module now refuses.

    (The durable fix belongs upstream — save-watch/index.ts should write
    `baselineBasis` alongside calcInputs, which would close the one-run window
    either side of a release where a freshly saved watch is processed against
    a reading its baseline did not come from. Until it does, that window is
    handled by rebaseline_watch(), which re-bases rather than scales.)
    """
    if "baselineBasis" in w:
        return w
    # ABSENCE OF `basis` IS THE UNIVERSAL STATE, NOT THE SIGNATURE OF A FRESH
    # WATCH. An earlier version of this line read the other way round and
    # adopted `entry_basis` when `basis` was missing. That inference is
    # backwards: `basis` is written in exactly two places, both of which fire
    # only on a basis CHANGE, and no tranche has been released — so it has
    # never been written at all. save-watch/index.ts writes
    # {metric, direction, threshold, crossed} and no basis. Every live watch
    # therefore lands in the "absent" case, and adopting the current basis
    # would stamp a closed-sale baseline as an asking-price one, let
    # scale_value through, and mail the cross-basis figure to the entire book
    # on the first run after a release. Verified: that version emitted a
    # $350,000 equity crossing where the honest unscaled figure was $200,000,
    # and HEAD emitted nothing.
    #
    # Default to LEGACY_BASIS unconditionally — the same default baseline_basis()
    # uses — so an unstamped watch routes to rebaseline_watch() rather than to
    # scale_value(). The entry_basis adoption arm becomes safe only once
    # save-watch stamps baselineBasis at write time, which it does not.
    return {**w, "baselineBasis": PAUSE.LEGACY_BASIS}


def compute_metric(metric, inputs, current_median, market_rate,
                   baseline_basis=PAUSE.LEGACY_BASIS,
                   current_basis=PAUSE.LEGACY_BASIS):
    """Current value of the requested metric, or None if the saved inputs
    are insufficient to compute it (e.g., lock-in needs a rate).

    Raises CrossBasisError for the dollar metrics when the saved baseline and
    the current median were taken on different bases. Callers must re-base
    (see rebaseline_watch) rather than swallow it.
    """
    if metric == "rate":
        # Pure market number — needs no personal inputs at all.
        return market_rate
    if metric == "rategap":
        # Points between today's market rate and theirs — no dollar inputs.
        my_rate = inputs.get("rate")
        return None if my_rate is None else market_rate - my_rate
    bal = inputs.get("bal") or 0
    # Lock-in is evaluated BEFORE the scaled value exists, because it never
    # used one: it compares two payments off the saved balance and rate.
    # Computing a scaled value first would have made it raise CrossBasisError
    # over a median its answer does not contain.
    if metric == "lockin":
        rate = inputs.get("rate")
        if rate is None or bal <= 0:
            return None
        now_pi = pmt(inputs.get("origAmt") or bal, rate)
        mkt_pi = pmt(bal, market_rate)
        return mkt_pi - now_pi
    if metric not in MEDIAN_METRICS:
        return None
    value = scale_value(inputs.get("value"), inputs.get("baselineMedian"), current_median,
                        baseline_basis, current_basis)
    if value is None:
        return None
    if metric == "equity":
        return value - bal
    if metric == "walkaway":
        cost_pct = inputs.get("costPct", 8)
        return value * (1 - cost_pct / 100) - bal
    pp = inputs.get("pp")           # metric == "gain"
    return None if pp is None else value - pp


def is_crossed(value, direction, threshold):
    """True/False once evaluated; None if the metric couldn't be computed."""
    if value is None:
        return None
    return value < threshold if direction == "below" else value > threshold


def fmt(n):
    sign = "− " if n < 0 else ""
    return sign + "$" + f"{abs(round(n)):,}"


def fmt_metric(metric, n):
    """Dollars for personal numbers, percent/points for rate-style metrics."""
    if metric in PERCENT_METRICS:
        return f"{n:.2f}".rstrip("0").rstrip(".") + "%"
    if metric in POINT_METRICS:
        txt = f"{n:.1f}".rstrip("0").rstrip(".")
        return txt + (" point" if txt in ("1", "-1", "−1") else " points")
    return fmt(n)


# ————— Preheader —————
# The inbox gives three slots: sender, subject, then whatever text it scrapes
# first from the body. That third slot was landing on the visible brand
# header, so a row repeated the product name and said the news once. This
# block is invisible when rendered but is the first text a client finds, so
# it becomes the preview line. The trailing zero-width joiners stop clients
# padding the preview with markup that follows.
def preheader(text):
    return ('<div style="display:none;font-size:1px;color:#faf8f4;line-height:1px;'
            'max-height:0;max-width:0;opacity:0;overflow:hidden">' + text
            + "&#8204;&nbsp;" * 60 + "</div>")


def render_watch_email(metric, direction, threshold, current_value, zip_code, token):
    label = METRIC_LABEL.get(metric, metric)
    verb = "dropped below" if direction == "below" else "rose above"
    whose = "The" if metric in PERCENT_METRICS else "Your"
    # The number they chose to watch, and what it just did. No brand — the
    # sender already says it.
    subject = f"{whose} {label} just {verb} {fmt_metric(metric, threshold)}"
    report_url = f"{SITE}/my-report.html?token={token}&zip={zip_code}" if token else f"{SITE}/?zip={zip_code}"
    html = f"""{preheader(f"You asked to hear when this crossed {fmt_metric(metric, threshold)}. It now reads {fmt_metric(metric, current_value)} in {zip_code}.")}
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">\U0001F514 MyMarketCheckup — your number alert</p>
  <h1 style="font-size:24px;margin:6px 0 4px">{whose} {label} just {verb} {fmt_metric(metric, threshold)}</h1>
  <p style="font-size:14px;color:#667085">You asked to hear about this. Current reading: <b>{fmt_metric(metric, current_value)}</b>.</p>
  <p style="margin:24px 0"><a href="{report_url}" style="background:#1f3a5f;color:#fff;padding:13px 24px;border-radius:10px;text-decoration:none;font-family:Arial,sans-serif;font-size:15px;font-weight:bold">Open your report →</a></p>
  <p style="font-size:12px;color:#98a2b3;line-height:1.5">This is your own number, computed from the inputs you saved and the latest licensed market statistics — not an appraisal. Not financial advice. Turn this alert off anytime from your report page.</p>
</div>"""
    return subject, html


def render_rebaseline_email(metric, direction, threshold, current_value, zip_code, token):
    """The disclosure that goes out when a watch is moved onto a new basis.

    Required because the alternative — re-anchoring someone's alert under
    them and saying nothing — changes what their own number means without
    telling them. Says plainly that the figure was recalculated on a new data
    source, that their setting is unchanged, and what it reads now. Names no
    provider: the outgoing one is not the subscriber's business and naming
    the incoming one is barred by its licence.
    """
    label = METRIC_LABEL.get(metric, metric)
    whose = "The" if metric in PERCENT_METRICS else "Your"
    verb = "drops below" if direction == "below" else "rises above"
    past = current_value < threshold if direction == "below" else current_value > threshold
    standing = ("It is already past the line you set, so the next alert will come "
                "when it moves back and crosses again."
                if past else
                "It has not reached the line you set, so your alert is armed as before.")
    subject = f"{whose} {label} alert was recalculated on a new data source"
    report_url = f"{SITE}/my-report.html?token={token}&zip={zip_code}" if token else f"{SITE}/?zip={zip_code}"
    html = f"""{preheader(f"Same alert, new market data. {whose} {label} now reads {fmt_metric(metric, current_value)} in {zip_code}.")}
<div style="font-family:Georgia,serif;max-width:520px;margin:0 auto;color:#101828">
  <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#0b6e64;font-weight:bold">MyMarketCheckup — a note about your alert</p>
  <h1 style="font-size:24px;margin:6px 0 4px">{whose} {label} was recalculated on a new data source</h1>
  <p style="font-size:15px;line-height:1.6;color:#344054">The market statistics behind {zip_code} are being rebuilt on a new data source. It measures the market in a different way, so we re-anchored your alert to today's reading rather than carrying the old comparison forward — carrying it forward would have compared two figures that don't mean the same thing.</p>
  <p style="font-size:15px;line-height:1.6;color:#344054">Nothing you chose has changed. You are still watching your {label} for when it {verb} <b>{fmt_metric(metric, threshold)}</b>. On the new data it reads <b>{fmt_metric(metric, current_value)}</b> today. {standing}</p>
  <p style="margin:24px 0"><a href="{report_url}" style="background:#1f3a5f;color:#fff;padding:13px 24px;border-radius:10px;text-decoration:none;font-family:Arial,sans-serif;font-size:15px;font-weight:bold">Open your report →</a></p>
  <p style="font-size:12px;color:#98a2b3;line-height:1.5">This is your own number, computed from the inputs you saved and the latest licensed market statistics — not an appraisal. Not financial advice. Turn this alert off anytime from your report page.</p>
</div>"""
    return subject, html


# ——— The velocity alert (metric "velocity") ———
# Stateful, not threshold-based: fires when the market's gathering STATE
# escalates past the baseline recorded at save time, then re-baselines so one
# worsening produces one email. De-escalation quietly lowers the baseline —
# nobody wants "good news" spam, and re-arming means a future worsening from
# the better level fires again. States come from zip_velocity (schema-v20),
# fetched in one query for every watched ZIP by main().
VEL_RANK = {"improving": 0, "stable": 1, "drifting": 2, "deteriorating fast": 3}
VEL_PHRASE = {
    "drifting": "has started drifting toward its warning lines",
    "deteriorating fast": "is now moving toward its warning lines fast",
}


def render_velocity_email(old_state, new_state, zip_code, token):
    phrase = VEL_PHRASE.get(new_state, f"changed from {old_state} to {new_state}")
    subject = f"{zip_code}: your market {phrase}"
    html = f"""{preheader(f"Direction change in {zip_code}: {old_state} \u2192 {new_state}. Your full report has the month-by-month pace.")}
<div style="font-family:system-ui,-apple-system,sans-serif;max-width:520px;margin:0 auto;color:#1c2430;line-height:1.65">
<p>You asked to hear if the market in <b>{zip_code}</b> started moving toward a warning line.</p>
<p>It has: our approach-velocity read just moved from <b>{old_state}</b> to <b>{new_state}</b>.
A state change is about direction and pace \u2014 not a verdict flip \u2014 but this is
how turns usually start, months before prices move.</p>
<p style="margin:22px 0"><a href="https://shouldisellyet.com/my-report.html?token={token}"
   style="background:#1f3a5f;color:#faf8f4;text-decoration:none;padding:13px 22px;border-radius:8px;font-weight:600;display:inline-block">
   See which dials are moving \u2192</a></p>
<p style="font-size:13px;color:#8a8578">ShouldISellYet \u00b7 you set this alert on your report page \u2014
manage or turn it off there. <a href="https://kfbjooteazwvdsonthba.supabase.co/functions/v1/unsubscribe?token={token}">Unsubscribe</a></p>
</div>"""
    return subject, html


def rebaseline_watch(w, inputs, current_median, entry_basis, market_rate):
    """Move one dollar-metric watch onto the reading's current basis.

    Returns (new_watch, current_value). A non-None value means the
    subscriber must be told: the number their alert watches is now computed
    from a different kind of market statistic. None means nothing they have
    ever seen moved — the old baseline was not scaling anything, because one
    of the two medians is missing — so the basis is recorded quietly and no
    mail goes out. Without that second case every legacy watch on the book
    would receive a "we recalculated it" notice announcing an identical
    figure, on a run where no recalculation happened.

    The saved value is anchored AS IT STANDS against today's median. There is
    deliberately no carry-forward of the movement since the watch was saved:
    computing one needs exactly the ratio scale_value refuses, so the honest
    move is to drop the cross-basis adjustment, not to invent a substitute
    for it and present it as the subscriber's equity.
    """
    b_value, b_median = watch_baseline(w, inputs)
    if not b_median or not current_median:
        return {**w, "basis": entry_basis, "baselineBasis": entry_basis}, None
    new_w = {**w, "basis": entry_basis, "baselineBasis": entry_basis,
             "baselineValue": b_value, "baselineMedian": current_median}
    value = compute_metric(new_w["metric"], watch_inputs(new_w, inputs),
                           current_median, market_rate,
                           baseline_basis=entry_basis, current_basis=entry_basis)
    crossed = is_crossed(value, new_w["direction"], new_w["threshold"])
    # Re-latch on the re-based figure so the NEXT genuine move sends the
    # ordinary crossing email. The notice below already reports where the
    # number stands relative to their line, so a second mail this run would
    # say the same thing twice.
    new_w["crossed"] = bool(crossed) if crossed is not None else bool(w.get("crossed"))
    return new_w, value


def process_subscriber(sub, data_dir, market_rate):
    """Evaluate every watch entry for one subscriber against fresh ZIP data.

    Returns (updated_watches, emails) where emails is a list of
    (subject, html) tuples to send to sub["email"]. `updated_watches` should
    be written back only if it differs from sub["watches"] (crossed-flag
    changes or a fresh evaluation of a previously-unevaluable metric).
    """
    watches = sub.get("watches") or []
    if not watches:
        return watches, []
    inputs = sub.get("calc_inputs") or {}
    entry = load_zip_data(data_dir, sub.get("zip", ""))
    current_median = latest_price(entry) if entry else None

    # The reading's basis. Legacy entries carry no `b` at all — absence IS
    # the marker (see data_pause.LEGACY_BASIS).
    entry_basis = (entry or {}).get("b", PAUSE.LEGACY_BASIS)

    zip_code = sub.get("zip", "")
    token = sub.get("access_token", "")
    updated, emails = [], []
    vel_state = sub.get("_vel_state")   # attached by main() from zip_velocity
    for w in watches:
        if w.get("metric") == "velocity":
            # Velocity compares a STATE word, not a median: no baseline
            # median, no ratio, nothing to refuse. So it keeps the original
            # migration guard exactly — a basis flip re-reads the state and
            # sends nothing, the same thing a first real read does.
            if w.get("basis", PAUSE.LEGACY_BASIS) != entry_basis:
                fresh = vel_state if vel_state in VEL_RANK else w.get("baseline", "unknown")
                updated.append({**w, "basis": entry_basis, "baseline": fresh})
                continue
            base = w.get("baseline", "unknown")
            cur = vel_state
            if cur is None or cur == "unknown" or cur not in VEL_RANK:
                updated.append(w)          # no fresh read — leave untouched
            elif base not in VEL_RANK:
                updated.append({**w, "baseline": cur})   # first real read becomes baseline
            elif VEL_RANK[cur] > VEL_RANK[base]:
                emails.append(render_velocity_email(base, cur, sub.get("zip", ""),
                                                    sub.get("access_token", "")))
                updated.append({**w, "baseline": cur})
            elif VEL_RANK[cur] < VEL_RANK[base]:
                updated.append({**w, "baseline": cur})   # quiet re-arm downward
            else:
                updated.append(w)
            continue
        # ——— median-backed metrics: basis before arithmetic ———
        # These get their baseline's basis written down first. A watch whose
        # recorded baseline basis no longer matches the reading is then
        # re-based onto the current one and the subscriber is told; it is
        # never scaled across the two, and it is never re-based in silence.
        # Everything else (rate, rategap, lockin) carries no median and so
        # falls straight through to the ordinary crossing check.
        if w.get("metric") in MEDIAN_METRICS:
            w = record_baseline_basis(w, entry_basis)
            if baseline_basis(w) != entry_basis:
                new_w, value = rebaseline_watch(w, inputs, current_median,
                                                entry_basis, market_rate)
                if value is not None:
                    emails.append(render_rebaseline_email(
                        new_w["metric"], new_w["direction"], new_w["threshold"],
                        value, zip_code, token,
                    ))
                updated.append(new_w)
                continue
        value = compute_metric(w["metric"], watch_inputs(w, inputs), current_median,
                               market_rate, baseline_basis=baseline_basis(w),
                               current_basis=entry_basis)
        crossed = is_crossed(value, w["direction"], w["threshold"])
        if crossed is None:
            updated.append(w)  # can't evaluate yet (e.g., lock-in needs a rate) — leave as-is
            continue
        was_crossed = bool(w.get("crossed"))
        if crossed and not was_crossed:
            emails.append(render_watch_email(
                w["metric"], w["direction"], w["threshold"], value,
                zip_code, token,
            ))
            updated.append({**w, "crossed": True})
        elif not crossed and was_crossed:
            updated.append({**w, "crossed": False})  # rearm for a future crossing
        else:
            updated.append(w)
    return updated, emails


# ——— I/O ———

def _req(url, headers=None, data=None, method=None):
    req = urllib.request.Request(
        url, headers=headers or {},
        data=json.dumps(data).encode() if data is not None else None,
        method=method or ("POST" if data is not None else "GET"),
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = r.read().decode()
        return json.loads(body) if body else None


def fetch_watchers(supabase_url, service_key):
    """Active/report subscribers who have at least one watch — filtered
    client-side (not via a jsonb-array PostgREST filter) to stay robust to
    exact-text-match quirks on jsonb equality."""
    url = (f"{supabase_url}/rest/v1/subscribers"
           f"?select=id,email,zip,access_token,calc_inputs,watches"
           # active/report exist only via the payment webhook, which stamps
           # confirmed_at (schema-v19) — payment-verified addresses, the
           # double-opt-in invariant. Never widen this filter.
           f"&status=in.(active,report)")
    rows = _req(url, headers={"apikey": service_key, "Authorization": f"Bearer {service_key}"}) or []
    return [r for r in rows if r.get("watches")]


def set_watches(supabase_url, service_key, sub_id, watches):
    _req(
        f"{supabase_url}/rest/v1/subscribers?id=eq.{sub_id}",
        headers={"apikey": service_key, "Authorization": f"Bearer {service_key}",
                 "Content-Type": "application/json", "Prefer": "return=minimal"},
        data={"watches": watches},
        method="PATCH",
    )


def send_email(api_key, sender, to, subject, html):
    return _req("https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                data={"from": sender, "to": [to], "subject": subject, "html": html})


def load_zip_data(data_dir, zip_code):
    """{state,...entry} for a ZIP from the pipeline's published data, or None."""
    try:
        index = json.load(open(os.path.join(data_dir, "index.json")))
    except (OSError, json.JSONDecodeError):
        return None
    state = index.get(zip_code[:3])
    if not state:
        return None
    try:
        zips = json.load(open(os.path.join(data_dir, "zips", f"{state}.json")))
    except (OSError, json.JSONDecodeError):
        return None
    return zips.get(zip_code)


def load_market_rate(data_dir, fallback=6.58):
    try:
        meta = json.load(open(os.path.join(data_dir, "meta.json")))
        return meta.get("national", {}).get("mortgage", {}).get("now", fallback)
    except (OSError, json.JSONDecodeError):
        return fallback


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="web/data", help="Path to the pipeline's published data dir")
    args = ap.parse_args()

    sb_url = os.environ.get("SUPABASE_URL", "")
    sb_key = os.environ.get("SUPABASE_SERVICE_KEY", "")
    rs_key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("ALERT_FROM", "ShouldISellYet <support@shouldisellyet.com>")

    if not (sb_url and sb_key):
        print("Supabase secrets not configured — DRY RUN, nothing to check.")
        return

    # load_zip_data swallows OSError and returns None per ZIP, so a missing
    # data directory reads as "no subscriber's market moved" and sends nothing.
    # Silence is the safe direction here, but it is not the truthful one.
    require_shards(Path(args.data, "zips"), "check_watches",
                   "the withdrawn per-ZIP metric block")

    watchers = fetch_watchers(sb_url, sb_key)
    total_watches = sum(len(w.get("watches") or []) for w in watchers)
    print(f"{len(watchers)} subscriber(s) with {total_watches} active watch(es) total.")

    # One query hydrates every velocity watch: current gathering state per
    # watched ZIP from zip_velocity (schema-v20). Missing rows leave
    # _vel_state None and the watch is left untouched this run.
    vel_zips = sorted({s.get("zip") for s in watchers
                       if any((w or {}).get("metric") == "velocity"
                              for w in (s.get("watches") or []))
                       and s.get("zip")})
    vel_states = {}
    # VELOCITY_ENABLED reaches the email surface too. Without this the flag
    # covered the report and the endpoint but not the thing that actually
    # arrives in an inbox.
    if vel_zips and VELOCITY.shows_velocity():
        try:
            rows = _req(f"{sb_url}/rest/v1/zip_velocity?select=zip,payload"
                        f"&zip=in.({','.join(vel_zips)})",
                        headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}"})
            vel_states = {r["zip"]: (r.get("payload") or {}).get("state")
                          for r in (rows or [])}
        except Exception as e:
            print(f"zip_velocity read failed — velocity watches skipped: {e}", file=sys.stderr)
    for s in watchers:
        s["_vel_state"] = vel_states.get(s.get("zip"))
    market_rate = load_market_rate(args.data)
    sent = 0

    for sub in watchers:
        updated, emails = process_subscriber(sub, args.data, market_rate)
        for subject, html in emails:
            if rs_key:
                try:
                    send_email(rs_key, sender, sub["email"], subject, html)
                    sent += 1
                except Exception as e:  # one bad address must not kill the batch
                    print(f"send failed for {sub.get('email')}: {e}", file=sys.stderr)
            else:
                print(f"DRY RUN would email {sub.get('email')}: {subject}")
        if updated != sub.get("watches"):
            set_watches(sb_url, sb_key, sub["id"], updated)

    print(f"Sent {sent} personal-number alert(s).")


if __name__ == "__main__":
    main()
