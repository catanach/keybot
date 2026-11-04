#!/bin/bash
# Deploys the firmware to CIRCUITPY over USB, from YOUR Terminal.
#
# Why Terminal: macOS sandboxes both the LaunchAgent and the agent shells out
# of removable volumes (file reads return "Operation not permitted", diskutil
# returns -69464). Terminal is the only process here that can read, write and
# eject the volume.
#
#   cd ~/src/keybot && bash webapp/fix-circuitpy.sh
#
# diskutil repairVolume is deliberately not attempted: the Claude bridge VM
# holds the volume mounted and dissents the unmount it needs (-69673).
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
FW=webapp/.fw-code.py
V=/Volumes/CIRCUITPY

say() { printf '\n== %s\n' "$*"; }

[ -f "$FW" ] || { echo "missing $FW -- nothing to deploy"; exit 1; }
[ -d "$V" ] || { echo "No CIRCUITPY. Plug the Pico into this Mac and rerun."; exit 1; }

say "the real directory, as your Mac sees it"
ls -la "$V"

DUPES=$(ls -1 "$V" | grep -cx 'code\.py')
say "entries named exactly code.py: $DUPES"
if [ "$DUPES" -gt 1 ]; then
  echo "   Genuinely duplicated. Clearing both entries before rewriting."
  for i in 1 2 3 4; do
    [ "$(ls -1 "$V" | grep -cx 'code\.py')" -eq 0 ] && break
    rm -f "$V"/code.py 2>/dev/null
    sync
  done
  LEFT=$(ls -1 "$V" | grep -cx 'code\.py')
  echo "   entries left: $LEFT"
  if [ "$LEFT" -gt 0 ]; then
    echo
    echo "The directory is damaged in a way rm cannot clear, and repairVolume"
    echo "cannot run while the bridge VM holds the volume. Two ways forward:"
    echo "  a) remove /Volumes/CIRCUITPY from the folders shared with Claude in"
    echo "     the desktop app, then rerun 'diskutil repairVolume disk4s1'"
    echo "  b) reflash: BOOTSEL -> lib/universal_flash_nuke.uf2"
    echo "              -> lib/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.2.1.uf2"
    exit 1
  fi
fi

say "clearing write leftovers"
rm -f "$V"/.code.py.*.tmp "$V"/code_new.py "$V"/._code_new.py 2>/dev/null
echo "   done"

say "restoring anything missing (boot.py is intentionally never copied)"
for f in keycodes.py script_runner.py settings.toml; do
  if [ ! -s "$V/$f" ]; then echo "   $f missing -> restoring"; cp "src/$f" "$V/$f"; fi
done
if [ ! -d "$V/lib/adafruit_hid" ] || [ ! -d "$V/lib/adafruit_httpserver" ]; then
  echo "   lib missing -> restoring"
  mkdir -p "$V/lib"; cp -R lib/adafruit_hid lib/adafruit_httpserver "$V/lib/"
fi
echo "   checked"

say "writing code.py"
cp "$FW" "$V"/code.py || { echo "write failed"; exit 1; }
sync

say "reading it back off the drive"
WANT=$(md5 -q "$FW"); GOT=$(md5 -q "$V"/code.py)
echo "   want $WANT"
echo "   got  $GOT"
ls -l "$V"/code.py
[ "$WANT" = "$GOT" ] || { echo "CHECKSUM MISMATCH -- do not unplug, rerun this."; exit 1; }
echo "   match"

say "ejecting so macOS flushes"
# Skipping this lost the last two deploys: macOS buffers FAT writes and an
# unplug without an eject discards them.
diskutil eject CIRCUITPY || { echo "eject failed -- eject from Finder before unplugging"; exit 1; }

say "done"
echo "Firmware on the board and flushed."
echo "Now move the Pico to the PS5. That power cycle starts the new code."
