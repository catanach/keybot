#!/bin/bash
# Wipes the Pico's flash and reinstalls CircuitPython 10.2.1.
#
# Needed when the CIRCUITPY FAT directory is corrupt: CircuitPython and macOS
# then disagree about what is on the drive (two directory entries both named
# code.py, the board loading a code.py that is not the one written), and no
# amount of rewriting files fixes it. repairVolume cannot run because the
# Claude bridge VM dissents the unmount it needs.
#
# Run from YOUR Terminal:
#   cd ~/src/keybot && bash webapp/flash-circuitpy.sh
#
# Hold BOOTSEL while plugging the Pico into this Mac first. Writing a .uf2
# makes the board reboot part way through the copy, so "device not configured"
# at the end of a copy is normal and is treated as success.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")/.."
NUKE=lib/universal_flash_nuke.uf2
CP=lib/adafruit-circuitpython-raspberry_pi_pico_w-en_US-10.2.1.uf2
B=/Volumes/RPI-RP2

say() { printf '\n== %s\n' "$*"; }
fail() { printf '\n!! %s\n' "$*"; exit 1; }

[ -f "$NUKE" ] || fail "missing $NUKE"
[ -f "$CP" ] || fail "missing $CP"

wait_for() {
  local path=$1 secs=$2 i
  for ((i=0; i<secs; i++)); do [ -d "$path" ] && return 0; sleep 1; done
  return 1
}

say "waiting up to 60s for the bootloader drive"
echo "   hold BOOTSEL and plug the Pico into this Mac if you have not already"
wait_for "$B" 60 || fail "RPI-RP2 never appeared. Hold BOOTSEL down while plugging in."
echo "   found $B"

say "step 1 of 2: wiping the flash"
cp "$NUKE" "$B"/ 2>&1 || echo "   (copy ended early, which is expected)"
sleep 3
echo "   waiting for the board to come back as a bootloader"
wait_for "$B" 90 || fail "the board did not reappear. Unplug, hold BOOTSEL, plug back in, rerun."
echo "   back"
sleep 2

say "step 2 of 2: installing CircuitPython 10.2.1"
cp "$CP" "$B"/ 2>&1 || echo "   (copy ended early, which is expected)"
sleep 3

say "waiting up to 90s for a fresh CIRCUITPY"
wait_for /Volumes/CIRCUITPY 90 || fail "CIRCUITPY never appeared. Unplug and replug, then check Finder."
echo "   mounted"
ls -la /Volumes/CIRCUITPY

say "done"
echo "The drive is clean. Now restore it:"
echo "  bash webapp/restore-circuitpy.sh"
