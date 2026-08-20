#!/usr/bin/env bash
# Force Meta to re-scrape a list of URLs, clearing previews cached before the
# 2026-08-19 withdrawal fix. Meta is the only platform with a real
# programmatic purge — see INVALIDATION_RUNBOOK.md for the rest.
#
#   FB_TOKEN=... ./scripts/rescrape-og.sh scripts/og-priority-urls.txt
#
# Dry by default: prints what it would do and exits. Pass --go to send.
# Written to be run by a human with the token in their own shell; nothing
# here stores or logs it.
set -euo pipefail

URLS="${1:-scripts/og-priority-urls.txt}"
GO="${2:-}"

[ -f "$URLS" ] || { echo "no URL file at $URLS" >&2; exit 1; }
if [ -z "${FB_TOKEN:-}" ] && [ "$GO" = "--go" ]; then
  echo "FB_TOKEN is not set. Get an app access token from developers.facebook.com" >&2
  exit 1
fi

n=$(grep -cve '^\s*$' -e '^\s*#' "$URLS")
echo "$n URL(s) from $URLS"

if [ "$GO" != "--go" ]; then
  echo "DRY RUN — nothing sent. Re-run with --go to submit."
  grep -ve '^\s*$' -e '^\s*#' "$URLS" | head -10 | sed 's/^/  /'
  [ "$n" -gt 10 ] && echo "  … and $((n - 10)) more"
  exit 0
fi

ok=0; fail=0
while IFS= read -r url; do
  case "$url" in ''|\#*) continue ;; esac
  # Meta rate-limits aggressively; one per second is well inside it.
  code=$(curl -sS -o /tmp/rescrape.out -w '%{http_code}' -X POST \
    "https://graph.facebook.com/v21.0/?id=${url}&scrape=true&access_token=${FB_TOKEN}" || echo 000)
  if [ "$code" = "200" ]; then
    ok=$((ok+1)); printf '  ok   %s\n' "$url"
  else
    fail=$((fail+1)); printf '  FAIL %s (HTTP %s) %s\n' "$url" "$code" "$(head -c 120 /tmp/rescrape.out)"
  fi
  sleep 1
done < "$URLS"

echo "re-scraped $ok, failed $fail"
echo "Verify three of them in the Sharing Debugger before trusting the batch."
