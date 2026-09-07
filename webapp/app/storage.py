"""JSON-file-based storage for scripts.

Each script is one file, named by its id, under KEYBOT_DATA_DIR/scripts/.
This keeps things simple and inspectable -- you can open any script file
directly and see exactly what's in it -- and avoids needing a database.

A script looks like:
{
    "id": "a1b2c3d4",
    "name": "Grind loop",
    "description": "Opens the menu and mashes through it.",
    "rev": 3,
    "steps": [
        ["press", "ENTER", 0.1],
        ["wait", 5.5],
        ["run", "other-script-id", 10]
    ]
}

Step types:
    ["press", keycode_name, hold_seconds]
    ["wait", seconds]
    ["run", script_id, times]   -- runs another script this many times, inline

"rev" counts how many times a script has been written. Whoever saves says
which rev they started from, and a save based on a stale one is refused
rather than quietly overwriting whatever happened in between -- two tabs
open on the same script is not unusual, and one of them silently losing
its steps is not something you would ever notice. Scripts written before
rev existed read as rev 1.
"""

import json
import os
import uuid
from pathlib import Path
from typing import Optional

class RevMismatch(Exception):
    """Raised when a save started from a rev that is no longer the current
    one, which means someone else saved the same script in between."""


def scripts_dir() -> Path:
    """Where the scripts live, worked out on every call rather than when
    this module is imported -- the way the run history does it. A test that
    points KEYBOT_DATA_DIR at a temporary directory has usually imported
    this module long before, and a path fixed at import time would send
    that test's writes into the real scripts."""
    return Path(os.environ.get("KEYBOT_DATA_DIR", "/data")) / "scripts"


def _ensure_dir():
    scripts_dir().mkdir(parents=True, exist_ok=True)


def _path(script_id: str) -> Path:
    return scripts_dir() / f"{script_id}.json"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def list_scripts() -> list[dict]:
    """Returns a summary of every script (no steps), sorted by name."""
    _ensure_dir()
    scripts = []
    for path in scripts_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        scripts.append(
            {
                "id": data["id"],
                "name": data.get("name", "(untitled)"),
                "description": data.get("description", ""),
                "rev": data.get("rev", 1),
                "step_count": len(data.get("steps", [])),
            }
        )
    scripts.sort(key=lambda s: s["name"].lower())
    return scripts


def get_script(script_id: str) -> Optional[dict]:
    _ensure_dir()
    path = _path(script_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    data.setdefault("rev", 1)
    return data


def save_script(
    script_id: Optional[str],
    name: str,
    description: str,
    steps: list,
    expected_rev: Optional[int] = None,
) -> dict:
    """Creates a new script (script_id is None) or overwrites an existing one.

    expected_rev is the rev the caller started from. Give it and a save that
    would overwrite someone else's raises RevMismatch and writes nothing;
    leave it out and the save goes through whatever the current rev is."""
    _ensure_dir()
    if script_id is None:
        script_id = new_id()
        rev = 1
    else:
        existing = get_script(script_id)
        current_rev = existing["rev"] if existing else 0
        if expected_rev is not None and expected_rev != current_rev:
            raise RevMismatch(
                f"expected rev {expected_rev}, but the stored script is at {current_rev}"
            )
        rev = current_rev + 1
    data = {
        "id": script_id,
        "name": name,
        "description": description or "",
        "rev": rev,
        "steps": steps,
    }
    _path(script_id).write_text(json.dumps(data, indent=2))
    return data


def delete_script(script_id: str) -> bool:
    _ensure_dir()
    path = _path(script_id)
    if not path.exists():
        return False
    path.unlink()
    return True


def copy_script(script_id: str, new_name: Optional[str] = None) -> Optional[dict]:
    original = get_script(script_id)
    if original is None:
        return None
    name = new_name or f"{original['name']} (copy)"
    return save_script(None, name, original.get("description", ""), original["steps"])
