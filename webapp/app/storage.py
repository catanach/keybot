"""JSON-file-based storage for scripts.

Each script is one file, named by its id, under KEYBOT_DATA_DIR/scripts/.
This keeps things simple and inspectable -- you can open any script file
directly and see exactly what's in it -- and avoids needing a database.

A script looks like:
{
    "id": "a1b2c3d4",
    "name": "Grind loop",
    "description": "Opens the menu and mashes through it.",
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
"""

import json
import os
import uuid
from pathlib import Path
from typing import Optional

DATA_DIR = Path(os.environ.get("KEYBOT_DATA_DIR", "/data"))
SCRIPTS_DIR = DATA_DIR / "scripts"


def _ensure_dir():
    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)


def _path(script_id: str) -> Path:
    return SCRIPTS_DIR / f"{script_id}.json"


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def list_scripts() -> list[dict]:
    """Returns a summary of every script (no steps), sorted by name."""
    _ensure_dir()
    scripts = []
    for path in SCRIPTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        scripts.append(
            {
                "id": data["id"],
                "name": data.get("name", "(untitled)"),
                "description": data.get("description", ""),
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
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_script(
    script_id: Optional[str], name: str, description: str, steps: list
) -> dict:
    """Creates a new script (script_id is None) or overwrites an existing one."""
    _ensure_dir()
    if script_id is None:
        script_id = new_id()
    data = {
        "id": script_id,
        "name": name,
        "description": description or "",
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
