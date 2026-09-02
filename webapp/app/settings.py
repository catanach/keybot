"""Small persisted settings file: which device (the local dev server or the
real Pico) this webapp talks to, and what was last told to run on it (so a
firmware deploy can put the same thing back afterward).
"""

import json
import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("KEYBOT_DATA_DIR", "/data"))
SETTINGS_FILE = DATA_DIR / "settings.json"

# host.docker.internal lets a container reach a server running directly on
# your Mac (like dev/server.py). It only works for things on your own
# machine -- the real Pico, being a separate device on your network, uses
# its own IP address instead, e.g. http://192.168.10.22:5000
DEFAULT_DEVICE_URL = "http://host.docker.internal:8085"


def _read() -> dict:
    if SETTINGS_FILE.exists():
        try:
            return json.loads(SETTINGS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write(data: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps(data, indent=2))


def get_device_url() -> str:
    return _read().get("device_url", DEFAULT_DEVICE_URL)


def set_device_url(url: str) -> None:
    data = _read()
    data["device_url"] = url.rstrip("/")
    _write(data)


def get_last_run():
    """The script_id/times that were last told to run, so a firmware
    deploy can resume the same thing afterward. None if nothing has run
    yet, or it was cleared by a manual stop."""
    return _read().get("last_run")


def set_last_run(script_id: str, times) -> None:
    data = _read()
    data["last_run"] = {"script_id": script_id, "times": times}
    _write(data)


def clear_last_run() -> None:
    data = _read()
    data.pop("last_run", None)
    _write(data)
