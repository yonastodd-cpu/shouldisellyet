#!/usr/bin/env python3
"""Mint a Search Console refresh token, once, on this machine.

    python3 pipeline/mint_gsc_token.py --client-id <id>

Opens Google's consent screen in your browser, catches the redirect on
localhost, exchanges the code, and prints the refresh token — then
immediately calls the API with it and lists which Search Console properties
that account can actually see. That last step is the point: a token can be
perfectly valid and still be attached to the wrong Google account, and the
DNS TXT record on shouldisellyet.com proves ownership only to whichever
account used it. Finding that out here costs nothing; finding it out from a
403 inside a scheduled run costs a debugging session.

Nothing is written to disk. The token is printed once, to your terminal,
with the commands to store it as a repository secret. Run it, store the
value, close the window.

THE SECRET IS NEVER AN ARGUMENT. --client-id is fine on the command line;
the client secret is read from GSC_CLIENT_SECRET or prompted for without
echo, because anything in argv is visible to `ps` and lands in shell
history. Same reason the token is not written to a file: a secret on disk
outlives the reason it was there.

TWO PARAMETERS THAT LOOK OPTIONAL AND ARE NOT. access_type=offline is what
makes Google issue a refresh token at all, and prompt=consent is what makes
it issue one AGAIN on a repeat authorization. Without the second, a second
run of this script returns an access token and no refresh token, and the
usual conclusion is that something is broken when the real answer is that
Google already told you once.

PKCE is used because Google requires it for desktop clients, and because the
loopback redirect is unauthenticated by nature — any local process could
race the callback without it.

SCOPE is read-only: webmasters.readonly. This token can list properties and
read performance data. It cannot submit a sitemap, request indexing, or
change anything.
"""

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from fetch_data import _ssl_context

AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN = "https://oauth2.googleapis.com/token"
SITES = "https://www.googleapis.com/webmasters/v3/sites"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
WANT = "sc-domain:shouldisellyet.com"
DONE_HTML = (b"<!doctype html><meta charset=utf-8>"
             b"<title>Done</title><body style='font:16px system-ui;padding:3rem'>"
             b"<h1>Authorized</h1><p>Return to your terminal. "
             b"You can close this tab.</p>")


# ————— pure pieces —————

def pkce_pair(verifier=None):
    """(verifier, challenge). S256 per RFC 7636 — the challenge is the
    base64url SHA-256 of the verifier, unpadded."""
    verifier = verifier or secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def auth_url(client_id, redirect_uri, challenge, state):
    return AUTH + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
        # See the module docstring: without BOTH of these a repeat run
        # silently returns no refresh token.
        "access_type": "offline",
        "prompt": "consent",
    })


def code_from_redirect(path, expected_state):
    """The ?code= off the loopback redirect. Raises on an error response or
    a state mismatch — the state check is what stops another local process
    feeding us its own authorization code."""
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(path).query)
    if q.get("error"):
        raise ValueError(f"Google returned an error: {q['error'][0]}")
    if q.get("state", [None])[0] != expected_state:
        raise ValueError("state mismatch — ignoring this callback")
    code = q.get("code", [None])[0]
    if not code:
        raise ValueError("no code in the redirect")
    return code


def summarise_properties(sites, want=WANT):
    """(rows, matched) from a sites.list response. Domain properties are
    prefixed sc-domain:; URL-prefix properties are plain URLs, and the two
    are different objects even for the same site."""
    rows = [(s.get("siteUrl", ""), s.get("permissionLevel", "?"))
            for s in (sites or {}).get("siteEntry") or []]
    rows.sort()
    return rows, any(u == want for u, _ in rows)


# ————— the flow —————

class _Handler(http.server.BaseHTTPRequestHandler):
    path_seen = None

    def do_GET(self):
        type(self).path_seen = self.path
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(DONE_HTML)

    def log_message(self, *a):
        pass                      # the server is a one-shot, not a web server


