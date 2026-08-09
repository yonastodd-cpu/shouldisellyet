// ————— Alert copy map — the ONE source for alert wording —————
// Every alert label and its microcopy lives here and only here. The homepage
// preview reads it today; the report page and the alert emails are meant to
// reuse it when personal alerts ship (FOLLOW-UP — do not fork this wording
// into my-report.html or the edge functions by hand; import or mirror THIS
// map, and if an email template must inline a string, cite this file in the
// comment beside it).
//
// Keys under rows match the preview/report section numbers. The microcopy is
// written in the visitor's first person ("my number", "my equity") because it
// completes the sentence "Alert me …".
window.ALERT_COPY = {
  // The toggle's visible label, and the sentence screen readers get appended
  // to a locked row's aria-label. Every string the toggles render lives in
  // this map — index.html holds no alert wording of its own.
  toggle_label: "Alert me",
  aria_suffix: "Alert available with monitoring.",

  // Shown on hover/tap of a locked toggle.
  locked_sublabel: "Alert me — included with monitoring",

  // The free-tier affordance's language, when/where one exists. (As of
  // 2026-08-08 no free alert affordance renders in the results block — the
  // inline signup form was removed 2026-07-31 — so this string waits for the
  // surface that next carries it: subscribe.html copy and future report use.)
  verdict_change: "Alert me · the moment this ZIP's verdict changes",

  rows: {
    "02": "if my home's value trend turns negative",
    "03": "when my equity crosses $___",
    "04": "if this drops below my number",
    "05": "if the market rate comes within ½ pt of mine",
    "06": "if my safety margin thins",
    "07": "60 days before my best listing window",
    "09": "if my market starts moving toward a warning line"
  }
};

// Homepage "Alerts in action" strip — the same triggers, phrased standalone.
// The rows[] strings assume their report-row context sits beside them
// ("if this drops below my number" needs the walk-away row above it), so two
// entries here are standalone rewordings of rows 01/04 and one reuses
// rows["05"] verbatim. Built AFTER the map literal so it can reference it —
// this file stays the single source for every alert string on the site.
window.ALERT_COPY.strip = [
  window.ALERT_COPY.toggle_label + " · the moment my ZIP's verdict changes",
  window.ALERT_COPY.toggle_label + " · if my walk-away number drops below my line",
  window.ALERT_COPY.toggle_label + " · " + window.ALERT_COPY.rows["05"],
];
