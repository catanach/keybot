#!/bin/bash
# Restores a freshly flashed CIRCUITPY drive: libraries, keycodes,
# script_runner, wifi settings, and the current firmware.
#
# Run from YOUR Terminal, after reflashing CircuitPython 10.2.1. macOS
# sandboxes the LaunchAgent and the agent shells out of removable volumes,
# so Terminal is the only process that can do this.
#
#   cd ~/src/keybot && bash webapp/restore-circuitpy.sh
#
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
FW=webapp/.fw-code.py
V=/Volumes/CIRCUITPY

say() { printf '\n== %s\n' "$*"; }
fail() { printf '\n!! %s\n' "$*"; exit 1; }

[ -f "$FW" ] || fail "missing $FW"
[ -d "$V" ] || fail "No CIRCUITPY. Flash CircuitPython first, then rerun."

say "what a fresh flash left behind"
ls -la "$V"
if [ -s "$V/code.py" ] || [ -d "$V/lib/adafruit_hid" ]; then
  echo
  echo "   This drive is not empty, so it may not be a fresh flash."
  echo "   That is fine if you meant to overwrite it; everything below is a"
  echo "   plain copy and will replace what is there."
fi

say "libraries"
mkdir -p "$V/lib"
cp -R lib/adafruit_hid "$V/lib/" || fail "adafruit_hid copy failed"
cp -R lib/adafruit_httpserver "$V/lib/" || fail "adafruit_httpserver copy failed"
echo "   adafruit_hid, adafruit_httpserver"

say "wifi settings"
# Copied file to file. Never read, never printed.
cp src/settings.toml "$V"/settings.toml || fail "settings.toml copy failed"
echo "   settings.toml ($(wc -c < "$V"/settings.toml | tr -d ' ') bytes)"

say "modules"
cp src/keycodes.py "$V"/keycodes.py || fail "keycodes.py copy failed"
cp src/script_runner.py "$V"/script_runner.py || fail "script_runner.py copy failed"
echo "   keycodes.py, script_runner.py"

say "firmware"
cp "$FW" "$V"/code.py || fail "code.py copy failed"
echo "   code.py"

# boot.py is deliberately NOT copied. With it present the board claims the
# filesystem and the drive stops being writable from this Mac.

sync

say "verifying every file against its source"
ok=1
check() {
  local want got
  want=$(md5 -q "$1"); got=$(md5 -q "$2" 2>/dev/null || echo MISSING)
  if [ "$want" = "$got" ]; then printf '   ok   %s\n' "$(basename "$2")"
  else printf '   BAD  %s (want %s, got %s)\n' "$(basename "$2")" "$want" "$got"; ok=0; fi
}
check "$FW" "$V"/code.py
check src/script_runner.py "$V"/script_runner.py
check src/keycodes.py "$V"/keycodes.py
check src/settings.toml "$V"/settings.toml
for f in lib/adafruit_hid/*.mpy; do check "$f" "$V/lib/adafruit_hid/$(basename "$f")"; done
for f in lib/adafruit_httpserver/*.mpy; do check "$f" "$V/lib/adafruit_httpserver/$(basename "$f")"; done
[ "$ok" = 1 ] || fail "something did not land. Do not unplug. Rerun this script."

say "flushing"
# A plain unplug loses buffered FAT writes, which is how two earlier deploys
# vanished. The bridge VM dissents a polite unmount, so force it.
diskutil unmount force "$V" >/dev/null 2>&1 \
  || diskutil eject CIRCUITPY >/dev/null 2>&1 \
  || fail "could not unmount. Eject from Finder before unplugging."
echo "   unmounted, writes flushed"

say "done"
echo "Now unplug the Pico and plug it into the PS5."
echo "Expect /status to report fw_version 2026.11.04-livekeys-1"
