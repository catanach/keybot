"""Runs once at power-on, before code.py, and decides who owns the filesystem.

CircuitPython hands the board's storage to the USB host by default, which
makes it read-only to the board itself. That is why a firmware deploy from
the webapp failed with "Read-only filesystem": the Pico is always plugged
into something over USB, because that is how it draws power and pretends to
be a keyboard, so it could never write its own code.py.

Remounting here flips that. The board can write, so deploys from the webapp
work, and CIRCUITPY becomes look-but-don't-touch on the Mac.

WAYS BACK, if a deploy ever leaves the board broken. A Pico W has no reset
button, only BOOTSEL, so every one of these is a cable action:

  1. Easiest, while the board still answers: "Hand the drive back to the
     Mac" in the webapp's Settings. That asks the board to write a
     HOST_WRITES file, and on the next power cycle this script leaves the
     filesystem alone, so CIRCUITPY mounts writable on the Mac again.
     Deleting HOST_WRITES puts things back.

  2. If the board no longer answers: unplug and replug it TWICE in quick
     succession, the second time within about a second of the first. That
     enters safe mode, where CircuitPython skips boot.py entirely and
     CIRCUITPY mounts writable, so files can be dragged on by hand.

  3. Last resort: hold BOOTSEL while plugging in. The board comes up as
     RPI-RP2 and a fresh .uf2 can be flashed, which erases everything.

Deliberately not in DEPLOYABLE_FILES in code.py: a broken code.py can be
replaced over the air, but a broken boot.py cannot, so this one only ever
changes over USB.
"""

import os
import storage

# Everything printed here lands in boot_out.txt on the board, which is the
# only way to see what happened during boot. Silence here was hiding a
# failure once already.
try:
    host_writes_requested = "HOST_WRITES" in os.listdir("/")
except Exception as e:
    print("keybot boot: could not list the filesystem ({}), continuing".format(e))
    host_writes_requested = False

if host_writes_requested:
    print("keybot boot: HOST_WRITES found, leaving the filesystem to the Mac")
else:
    try:
        storage.remount("/", readonly=False)
        print("keybot boot: filesystem remounted writable for the board")
    except Exception as e:
        # Carry on booting rather than bricking. The board stays read-only
        # to itself, which is how it behaved before this file existed.
        print("keybot boot: remount refused ({}: {})".format(type(e).__name__, e))