def wait_for_redirect(port, timeout=300):
    """Serve exactly one request on loopback and return its path."""
    _Handler.path_seen = None
    srv = http.server.HTTPServer(("127.0.0.1", port), _Handler)
    srv.timeout = timeout
    t = threading.Thread(target=srv.handle_request, daemon=True)
    t.start()
    t.join(timeout)
    srv.server_close()
    if not _Handler.path_seen:
        raise SystemExit(f"No redirect received within {timeout}s — nothing minted.")
    return _Handler.path_seen


def post_form(url, fields):
    req = urllib.request.Request(
        url, data=urllib.parse.urlencode(fields).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        return json.loads(urllib.request.urlopen(
            req, timeout=60, context=_ssl_context()).read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Token exchange failed ({e.code}): "
                         f"{e.read().decode('utf-8', 'replace')[:400]}")


def list_sites(access_token):
    req = urllib.request.Request(SITES, headers={
        "Authorization": f"Bearer {access_token}"})
    try:
        return json.loads(urllib.request.urlopen(
            req, timeout=60, context=_ssl_context()).read())
    except urllib.error.HTTPError as e:
        print(f"  (sites.list failed: {e.code} "
              f"{e.read().decode('utf-8', 'replace')[:200]})")
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser(description="Mint a Search Console refresh token")
    ap.add_argument("--client-id", default=os.environ.get("GSC_CLIENT_ID", ""))
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true",
                    help="print the URL instead of opening it")
    args = ap.parse_args(argv)

    client_id = args.client_id
    if not client_id:
        raise SystemExit("--client-id is required (or set GSC_CLIENT_ID). "
                         "Create one in Google Cloud → Credentials → OAuth "
                         "client ID → Desktop app.")
    secret = os.environ.get("GSC_CLIENT_SECRET", "")
    if not secret:
        import getpass
        secret = getpass.getpass("GSC_CLIENT_SECRET (not echoed): ").strip()
    if not secret:
        raise SystemExit("No client secret — nothing to exchange with.")

    redirect_uri = f"http://127.0.0.1:{args.port}"
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(16)
    url = auth_url(client_id, redirect_uri, challenge, state)

    print(f"Listening on {redirect_uri} for the redirect.")
    if args.no_browser:
        print("\nOpen this URL:\n" + url + "\n")
    else:
        print("Opening your browser — approve the read-only access.\n")
        webbrowser.open(url)

    path = wait_for_redirect(args.port)
    try:
        code = code_from_redirect(path, state)
    except ValueError as e:
        raise SystemExit(str(e))

    tok = post_form(TOKEN, {
        "client_id": client_id, "client_secret": secret,
        "code": code, "code_verifier": verifier,
        "grant_type": "authorization_code", "redirect_uri": redirect_uri})

    refresh = tok.get("refresh_token")
    access = tok.get("access_token", "")
    if not refresh:
        raise SystemExit(
            "Google returned no refresh_token. That happens when this account "
            "already granted consent — revoke it at "
            "https://myaccount.google.com/permissions and run this again.")

    print("\n" + "=" * 62)
    print("Properties this account can see:")
    rows, matched = summarise_properties(list_sites(access))
    if not rows:
        print("  (none — this account is not on any Search Console property)")
    for u, perm in rows:
        print(f"  {'>>' if u == WANT else '  '} {u}  [{perm}]")
    print()
    if matched:
        print(f"{WANT} IS visible to this account. The probe will work.")
    else:
        print(f"WARNING: {WANT} is NOT visible to this account.\n"
              f"The DNS TXT record proves ownership to whichever Google "
              f"account used it — evidently not this one. Either sign in as "
              f"that account and re-run, or add this one as a user on the "
              f"property. fetch_gsc.py would fail with a 403.")
    print("=" * 62)
    print("\nGSC_REFRESH_TOKEN (store it now; it is not saved anywhere):\n")
    print(refresh)
    print("\nStore all three as repository secrets:")
    print("  gh secret set GSC_CLIENT_ID")
    print("  gh secret set GSC_CLIENT_SECRET")
    print("  gh secret set GSC_REFRESH_TOKEN")
    print("\nIf the OAuth consent screen is still in Testing mode, this token "
          "expires in 7 days. Publish the app first.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
