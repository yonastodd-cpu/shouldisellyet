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
// ⚠️ TEAM_NAME and LICENSE_NO are INTENTIONALLY EMPTY. I do not have those
// values, and a licence number is a regulatory credential — inventing a
// plausible-looking one would be far worse than showing the generic text.
// Fill them in and the full disclosure turns on by itself; until then the
// generic version ships, which is accurate and complete on its own terms.
//
// Bump DISCLOSURE_VERSION whenever the wording below changes. It is stored on
// every match_requests row, so "which disclosure did this person actually
// see" stays answerable after the copy has moved on.

const REFERRAL = (function () {
  const AGENT_NAME = "Naomi Todd";
  const AGENT_TITLE = "Licensed Maryland Real Estate Agent";
  const TEAM_NAME = "";            // TODO: team/group name, if any
  const BROKERAGE = "NTRealty";
  const LICENSE_NO = "";           // TODO: MD real estate licence number

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

  /** True only when every credential is present — see rule 2. */
  function complete() {
    return [AGENT_NAME, AGENT_TITLE, TEAM_NAME, BROKERAGE, LICENSE_NO]
      .every(v => typeof v === "string" && v.trim() !== "");
  }

  /** The referring-agent sentence: full credentials, or the generic fallback. */
  function agentLine() {
    if (!complete()) return "Your request will be handled personally by our licensed referring agent.";
    return `Your request will be handled personally by ${AGENT_NAME}, ${AGENT_TITLE} · ` +
           `${TEAM_NAME} · Brokered by ${BROKERAGE} · MD License #${LICENSE_NO}.`;
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
