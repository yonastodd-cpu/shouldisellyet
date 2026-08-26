"""ONDEMAND_ENABLED is mirrored, and mirrors that can diverge are not a flag.

Same arrangement as test_figures_switch.py / test_velocity_switch.py: the
Python module is authoritative, the TypeScript function and the two web pages
carry literals they cannot import, and this test fails the build when any
copy disagrees. Flipping the switch = edit all four + deploy the function.

Run: python3 -m pytest pipeline/test_ondemand_switch.py -q
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).parent))

import ondemand_switch


def _flag_in(path, pattern):
    src = (ROOT / path).read_text()
    m = re.search(pattern, src)
    assert m, f"{path}: no ONDEMAND_ENABLED literal found"
    return m.group(1) == "true"


def test_the_authoritative_flag_is_a_bool():
    assert isinstance(ondemand_switch.ONDEMAND_ENABLED, bool)


def test_the_mirror_list_is_the_actual_set_of_copies():
    """A copy not in MIRRORS is a copy this test does not pin."""
    assert set(ondemand_switch.MIRRORS) == {
        "supabase/functions/ondemand-pull/index.ts",
        "web/index.html",
        "web/subscribe.html",
    }


def test_every_mirror_agrees_with_the_module():
    want = ondemand_switch.ONDEMAND_ENABLED
    for path in ondemand_switch.MIRRORS:
        got = _flag_in(path, r"const ONDEMAND_ENABLED = (true|false)")
        assert got == want, (
            f"{path} says ONDEMAND_ENABLED={got}, pipeline/ondemand_switch.py "
            f"says {want} — the copies must move together, and the function "
            f"copy only takes effect when the function is REDEPLOYED")


def test_the_server_copy_is_exported_for_inspection():
    src = (ROOT / "supabase/functions/ondemand-pull/index.ts").read_text()
    assert "export const ONDEMAND_ENABLED" in src
