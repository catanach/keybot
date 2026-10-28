#!/bin/bash
# Proves on real hardware that a long hold no longer makes the board go
# quiet. Runs from the LaunchAgent; the agent shells have no network.
#
# Uses F13 deliberately: it is a real key to the PS5 but does nothing in a
# game, so this cannot type anything into whatever Rosy has focused.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
cd "$(dirname "${BASH_SOURCE[0]}")/.."
TRIGGER="webapp/.fw-verify-requested"
LOG="webapp/fw-verify.log"
APP="http://localhost:8000"
[ -f "$TRIGGER" ] || exit 0
rm -f "$TRIGGER"
{
  echo "=============================================="
  echo "=== fw-verify $(date) ==="

  BUSY=$(curl -s -m 15 "$APP/api/device/status" | grep -o '"running":true')
  if [ -n "$BUSY" ]; then echo "A script is running. Not interfering. Try again later."; exit 0; fi

  echo "--- creating a throwaway script: one 8 second hold on F13 ---"
  CREATED=$(curl -s -m 15 -X POST -H 'Content-Type: application/json' \
    -d '{"name":"zz-hold-check","description":"temporary, issue 21 hardware check","steps":[["press","F13",8]]}' \
    "$APP/api/scripts")
  echo "$CREATED"
  ID=$(echo "$CREATED" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
  [ -z "$ID" ] && { echo "could not create the script"; exit 0; }

  echo "--- starting it, then polling once a second while the key is held ---"
  curl -s -m 20 -X POST -H 'Content-Type: application/json' -d '{"times":1}' "$APP/api/scripts/$ID/run"; echo
  ANSWERED=0; MISSED=0
  for i in $(seq 1 11); do
    sleep 1
    S=$(curl -s -m 3 "$APP/api/device/status" 2>/dev/null)
    if echo "$S" | grep -q '"running"'; then
      ANSWERED=$((ANSWERED+1))
      echo "  ${i}s: answered  $(echo "$S" | python3 -c "import json,sys; d=json.load(sys.stdin); print('running=%s step=%s mem=%s' % (d.get('running'), d.get('current_step'), d.get('mem_free')))" 2>/dev/null)"
    else
      MISSED=$((MISSED+1)); echo "  ${i}s: NO ANSWER"
    fi
  done
  echo "--- result: answered $ANSWERED of 11, missed $MISSED ---"

  echo "--- the other half: can Stop cut a hold short? ---"
  curl -s -m 20 -X POST -H 'Content-Type: application/json' -d '{"times":1}' "$APP/api/scripts/$ID/run"; echo
  sleep 2
  echo "  2s in, asking it to stop:"
  STOPPED_AT=$(date +%s)
  curl -s -m 10 -X POST -H 'Content-Type: application/json' -d '{}' "$APP/api/device/stop"; echo
  for i in $(seq 1 8); do
    sleep 1
    S=$(curl -s -m 3 "$APP/api/device/status" 2>/dev/null)
    RUN=$(echo "$S" | python3 -c "import json,sys; print(json.load(sys.stdin).get('running'))" 2>/dev/null)
    echo "  +${i}s after stop: running=$RUN"
    if [ "$RUN" = "False" ]; then
      echo "  stopped $(( $(date +%s) - STOPPED_AT ))s after the request, with about 6s of hold left to go"
      break
    fi
  done

  echo "--- cleaning up the throwaway script ---"
  curl -s -m 15 -X DELETE "$APP/api/scripts/$ID"; echo
  curl -s -m 15 "$APP/api/device/status" | head -c 300; echo
  echo "=== end fw-verify ==="
} >> "$LOG" 2>&1
tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
