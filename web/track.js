// ShouldISellYet — anonymous first-party usage counting. Loaded on every page.
//
// What this deliberately is NOT: user tracking. No cookies, no localStorage,
// no fingerprinting, no identifiers of any kind — the privacy policy promises
// exactly that, and the server table has no columns that could hold more (see
// supabase/schema-v11.sql). Everything here is an event COUNTER.
//
// Do Not Track / Global Privacy Control: if either is signalled, this file
// does nothing at all — no page_view, no click events, SISY.track is a no-op.
// "We honor Do Not Track" means zero requests, not degraded ones.
//
// Sessions without identity: sessionStorage (cleared when the tab closes,
// never sent as an identifier) marks the FIRST page_view of a browser session
// so the dashboard can approximate visitors as "sessions, not people". The
// same mechanism carries the landing page's utm_source / referrer domain to
// later events in the session — channel attribution, still nobody's identity.
//
// Two ways events fire:
//   * declaratively: any element with data-track="event_name" (and optional
//     data-track-zip) sends on click — used by CTAs, so page scripts don't
//     need wiring for simple buttons.
//   * imperatively: window.SISY.track("zip_check", {zip}) from page code
//     where there is real context (the checked ZIP, the chosen plan).
//
// Sends are fire-and-forget: text/plain body (no CORS preflight — one request
// per event, not two), keepalive so navigation doesn't cancel purchase
// clicks, and every failure is swallowed. Analytics must never cost a
// customer anything.

(function () {
  "use strict";

  var DNT = navigator.doNotTrack === "1" || window.doNotTrack === "1" ||
            navigator.globalPrivacyControl === true;

  if (DNT) {
    window.SISY = { track: function () {} };
    return;
  }

  var FN = "https://kfbjooteazwvdsonthba.supabase.co/functions/v1/track";

  // First page_view of this browser session? sessionStorage can throw in
  // some private-browsing modes; treat that as "not new" rather than failing.
  var newSession = false;
  try {
    if (!sessionStorage.getItem("sisy_s")) {
      sessionStorage.setItem("sisy_s", "1");
      newSession = true;
    }
  } catch (e) {}

  // Capture channel on the landing page only; carry it for the session.
  var utm = "", ref = "";
  try {
    utm = sessionStorage.getItem("sisy_utm") || "";
    ref = sessionStorage.getItem("sisy_ref") || "";
    var qsUtm = new URLSearchParams(location.search).get("utm_source");
    if (qsUtm && !utm) { utm = qsUtm.slice(0, 60); sessionStorage.setItem("sisy_utm", utm); }
    if (document.referrer && !ref) {
      var h = new URL(document.referrer).hostname;
      if (h && h !== location.hostname) { ref = h; sessionStorage.setItem("sisy_ref", ref); }
    }
  } catch (e) {}

  function send(event, extra) {
    extra = extra || {};
    var payload = {
      event: event,
      ns: extra.ns === true,
      source: utm || undefined,
      ref: ref || undefined,
      // pathname ONLY — location.search may carry a report access token,
      // and that must never reach analytics. The server strips again.
      path: location.pathname,
      zip: extra.zip || undefined,
      plan: extra.plan || undefined,
      // Which price led the page when a purchase CTA was clicked — set
      // centrally so every purchase_click carries it, from any page.
      // (prices.js publishes window.PRICE_DISPLAY_MODE; pages without
      // prices.js send no mode, and the column stays null.)
      price_mode: (event.indexOf("purchase_click") === 0 && window.PRICE_DISPLAY_MODE) || undefined,
    };
    try {
      fetch(FN, {
        method: "POST",
        keepalive: true,
        headers: { "Content-Type": "text/plain" },
        body: JSON.stringify(payload),
      }).catch(function () {});
    } catch (e) {}
  }

  window.SISY = { track: function (event, extra) { send(event, extra || {}); } };

  send("page_view", { ns: newSession });

  // Declarative click events. One delegated listener; keepalive above means
  // the following navigation can't cancel the send.
  document.addEventListener("click", function (e) {
    var el = e.target && e.target.closest && e.target.closest("[data-track]");
    if (!el) return;
    var name = el.getAttribute("data-track");
    if (!name) return;
    send(name, { zip: el.getAttribute("data-track-zip") || undefined });
  });
})();
