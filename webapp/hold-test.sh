#!/bin/bash
# One-shot: make the board hold W for 5 seconds, through the same path a
# recorded hold uses. /press cannot do this (MAX_HOLD caps it at 1s), so
# this pushes a one-step program and runs it.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
cd "$(dirname "${BASH_SOURCE[0]}")/.."
TRIGGER="webapp/.hold-test-requested"
LOG="webapp/hold-test.log"
APP="http://localhost:8000"
[ -f "$TRIGGER" ] || exit 0
rm -f "$TRIGGER"
{
  echo "=============================================="
  echo "=== hold-test $(date) ==="
  BUSY=$(curl -s -m 15 "$APP/api/device/status" | grep -o '"running":true')
  if [ -n "$BUSY" ]; then echo "A script is running. Not interfering."; exit 0; fi

  CREATED=$(curl -s -m 15 -X POST -H 'Content-Type: application/json' \
    -d '{"name":"zz-hold-W-5s","description":"temporary, issue 21 hold check","steps":[["press","W",5]]}' \
    "$APP/api/scripts")
  ID=$(echo "$CREATED" | python3 -c "import json,sys; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
  [ -z "$ID" ] && { echo "could not create the script: $CREATED"; exit 0; }
  echo "script $ID: [[\"press\",\"W\",5]]"

  echo "--- starting; W goes down now ---"
  T0=$(python3 -c 'import time; print(time.time())')
  curl -s -m 20 -X POST -H 'Content-Type: application/json' -d '{"times":1}' "$APP/api/scripts/$ID/run"; echo
  DOWN_AT=""
  UP_AT=""
  for i in $(seq 1 40); do
    sleep 0.25
    S=$(curl -s -m 3 "$APP/api/device/status" 2>/dev/null)
    RUN=$(echo "$S" | python3 -c "import json,sys; print(json.load(sys.stdin).get('running'))" 2>/dev/null)
    NOW=$(python3 -c 'import time; print(time.time())')
    if [ "$RUN" = "True" ] && [ -z "$DOWN_AT" ]; then DOWN_AT=$NOW; fi
    if [ "$RUN" = "False" ] && [ -n "$DOWN_AT" ] && [ -z "$UP_AT" ]; then UP_AT=$NOW; break; fi
  done
  if [ -n "$DOWN_AT" ] && [ -n "$UP_AT" ]; then
    python3 -c "print('--- the key was down for about %.1f seconds (asked for 5) ---' % ($UP_AT - $DOWN_AT))"
  else
    echo "--- could not bracket the run: down=$DOWN_AT up=$UP_AT ---"
  fi
  curl -s -m 15 "$APP/api/device/status" | head -c 320; echo

  echo "--- cleaning up ---"
  curl -s -m 15 -X DELETE "$APP/api/scripts/$ID" > /dev/null
  # Leave the board holding a script Rosy recognises rather than the
  # throwaway, since the board keeps the last program across a power cycle.
  LAST=$(python3 -c "import json; print(json.load(open('webapp/data/settings.json'))['last_run']['script_id'])" 2>/dev/null)
  if [ -n "$LAST" ]; then
    curl -s -m 20 "$APP/api/scripts/$LAST/preview" > /dev/null 2>&1
    echo "board's stored program restored to your last-run script ($LAST)"
  fi
  echo "=== end hold-test ==="
} >> "$LOG" 2>&1
tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
