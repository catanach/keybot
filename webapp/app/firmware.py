"""Reads the Pico's firmware source (code.py, script_runner.py) from the
repo's src/ folder, which the webapp is given read-only access to as a
Docker volume, and does a basic sanity check before it's ever sent to the
device.
"""

import ast
import os
from pathlib import Path

FIRMWARE_DIR = Path(os.environ.get("KEYBOT_FIRMWARE_DIR", "/firmware_src"))
DEPLOY_FILES = ["code.py", "script_runner.py"]


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
