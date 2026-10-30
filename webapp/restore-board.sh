#!/bin/bash
# Puts the board's stored program back to a real script after a test, and
# repairs settings.json if a throwaway run left last_run pointing at a
# script that no longer exists. Pushes straight to the board, because the
# webapp only sends a program as part of starting a run.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[ -f webapp/.restore-board-requested ] || exit 0
rm -f webapp/.restore-board-requested
WANT="$(cat webapp/.restore-board-target 2>/dev/null)"
LOG="webapp/hold-test.log"
{
  echo "--- restore-board $(date) ---"
  [ -z "$WANT" ] && { echo "no target given"; exit 0; }
  STEPS=$(python3 -c "
import json
d=json.load(open('webapp/data/scripts/$WANT.json'))
print(json.dumps(d['steps']))
" 2>/dev/null)
  [ -z "$STEPS" ] && { echo "could not read script $WANT"; exit 0; }
  DEV=$(python3 -c "import json;print(json.load(open('webapp/data/settings.json'))['device_url'])")
  echo "pushing $WANT to $DEV/update"
  curl -s -m 15 -X POST -H 'Content-Type: application/json' -d "$STEPS" "$DEV/update"; echo
  python3 - <<'EOF'
import json
p = "webapp/data/settings.json"
s = json.load(open(p))
want = open("webapp/.restore-board-target").read().strip()
s["last_run"] = {"script_id": want, "times": 1, "part_names": []}
json.dump(s, open(p, "w"), indent=2)
print("settings.json last_run set back to", want)
EOF
  curl -s -m 15 "$DEV/status" | head -c 300; echo
  echo "--- end restore-board ---"
} >> "$LOG" 2>&1
