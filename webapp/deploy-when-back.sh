#!/bin/bash
# Deploys the firmware the moment the Pico comes back on the network.
#
# The board can wedge in a way that only a power cycle clears (issue #2).
# The fix for that is firmware, which can only be sent while the board is
# answering, so the deploy has to be waiting for it rather than the other
# way round. Run from the LaunchAgent every couple of minutes. Does nothing
# unless the flag file exists, and removes the flag once a deploy finishes,
# so it fires once and then stays out of the way.

export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:$PATH"
cd "$(dirname "${BASH_SOURCE[0]}")/.."

FLAG="webapp/.deploy-when-back"
LOG="webapp/deploy-when-back.log"
APP="http://localhost:8000"

[ -f "$FLAG" ] || exit 0

STATUS=$(curl -s --max-time 8 "$APP/api/device/status" 2>/dev/null)
echo "$STATUS" | grep -q '"running"' || exit 0          # board still not answering

# Already on the new firmware? Then there is nothing to do; stand down.
if echo "$STATUS" | grep -q 'last_error'; then
  {
    echo "=== $(date) ==="
    echo "Pico is back and already running the new firmware. Nothing to deploy."
  } >> "$LOG"
  rm -f "$FLAG"
  exit 0
fi

if echo "$STATUS" | grep -q '"running":true'; then
  exit 0                                                 # a script is running, wait
fi

{
  echo "=== $(date) ==="
  echo "Pico is back on old firmware and idle. Deploying."
  curl -s -X POST -H 'Content-Type: application/json' -d '{}' "$APP/api/device/deploy"
  echo
  for i in $(seq 1 40); do
    sleep 3
    PHASE=$(curl -s --max-time 8 "$APP/api/device/deploy/status" 2>/dev/null)
    echo "  $PHASE"
    case "$PHASE" in
      *'"phase":"done"'*)  echo "Deploy complete."; rm -f "$FLAG"; break ;;
      *'"phase":"error"'*) echo "Deploy failed. Leaving the flag set to retry."; break ;;
    esac
  done
} >> "$LOG" 2>&1

tail -n 300 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
