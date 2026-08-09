// ShouldISellYet — Cloudflare Turnstile, invisible mode, on email-accepting
// forms only. NOT on the free ZIP check (no friction there, ever), NOT on
// page load, and NOT Google reCAPTCHA — reCAPTCHA would falsify the privacy
// page's no-Google-trackers claim; Turnstile keeps it true and the privacy
// page names it in one line.
//
// INERT UNTIL CONFIGURED. SITE_KEY below is empty until the operator creates
// the (free) widget in the Cloudflare dashboard. Empty key → no script ever
// loads, forms submit without a token, and the edge functions (whose
// TURNSTILE_SECRET is likewise unset) skip verification. Fill the key, set
// the secret, redeploy functions — the layer switches on with no other change.
//
// GRACEFUL DEGRADE, chosen over lockout: if the script fails to load (network,
// blocker) the form submits without a token and the server ALLOWS it, counting
// turnstile_bypass so a rising bypass rate is visible in events_daily. The
// honeypot (T1) and rate limits (T2) still stand in front of every bypass.
//
// TODO(operator): create the Turnstile site key — Cloudflare dashboard →
// Turnstile → Add site (free tier, invisible/managed) → paste the site key
// here, then: npx supabase secrets set TURNSTILE_SECRET=<secret key>
// and redeploy signup, match-request, save-watch.
window.SISY_TS = (function () {
  const SITE_KEY = "";   // ← operator fills; empty = layer off

  let scriptFailed = false, apiReady = false;
  const widgets = new Map();   // slot element → widget id

  function load() {
    if (!SITE_KEY || document.getElementById("cf-ts-api")) return;
    const s = document.createElement("script");
    s.id = "cf-ts-api";
    s.src = "https://challenges.cloudflare.com/turnstile/v0/api.js?onload=__sisyTsReady&render=explicit";
    s.async = true;
    s.onerror = () => { scriptFailed = true; };
    document.head.appendChild(s);
  }

  window.__sisyTsReady = function () {
    apiReady = true;
    document.querySelectorAll(".ts-slot").forEach((slot) => {
      try {
        const id = turnstile.render(slot, {
          sitekey: SITE_KEY,
          appearance: "interaction-only",   // invisible unless CF wants a check
          callback: () => {},               // token read via getResponse()
          "error-callback": () => {},       // degrade path — token() returns ""
        });
        widgets.set(slot, id);
      } catch (e) { /* degrade */ }
    });
  };

  // Current token for the form owning `slot`, or "" (not configured, script
  // failed, or challenge errored — the server's bypass counter covers those).
  // Tokens are single-use: the widget is reset after each read so the next
  // submit mints a fresh one.
  function token(slot) {
    if (!SITE_KEY || scriptFailed || !apiReady || !slot) return "";
    const id = widgets.get(slot);
    if (id === undefined) return "";
    try {
      const t = turnstile.getResponse(id) || "";
      if (t) turnstile.reset(id);
      return t;
    } catch (e) { return ""; }
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();

  return { token, enabled: () => !!SITE_KEY };
})();
