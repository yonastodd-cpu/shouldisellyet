// ShouldISellYet — referring-agent disclosure.
//
// When someone asks for an introduction, they are told — at that moment, on
// screen and again by email — who will handle it and how anyone gets paid.
// Not buried in Terms.
//
// TWO RULES GOVERN THIS FILE.
//
// 1. NOTHING HERE RENDERS BEFORE SUBMISSION. The Get Connected card and its
//    form name no agent, show no photo, and carry no brokerage. A request
//    form that leads with a specific agent is a funnel; one that discloses
//    after you ask is a disclosure. Only showConnected()'s success state
//    reads this module.
//
// 2. IT FAILS CLOSED. If any credential below is blank, the disclosure drops
//    to "our licensed referring agent" rather than rendering a half-identity
//    like "Naomi Todd, Licensed Maryland Real Estate Agent · · Brokered by ·
//    MD License #". A partial credential reads as sloppy at best and as a
//    misstated licence at worst.
//
// TEAM_NAME is empty and optional — the line omits that segment rather than
// leaving a dangling separator. Every REQUIRED credential is filled, so the
// full disclosure is what ships.
//
// Bump DISCLOSURE_VERSION whenever the wording below changes. It is stored on
// every match_requests row, so "which disclosure did this person actually
// see" stays answerable after the copy has moved on.

const REFERRAL = (function () {
  const AGENT_NAME = "Naomi Todd";
  const AGENT_TITLE = "Licensed Maryland Real Estate Agent";
  // Optional, and NOT part of complete() — see below. Set it to add a
  // "· <team> ·" segment; leave it empty and the line simply omits that part.
  const TEAM_NAME = "";
  const BROKERAGE = "NTRealty";
  const LICENSE_NO = "5011323";    // MD real estate licence

  const DISCLOSURE_VERSION = "2026-08-05.v1";

  const NEXT_STEPS_FULL =
    "She'll reach out within 2 business days to make your introduction to a " +
    "vetted local agent. No cost, no obligation.";
  const NEXT_STEPS_GENERIC =
    "They'll reach out within 2 business days to make your introduction to a " +
    "vetted local agent. No cost, no obligation.";

  // The material connection, in the plainest words that are still accurate.
  const MATERIAL_CONNECTION =
    "If you choose to work with an introduced agent, our referring agent's " +
    "brokerage may receive a standard broker-to-broker referral fee. This " +
    "never affects your verdict and never costs you anything.";

  /** True only when every REQUIRED credential is present — see rule 2.
   *
   *  TEAM_NAME is deliberately excluded. The fail-closed rule exists to stop a
   *  broken or misstated LICENCE reaching a consumer; a missing team name
   *  creates no such risk, and plenty of agents simply do not have one.
   *  Requiring it would have held the whole disclosure at the generic fallback
   *  forever over a cosmetic field — which would be the rule defeating its own
   *  purpose. Name, title, brokerage and licence are the four that matter. */
  function complete() {
    return [AGENT_NAME, AGENT_TITLE, BROKERAGE, LICENSE_NO]
      .every(v => typeof v === "string" && v.trim() !== "");
  }

  /** The referring-agent sentence: full credentials, or the generic fallback.
   *  Segments are joined rather than templated, so an empty optional field
   *  drops out cleanly instead of leaving a dangling " · ". */
  function agentLine() {
    if (!complete()) return "Your request will be handled personally by our licensed referring agent.";
    const parts = [`${AGENT_NAME}, ${AGENT_TITLE}`, TEAM_NAME,
                   `Brokered by ${BROKERAGE}`, `MD License #${LICENSE_NO}`]
      .filter(s => s && s.trim() !== "");
    return `Your request will be handled personally by ${parts.join(" · ")}.`;
  }

  function nextSteps() {
    return complete() ? NEXT_STEPS_FULL : NEXT_STEPS_GENERIC;
  }

  /**
   * The version stamped on the stored request. It records the VARIANT too —
   * "full" and "generic" are different disclosures, and six months from now
   * the difference is exactly what someone auditing a request would need.
   */
  function version() {
    return DISCLOSURE_VERSION + (complete() ? "-full" : "-generic");
  }

  /** The three sentences, in order, as plain text — for the email and for
   *  anything else that needs the disclosure without markup. */
  function plainText() {
    return [agentLine(), nextSteps(), MATERIAL_CONNECTION].join("\n\n");
  }

  return {
    complete, agentLine, nextSteps, version, plainText,
    MATERIAL_CONNECTION, DISCLOSURE_VERSION,
  };
})();
