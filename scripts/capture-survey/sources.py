#!/usr/bin/env python3
"""Where a third party might be holding a copy, and whether we can ask.

THE HONEST SHAPE OF THIS PROBLEM. Of the three sources the memo asks about,
exactly one can be surveyed without a credential: the web archive. The search
engines retired the mechanism that used to answer this (Google removed the
`cache:` operator and the cached-page link in 2024), and the social platforms
either never had a public read endpoint or retired theirs. A tool that hid
that behind a plausible-looking progress bar would produce a thin CSV and
leave counsel to discover the reason later.

So availability is a first-class field. Every mechanism is registered whether
or not we can run it, every planned query states its availability, and the
unavailable ones still emit a row — URL, mechanism, and the reason nothing
could be checked. "We could not check Facebook's cache without an app token"
is a factual survey finding. A missing row is not.

MUTATION IS THE OTHER AXIS, and it is the one with teeth. Facebook's Sharing
Debugger has a "Scrape Again" action, and the Graph API exposes it as
`?id={url}&scrape=true`. That is not a read. It tells the platform to refetch
our page, which changes the thing being surveyed and leaves a request in their
logs against our property. The memo's caveat — that asking for a removal is a
discoverable act — applies to it in full, and it is a survey mechanism only by
accident of sharing an endpoint with one. It is registered here with
`mutating=True` and the planner refuses to emit it. Turning it on is the
runbook's removal procedure, behind counsel sign-off, not part of a survey.

NOTHING IN THIS MODULE OPENS A SOCKET. It builds request descriptors —
method, URL, query string — and hands them back as data. transport.py is the
only file in this tree that can perform one, and only when the survey was run
with an explicit flag.
"""

from urllib.parse import urlencode

import windows

# ————— availability —————
PUBLIC = "public"                      # runnable now, no credential
CREDENTIAL = "requires_credential"     # an endpoint exists; we hold no token
RETIRED = "retired"                    # the mechanism no longer exists
POLICY = "policy_review"               # technically possible, not clearly permitted

# ————— sources —————
WEBARCHIVE = "webarchive"
SEARCHCACHE = "searchcache"
SOCIALPREVIEW = "socialpreview"
SOURCES = (WEBARCHIVE, SEARCHCACHE, SOCIALPREVIEW)


class Mechanism:
    __slots__ = ("id", "source", "label", "availability", "method", "base",
                 "mutating", "requires", "note")

    def __init__(self, id, source, label, availability, method="GET", base="",
                 mutating=False, requires="", note=""):
        self.id = id
        self.source = source
        self.label = label
        self.availability = availability
        self.method = method
        self.base = base
        self.mutating = mutating
        self.requires = requires
        self.note = note


MECHANISMS = (
    # ——— web archive: the one source that actually answers ———
    Mechanism(
        "wayback_cdx", WEBARCHIVE,
        "Internet Archive CDX capture index", PUBLIC,
        base="https://web.archive.org/cdx/search/cdx",
        note="Returns one row per capture: timestamp, status, content digest. "
             "No `to=` bound is applied — the query deliberately returns "
             "captures on BOTH sides of the exposure window, because a "
             "capture after the fix is the evidence that the fix is live in "
             "the archive too. The in-window decision is made locally by "
             "windows.matched(), where it can be re-checked without "
             "re-querying anyone."),
    Mechanism(
        "wayback_snapshot", WEBARCHIVE,
        "Internet Archive stored snapshot body", PUBLIC,
        base="https://web.archive.org",
        note="Second stage, one request per in-window capture, and the only "
             "thing that can answer whether a withdrawn figure is VISIBLE "
             "rather than merely archived. Uses the `id_` modifier so the "
             "archive returns the original stored bytes without its own "
             "toolbar injected — otherwise the detector scans the archive's "
             "chrome as if it were our page."),

    # ——— search engines: nothing here is runnable ———
    Mechanism(
        "google_cache_operator", SEARCHCACHE,
        "Google `cache:` operator / cached-page link", RETIRED,
        note="Removed in 2024. There is no successor that serves a stored "
             "copy of a third party's page. Registered so the survey can "
             "state that the check was impossible rather than omitted."),
    Mechanism(
        "gsc_url_inspection", SEARCHCACHE,
        "Search Console URL Inspection API", CREDENTIAL,
        base="https://searchconsole.googleapis.com/v1/urlInspection/index:inspect",
        requires="OAuth for the verified property (pipeline/mint_gsc_token.py "
                 "mints one for a different job; NOTHING is wired to it here)",
        note="Reports index coverage and last crawl date for OUR OWN "
             "property. That is an index-presence signal, not a cached copy, "
             "and it says nothing about what a cached copy still shows. "
             "Useful corroboration for a crawl date inside the window; not a "
             "substitute for the archive."),
    Mechanism(
        "bing_cached_page", SEARCHCACHE,
        "Bing cached-page view", CREDENTIAL,
        base="https://cc.bingj.com/cache.aspx",
        requires="a per-result document id obtainable only from a Web Search "
                 "API response, which is a paid key",
        note="The cached view still exists but is not addressable from a URL "
             "alone, so it cannot be driven from a target list."),
    Mechanism(
        "serp_site_query", SEARCHCACHE,
        "Automated `site:` / `url:` query against a search UI", POLICY,
        note="Technically trivial and would answer index presence. It is "
             "automated querying of a search interface, which their terms "
             "address directly. Left unrunnable pending the same sign-off "
             "the removal procedures need — a survey that breaks a second "
             "set of terms while documenting a breach of the first is not a "
             "survey counsel can file."),

    # ——— social previews: one credentialed read, one mutation, one retired ———
    Mechanism(
        "facebook_graph_read", SOCIALPREVIEW,
        "Graph API og_object read", CREDENTIAL,
        base="https://graph.facebook.com/v20.0/",
        requires="an app access token",
        note="GET ?id={url}&fields=og_object,updated_time reads what Meta "
             "currently holds for a URL WITHOUT refetching it. This is the "
             "only social-preview read that is a read. No token is wired in."),
    Mechanism(
        "facebook_scrape_again", SOCIALPREVIEW,
        "Graph API scrape=true (Sharing Debugger 'Scrape Again')", CREDENTIAL,
        method="POST", base="https://graph.facebook.com/v20.0/",
        mutating=True,
        requires="an app access token",
        note="NOT A SURVEY MECHANISM. It tells Meta to refetch our page: it "
             "changes the cache being surveyed and leaves a request against "
             "our property in their logs. It is the remedy, not the "
             "measurement, and the memo's discoverability caveat applies to "
             "it. Registered so its exclusion is on the record; "
             "plan_for() refuses to emit it."),
    Mechanism(
        "linkedin_post_inspector", SOCIALPREVIEW,
        "LinkedIn Post Inspector", POLICY,
        base="https://www.linkedin.com/post-inspector/inspect/",
        note="No public read API, one URL at a time through a browser — and "
             "inspecting REFRESHES the cache, so it is a mutation wearing a "
             "reader's clothes. Same treatment as scrape=true: runbook, not "
             "survey."),
    Mechanism(
        "x_card_validator", SOCIALPREVIEW,
        "X / Twitter Card Validator", RETIRED,
        note="Retired. No read, no forced refresh. Caches expire on their "
             "own, typically within about a week (INVALIDATION_RUNBOOK.md), "
             "which for a survey means there is nothing left to find and "
             "nothing to ask."),
)

