#!/usr/bin/env python3
"""ONDEMAND_ENABLED — sell reports for notice ZIPs via purchase-time pulls.

WHAT THE SWITCH GOVERNS. With it ON, a ZIP showing the rebuilding notice
carries a purchase CTA, and the checkout page calls the `ondemand-pull` edge
function BEFORE handing the buyer to Stripe: the function pulls fresh market
data for the ZIP (or answers from the private store), validates the same
data-quality floor the live pages use, and only a passing answer lets the
Stripe redirect happen. FAIL → the buyer is told plainly and never charged.
With it OFF, notice ZIPs behave as before: notice, notify-me, no purchase
path.

A MODULE ATTRIBUTE, NOT AN ENVIRONMENT READ — same discipline as
velocity_switch.py and figures_switch.py, for the same reason: a flag whose
copies are set three different ways is a flag that gets flipped in two of
them, and an env read makes the deployed posture invisible in the repo.

THE COPIES MUST MOVE TOGETHER. Deno and browser JavaScript cannot import
this module, so the flag is MIRRORED, never shared:

    pipeline/ondemand_switch.py                     this file — authoritative
    supabase/functions/ondemand-pull/index.ts       the server-side gate
    web/index.html                                  the notice-branch CTA
    web/subscribe.html                              the pre-payment gate

pipeline/test_ondemand_switch.py pins all four to each other. Flipping the
switch means editing all four AND DEPLOYING THE FUNCTION — the two web copies
take effect on the next build, the function's only when it ships.

Note the asymmetry of a mismatch: the server copy is the one that spends
money, so if the copies ever diverge, OFF on the server wins (the client CTA
then leads to a "disabled" answer and checkout falls back to the coverage
check). That is the safe direction, and the test exists so it never happens
anyway.
"""

ONDEMAND_ENABLED = True

# Every file that carries a copy of the flag, for the pinning test.
MIRRORS = (
    "supabase/functions/ondemand-pull/index.ts",
    "web/index.html",
    "web/subscribe.html",
)
