#!/bin/bash
# Runs ./deploy.sh over USB, from the LaunchAgent, because the agent shells
# cannot reach /Volumes/CIRCUITPY at all. Requires an explicit trigger file,
# so it never writes to the board on its own.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH"
cd "$(dirname "${BASH_SOURCE[0]}")/.."
TRIGGER="webapp/.usb-deploy-requested"
LOG="webapp/usb-deploy.log"
[ -f "$TRIGGER" ] || exit 0
{
  echo "=============================================="
  echo "=== usb-deploy $(date) ==="
  echo "--- before ---"
  ls -la /Volumes/CIRCUITPY 2>&1 | head -15
  echo "--- running ./deploy.sh ---"
  ./deploy.sh 2>&1
  echo "--- after ---"
  ls -la /Volumes/CIRCUITPY 2>&1 | head -15
  echo "--- lib on board ---"
  ls /Volumes/CIRCUITPY/lib 2>&1
  echo "--- sizes we care about ---"
  for f in boot.py code.py script_runner.py keycodes.py settings.toml; do
    printf "  %-18s %s\n" "$f" "$(wc -c < /Volumes/CIRCUITPY/$f 2>/dev/null || echo MISSING)"
  done
  echo "=== end usb-deploy ==="
} >> "$LOG" 2>&1
rm -f "$TRIGGER"
tail -n 400 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
