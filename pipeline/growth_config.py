"""
ShouldISellYet — Growth Ops digest configuration.

Everything an operator is likely to want to change lives here, so the digest
can be retargeted without touching generation logic. See docs/GROWTH-OPS.md.
"""

# ——— Who gets the monthly digest ———
# Overridden at runtime by the OPS_DIGEST_RECIPIENTS env var (comma-separated),
# which is how CI supplies it. This list is the fallback default.
DIGEST_RECIPIENTS = ["admin@shouldisellyet.com"]

# ——— The home market ———
# DMV flips are listed individually and sorted first everywhere in the digest;
# everything else is aggregated. Matching is by ZIP prefix so a whole county or
# exchange can be added with one short string.
#   DC  200/202-205  ·  MD suburbs 206-209, 217 (Frederick), 210-212 (Baltimore)
#   VA inner 220-223, 201 (Fairfax/Arlington/Alexandria/Loudoun/PW)
DMV_PREFIXES = [
    "200", "202", "203", "204", "205",          # Washington, DC
    "206", "207", "208", "209",                  # Montgomery / Prince George's
    "210", "211", "212", "217",                  # Baltimore metro, Frederick
    "201", "220", "221", "222", "223",           # Northern Virginia
]

# ——— Rate burst play ———
# A month-over-month (or week-over-week, for the weekly job) move of at least
# this many percentage points is treated as a marketing window.
RATE_BURST_POINTS = 0.25

# ——— Angle bank ———
ANGLE_COUNT = 5           # facts to surface, DMV first then national
MIN_SOLD_FOR_ANGLE = 15   # ignore thin ZIPs; one sale can swing a percentage


def is_dmv(zip_code: str) -> bool:
    return any(zip_code.startswith(p) for p in DMV_PREFIXES)