BY_ID = {m.id: m for m in MECHANISMS}

# Seconds between requests. It lives here rather than in transport.py so that
# PLAN mode can state how long a run would take without importing an HTTP
# client — the property transport.py's second lock exists to preserve. The
# archive's CDX endpoint is a shared public service and a full-scope run is a
# large ask of it; being slow is cheaper than being rate-limited into a
# partial dataset that looks complete.
REQUEST_INTERVAL_S = 1.0


def for_source(source):
    return tuple(m for m in MECHANISMS if m.source == source)


def runnable(source):
    """The mechanisms a --collect run would actually perform."""
    return tuple(m for m in for_source(source)
                 if m.availability == PUBLIC and not m.mutating)


class PlannedQuery:
    """One request the tool would make, fully formed. Data, never performed."""

    __slots__ = ("mechanism", "target", "variant", "method", "url", "stage",
                 "blocked_reason", "note")

    def __init__(self, mechanism, target, variant, method, url, stage,
                 blocked_reason="", note=""):
        self.mechanism = mechanism
        self.target = target
        self.variant = variant
        self.method = method
        self.url = url
        self.stage = stage
        # blocked_reason is why this query CANNOT be made. It is not a general
        # note field: the plan counts a query as runnable exactly when this is
        # empty, and an explanatory string parked here once made 60 perfectly
        # runnable stage-2 queries report as unrunnable.
        self.blocked_reason = blocked_reason
        self.note = note


def cdx_url(page_url, limit=500):
    """The capture-index query for one URL spelling.

    `collapse=digest` folds runs of byte-identical captures into their first
    occurrence. That is what makes the output readable — a daily crawler
    produces hundreds of identical rows — and it is also what makes it
    evidential: a new digest is a moment the page CHANGED, which is exactly
    where the withdrawal should show up.
    """
    q = [("url", page_url), ("output", "json"),
         ("fl", "timestamp,original,statuscode,digest,mimetype,length"),
         ("collapse", "digest"), ("matchType", "exact"), ("limit", str(limit))]
    return f"{BY_ID['wayback_cdx'].base}?{urlencode(q)}"


def snapshot_url(timestamp, original):
    """The stored bytes for one capture, without the archive's toolbar."""
    return f"{BY_ID['wayback_snapshot'].base}/web/{timestamp}id_/{original}"


def _blocked_reason(m):
    if m.availability == RETIRED:
        return f"{m.label} no longer exists; there is no successor read"
    if m.availability == CREDENTIAL:
        return f"requires {m.requires}; none wired in"
    if m.availability == POLICY:
        return "needs counsel sign-off before it may run"
    return ""


def plan_for(target, source):
    """Every query this source would make for one target.

    Mutating mechanisms are never emitted. That is a hard filter and not a
    default: the removal procedures live in CAPTURE_SURVEY_RUNBOOK.md as
    manual steps, so that no flag on this tool can make it contact a platform
    to ask for something.
    """
    out = []
    for m in for_source(source):
        if m.mutating:
            continue
        if m.availability != PUBLIC:
            out.append(PlannedQuery(m, target, target.url, m.method,
                                    m.base or "(no endpoint)", "n/a",
                                    _blocked_reason(m)))
            continue
        if m.id == "wayback_cdx":
            for variant in target.variants:
                out.append(PlannedQuery(m, target, variant, "GET",
                                        cdx_url(variant), "1-index"))
        elif m.id == "wayback_snapshot":
            out.append(PlannedQuery(
                m, target, target.url, "GET",
                snapshot_url("{capture_timestamp}", target.url),
                "2-body", "",
                "one request per in-window capture found in stage 1, plus the "
                "first capture after the window closes; the count is not "
                "knowable until stage 1 has run"))
    return out


def window_summary(target):
    """'consumer_figures ≤2026-08-20T23:59:59Z (day)' for the plan output."""
    return "; ".join(
        f"{w} ≤{windows.WINDOWS[w]['end_utc']} ({windows.WINDOWS[w]['precision']})"
        for w in target.windows)
