"""Token minting — the parameters that are silently load-bearing.

Nothing here touches the network or a browser. What it pins is the handful
of details whose absence produces a confusing success rather than a clear
failure: a consent URL missing access_type/prompt returns no refresh token
on a repeat run, and a callback without a state check will accept an
authorization code from any local process that reaches the port first.

Run: python3 -m pytest pipeline/test_mint_gsc_token.py -q
"""

import base64
import hashlib
import sys
import urllib.parse
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from mint_gsc_token import (SCOPE, WANT, auth_url, code_from_redirect,
                            pkce_pair, summarise_properties)


# ————— PKCE —————

def test_challenge_is_unpadded_base64url_sha256_of_the_verifier():
    verifier, challenge = pkce_pair("a-known-verifier")
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(b"a-known-verifier").digest()).decode().rstrip("=")
    assert challenge == expected
    assert "=" not in challenge and "+" not in challenge and "/" not in challenge


def test_generated_verifiers_differ():
    assert pkce_pair()[0] != pkce_pair()[0]


# ————— the consent URL —————

def q(url):
    return urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)


def test_offline_and_consent_are_both_present():
    """Without access_type=offline Google issues no refresh token at all;
    without prompt=consent it issues none on a REPEAT authorization, which
    reads as a broken script rather than as Google having answered once."""
    p = q(auth_url("cid", "http://127.0.0.1:8765", "chal", "st"))
    assert p["access_type"] == ["offline"]
    assert p["prompt"] == ["consent"]


def test_scope_is_read_only():
    p = q(auth_url("cid", "http://127.0.0.1:8765", "chal", "st"))
    assert p["scope"] == [SCOPE] and SCOPE.endswith("webmasters.readonly")


def test_url_carries_pkce_and_state():
    p = q(auth_url("cid", "http://127.0.0.1:8765", "chal", "st"))
    assert p["code_challenge"] == ["chal"]
    assert p["code_challenge_method"] == ["S256"]
    assert p["state"] == ["st"]
    assert p["response_type"] == ["code"]


# ————— the callback —————

def test_code_is_read_from_the_redirect():
    assert code_from_redirect("/?code=abc123&state=st", "st") == "abc123"


def test_state_mismatch_is_refused():
    """The loopback redirect is unauthenticated: any local process could
    reach the port. The state check is the only thing distinguishing our
    callback from someone else's."""
    with pytest.raises(ValueError, match="state mismatch"):
        code_from_redirect("/?code=abc123&state=wrong", "st")


def test_missing_state_is_refused():
    with pytest.raises(ValueError, match="state mismatch"):
        code_from_redirect("/?code=abc123", "st")


def test_google_error_is_surfaced_not_swallowed():
    with pytest.raises(ValueError, match="access_denied"):
        code_from_redirect("/?error=access_denied&state=st", "st")


def test_missing_code_is_an_error():
    with pytest.raises(ValueError, match="no code"):
        code_from_redirect("/?state=st", "st")


# ————— property matching —————

def test_domain_property_is_matched_exactly():
    sites = {"siteEntry": [
        {"siteUrl": WANT, "permissionLevel": "siteOwner"},
        {"siteUrl": "sc-domain:example.com", "permissionLevel": "siteOwner"}]}
    rows, matched = summarise_properties(sites)
    assert matched and len(rows) == 2


def test_url_prefix_property_does_not_count_as_the_domain_property():
    """https://shouldisellyet.com/ and sc-domain:shouldisellyet.com are
    different objects in Search Console, with different data."""
    sites = {"siteEntry": [{"siteUrl": "https://shouldisellyet.com/",
                            "permissionLevel": "siteOwner"}]}
    rows, matched = summarise_properties(sites)
    assert rows and not matched


def test_no_properties_is_not_a_crash():
    assert summarise_properties({}) == ([], False)
    assert summarise_properties({"siteEntry": []}) == ([], False)
    assert summarise_properties(None) == ([], False)
