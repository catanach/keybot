"""Small persisted settings file -- currently just which device (the local
dev server or the real Pico) this webapp talks to.
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


def get_device_url() -> str:
    if SETTINGS_FILE.exists():
        try:
            data = json.loads(SETTINGS_FILE.read_text())
            return data.get("device_url", DEFAULT_DEVICE_URL)
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_DEVICE_URL


def set_device_url(url: str) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_FILE.write_text(json.dumps({"device_url": url.rstrip("/")}, indent=2))
