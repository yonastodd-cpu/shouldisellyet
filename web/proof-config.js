// Proof-counter display thresholds — the definition of "not embarrassing".
//
// A counter below its threshold DOES NOT RENDER: no placeholder, no
// "growing fast!" filler, nothing. Per operator instruction, the number
// shows only once it stands on its own. Editing these requires a commit —
// deliberate friction, so the bar doesn't drift downward in a weak month.
//
// Read by web/index.html (the public proof line) and web/admin.html (the
// Overview panel that shows each value against its threshold, so the
// operator can see zip_checks approaching eligibility).
window.PROOF_THRESHOLDS = {
  zip_checks_month: 500,   // OFF until real volume
  markets_flipped: 25,
  markets_scored: 1000,    // ~33k today — the launch-day counter
};
