#!/bin/bash
# One-shot firmware deploy over the air, run by the LaunchAgent because the
# agent shells have no network interfaces and cannot reach the webapp on
# localhost. Requires an explicit trigger file, so it never deploys on its
# own. Removes the trigger whatever happens, so a failure does not retry
# forever; the agent reads the log and decides.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
cd "$(dirname "${BASH_SOURCE[0]}")/.."
TRIGGER="webapp/.fw-deploy-requested"
LOG="webapp/fw-deploy.log"
APP="http://localhost:8000"
[ -f "$TRIGGER" ] || exit 0
rm -f "$TRIGGER"
{
  echo "=============================================="
  echo "=== fw-deploy $(date) ==="
  echo "--- board before ---"
  curl -s -m 15 "$APP/api/device/status" | head -c 500; echo
  echo "--- asking for the deploy ---"
  curl -s -m 20 -X POST -H 'Content-Type: application/json' -d '{}' "$APP/api/device/deploy"; echo
  for i in $(seq 1 60); do
    sleep 3
    PHASE=$(curl -s -m 10 "$APP/api/device/deploy/status" 2>/dev/null)
    echo "  $PHASE"
    case "$PHASE" in
      *'"phase":"done"'*)  echo "RESULT: done"; break ;;
      *'"phase":"error"'*) echo "RESULT: error"; break ;;
    esac
  done
  echo "--- board after, giving it time to come back ---"
  for i in $(seq 1 10); do
    sleep 5
    OUT=$(curl -s -m 10 "$APP/api/device/status" 2>/dev/null)
    if echo "$OUT" | grep -q '"running"'; then echo "$OUT" | head -c 500; echo; break; fi
    echo "  not answering yet ($i)"
  done
  echo "=== end fw-deploy ==="
} >> "$LOG" 2>&1
tail -n 300 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
