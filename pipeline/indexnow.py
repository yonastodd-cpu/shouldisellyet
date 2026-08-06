"""
ShouldISellYet — IndexNow submission.

Tells Bing (and every other IndexNow participant) which URLs changed, instead
of waiting to be crawled. That wait is the whole problem for this site: a new
domain with no inbound links has no natural crawl path, so pages that change
monthly can go unnoticed indefinitely.

Run after a data refresh, from the workflow:

    python3 pipeline/indexnow.py --old /tmp/old_zips --new web/data/zips

WHAT IT SUBMITS, and why not everything: only the ZIPs whose verdict actually
changed, plus the handful of pages that change every refresh (homepage, the
state hub for each changed ZIP, the markets index). Submitting all 22k every
month would be both untrue — most pages didn't change — and a good way to
look like a spammer from a domain with no authority yet. SUBMIT_CAP is a
backstop for the month a threshold change flips half the country.

The key is public by design: IndexNow verifies ownership by fetching
KEY_LOCATION and checking it contains this exact string. There is nothing to
protect — anyone can read it off the site.

Failure is never fatal. A search-engine ping that breaks a data deploy would
be a bad trade, so every error path returns quietly.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

SITE = "https://shouldisellyet.com"
HOST = "shouldisellyet.com"
KEY = "2bf8b6d4848a4fd1ae1bdd2d9725cf08"
KEY_LOCATION = f"{SITE}/{KEY}.txt"

# api.indexnow.org fans out to every participating engine (Bing, Yandex,
# Seznam, Naver). Bing's own endpoint additionally requires the domain to be
# verified in Webmaster Tools, and 403s until it is — so the shared endpoint
# is the one worth depending on.
ENDPOINT = "https://api.indexnow.org/indexnow"

# One threshold move can reprice the whole country. Past this many changed
# ZIPs the month is a methodology event, not news, and blasting it would read
# as spam — so submit the core pages and let the sitemap carry the rest.
SUBMIT_CAP = 2000


def verdicts(dirpath):
    """{zip: level} across every state file in a zips/ directory."""
    out = {}
    for f in Path(dirpath).glob("*.json"):
        try:
            for z, e in json.loads(f.read_text()).items():
                out[z] = e.get("l")
        except (OSError, ValueError):
            continue
    return out


def changed_zips(old_dir, new_dir):
    """ZIPs whose verdict differs, plus ZIPs that are newly covered.

    A ZIP that vanished is deliberately NOT submitted: its page is gone, and
    pointing a crawler at a 404 helps nobody.
    """
    old, new = verdicts(old_dir), verdicts(new_dir)
    return sorted(z for z, lvl in new.items() if old.get(z) != lvl)


def zip_state(new_dir):
    """{zip: STATE} so a changed ZIP can also refresh its state hub."""
    out = {}
    for f in Path(new_dir).glob("*.json"):
        try:
            for z in json.loads(f.read_text()):
                out[z] = f.stem
        except (OSError, ValueError):
            continue
    return out


def build_urls(changed, z2s):
    """Changed ZIP pages + the hubs that list them + the always-changing pages."""
    urls = [f"{SITE}/", f"{SITE}/zip/"]
    if len(changed) <= SUBMIT_CAP:
        urls += [f"{SITE}/zip/{z}/" for z in changed]
        for st in sorted({z2s[z] for z in changed if z in z2s}):
            urls.append(f"{SITE}/zip/{st}/")
    return urls


def submit(urls, dry_run=False):
    payload = {"host": HOST, "key": KEY, "keyLocation": KEY_LOCATION, "urlList": urls}
    if dry_run:
        print(f"[dry-run] would submit {len(urls)} URLs to {ENDPOINT}")
        for u in urls[:10]:
            print("   ", u)
        if len(urls) > 10:
            print(f"    … and {len(urls)-10} more")
        return True
    req = urllib.request.Request(
        ENDPOINT, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            # 200 accepted, 202 accepted-pending-key-validation. Both are wins.
            print(f"IndexNow: submitted {len(urls)} URLs — HTTP {r.status}")
            return True
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")[:300]
        print(f"IndexNow: HTTP {e.code} — {body}")
        # 403 SiteVerificationNotCompleted is the expected answer until the
        # domain is verified in Bing Webmaster Tools. Say so rather than
        # leaving a bare code to be puzzled over later.
        if e.code == 403 and "Verification" in body:
            print("  → verify the domain in Bing Webmaster Tools; "
                  f"the key file is already live at {KEY_LOCATION}")
        return False
    except Exception as e:
        print(f"IndexNow: submission failed — {e}")
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--old", help="previous web/data/zips snapshot")
    ap.add_argument("--new", default="web/data/zips")
    ap.add_argument("--all-core", action="store_true",
                    help="submit only the core pages (no diff needed)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if args.all_core or not args.old:
        urls = [f"{SITE}/", f"{SITE}/zip/", f"{SITE}/press.html", f"{SITE}/report.html"]
        print(f"IndexNow: core pages only ({len(urls)})")
    else:
        changed = changed_zips(args.old, args.new)
        z2s = zip_state(args.new)
        urls = build_urls(changed, z2s)
        print(f"IndexNow: {len(changed)} ZIP verdicts changed"
              + (f" — over the {SUBMIT_CAP} cap, submitting core pages only"
                 if len(changed) > SUBMIT_CAP else ""))
    submit(urls, args.dry_run)
    return 0        # never fail the build over a search-engine ping


if __name__ == "__main__":
    sys.exit(main())
