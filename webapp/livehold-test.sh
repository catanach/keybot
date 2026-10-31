#!/bin/bash
# Verifies the new /key_down and /key_up on the real board, plus the
# watchdog that lets go of a key whose release never arrives.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[ -f webapp/.livehold-requested ] || exit 0
rm -f webapp/.livehold-requested
LOG="webapp/livehold-test.log"
DEV=$(python3 -c "import json;print(json.load(open('webapp/data/settings.json'))['device_url'])")
{
  echo "=============================================="
  echo "=== livehold-test $(date) ==="

  echo "--- 1. do the new routes exist? ---"
  printf "  /key_down no key -> "; curl -s -o /dev/null -w "http %{http_code}\n" -m 8 "$DEV/key_down"
  printf "  /key_up   no key -> "; curl -s -o /dev/null -w "http %{http_code}\n" -m 8 "$DEV/key_up"

  echo "--- 2. hold W down for 5 seconds, the way the recorder now does ---"
  T0=$(python3 -c 'import time;print(time.time())')
  printf "  key_down W -> "; curl -s -m 8 "$DEV/key_down?key=W"; echo
  for i in 1 2 3 4 5; do
    sleep 1
    printf "    +%ss board still answering: " "$i"
    curl -s -m 3 "$DEV/status" | python3 -c "import json,sys; print(json.load(sys.stdin).get('running'))" 2>/dev/null || echo "NO ANSWER"
  done
  printf "  key_up W -> "; curl -s -m 8 "$DEV/key_up?key=W"; echo
  T1=$(python3 -c 'import time;print(time.time())')
  python3 -c "print('  W was down for about %.1f seconds' % ($T1 - $T0))"

  echo "--- 3. the watchdog: press F13 and never release it ---"
  echo "    F13 is harmless in a game, so a 30s hold does nothing visible."
  printf "  key_down F13 -> "; curl -s -m 8 "$DEV/key_down?key=F13"; echo
  for i in $(seq 1 14); do
    sleep 3
    FAULT=$(curl -s -m 3 "$DEV/status" | python3 -c "import json,sys; print(json.load(sys.stdin).get('last_fault'))" 2>/dev/null)
    echo "    +$((i*3))s last_fault: $FAULT"
    case "$FAULT" in
      *"timed out"*) echo "  the watchdog let go of it at about $((i*3))s"; break ;;
    esac
  done
  printf "  belt and braces, releasing F13 anyway -> "; curl -s -m 8 "$DEV/key_up?key=F13"; echo
  curl -s -m 8 "$DEV/status" | head -c 300; echo
  echo "=== end livehold-test ==="
} >> "$LOG" 2>&1
tail -n 200 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
