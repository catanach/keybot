"""Reads the Pico's firmware source (keycodes.py, script_runner.py and
code.py) from the repo's src/ folder, which the webapp is given read-only
access to as a Docker volume, and does a basic sanity check before any of it
is sent to the device.
"""

import ast
import os
from pathlib import Path

FIRMWARE_DIR = Path(os.environ.get("KEYBOT_FIRMWARE_DIR", "/firmware_src"))
# The order matters, because the files are sent one at a time and the board
# restarts after each one: there is a moment when they do not all match, and
# the board has to boot anyway.
#
# keycodes.py first: code.py imports it, and imports it in a way that
# survives the file not being there yet, so it is safe either way round --
# but sending it first means the board is only ever missing it once.
#
# script_runner.py before code.py: old code.py with new script_runner.py is
# fine, because the new arguments are optional. New code.py with old
# script_runner.py is not: it passes an argument the old one does not take,
# the import fails outside the error handler, and the board reboot-loops
# with no server.
DEPLOY_FILES = ["keycodes.py", "script_runner.py", "code.py"]


class FirmwareError(Exception):
    """Raised when the firmware source can't be read, or doesn't even parse
    as valid Python. The message is meant to be shown to the user."""


def load_firmware_files() -> dict:
    """Reads every file in DEPLOY_FILES and checks each one parses as valid
    Python before returning them. This catches typos and broken syntax --
    it can't catch a logic mistake that only shows up once the code runs."""
    files = {}
    for name in DEPLOY_FILES:
        path = FIRMWARE_DIR / name
        try:
            content = path.read_text()
        except OSError as e:
            raise FirmwareError(f"can't read {name} from the repo: {e}")
        try:
            ast.parse(content, filename=name)
        except SyntaxError as e:
            raise FirmwareError(f"{name} has a syntax error and won't be sent: {e}")
        files[name] = content
    return files
