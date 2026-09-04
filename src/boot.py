"""Runs once at power-on, before code.py, and decides who owns the filesystem.

CircuitPython hands the board's storage to the USB host by default, which
makes it read-only to the board itself. That is why a firmware deploy from
the webapp failed with "Read-only filesystem": the Pico is always plugged
into something over USB, because that is how it draws power and pretends to
be a keyboard, so it could never write its own code.py.

Remounting here flips that. The board can write, so deploys from the webapp
work, and CIRCUITPY becomes look-but-don't-touch on the Mac.

TWO WAYS BACK, if a deploy ever leaves the board broken:

  1. Press the reset button twice in quick succession. That boots into safe
     mode, where CircuitPython skips boot.py entirely, so CIRCUITPY mounts
     writable on the Mac exactly as it used to and files can be dragged on.

  2. While in safe mode, create an empty file called HOST_WRITES on
     CIRCUITPY. This script then leaves the filesystem alone on every
     subsequent boot, so the board stays Mac-writable until that file is
     deleted. Use this to work on the board by hand for a while.

Deliberately not in DEPLOYABLE_FILES in code.py: a broken code.py can be
replaced over the air, but a broken boot.py cannot, so this one only ever
changes over USB.
"""

import os
import storage

try:
    host_writes_requested = "HOST_WRITES" in os.listdir("/")
except Exception:
    host_writes_requested = False

if not host_writes_requested:
    try:
        storage.remount("/", readonly=False)
    except Exception:
        # If the remount is refused, carry on booting rather than bricking.
        # The board stays read-only to itself, exactly as it was before.
        pass
