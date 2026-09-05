"""Serves the one shared list of key names to the browser.

The list itself lives in src/keycodes.py, which is also what runs on the
Pico. The webapp reads that same file (it is mounted read-only into the
container as /firmware_src) rather than keeping a copy, because a copy is
exactly how the names drifted apart last time.

Grouping happens here rather than in the shared file, so the file stays
plain data that CircuitPython can load.
"""

import importlib.util
import re

from .firmware import FIRMWARE_DIR, FirmwareError

# The first group of the picker: the keys almost every script uses, in the
# order someone reaches for them rather than alphabetically.
COMMON = ["ENTER", "SPACE", "TAB", "ESCAPE", "BACKSPACE", "DELETE"]

MODIFIERS = [
    "LEFT_CONTROL", "CONTROL", "RIGHT_CONTROL",
    "LEFT_SHIFT", "SHIFT", "RIGHT_SHIFT",
    "LEFT_ALT", "ALT", "RIGHT_ALT", "OPTION",
    "LEFT_GUI", "GUI", "RIGHT_GUI", "COMMAND", "WINDOWS",
]

PUNCTUATION = [
    "MINUS", "EQUALS", "LEFT_BRACKET", "RIGHT_BRACKET", "BACKSLASH",
    "POUND", "SEMICOLON", "QUOTE", "GRAVE_ACCENT", "COMMA", "PERIOD",
    "FORWARD_SLASH",
]

DIGITS = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX", "SEVEN",
          "EIGHT", "NINE"]

# The order the picker shows the groups in. Anything a rule below does not
# claim ends up in "Other" -- the navigation and system keys, and the
# alternative spellings like RETURN and SPACEBAR.
GROUP_ORDER = [
    "Common", "Letters", "Numbers", "Arrows", "Function keys", "Keypad",
    "Modifiers", "Punctuation", "Other",
]


def load_keycodes() -> list:
    """Reads the (NAME, label) pairs out of the shared src/keycodes.py."""
    path = FIRMWARE_DIR / "keycodes.py"
    spec = importlib.util.spec_from_file_location("keybot_keycodes", path)
    if spec is None or spec.loader is None:
        raise FirmwareError(f"can't read the shared key list at {path}")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except OSError as e:
        raise FirmwareError(f"can't read the shared key list at {path}: {e}")
    return list(module.KEYCODES)


def group_for(name: str) -> str:
    if name in COMMON:
        return "Common"
    if len(name) == 1 and name.isalpha():
        return "Letters"
    if name in DIGITS:
        return "Numbers"
    if name.endswith("_ARROW"):
        return "Arrows"
    if re.fullmatch(r"F\d+", name):
        return "Function keys"
    if name.startswith("KEYPAD_"):
        return "Keypad"
    if name in MODIFIERS:
        return "Modifiers"
    if name in PUNCTUATION:
        return "Punctuation"
    return "Other"


def grouped() -> list:
    """The shared list, split into the groups the picker shows, in order.
    Common keeps its own hand-picked order; every other group keeps the
    order of the shared list. Empty groups are left out."""
    buckets = {group: [] for group in GROUP_ORDER}
    for name, label in load_keycodes():
        buckets[group_for(name)].append({"name": name, "label": label})

    by_name = {key["name"]: key for key in buckets["Common"]}
    buckets["Common"] = [by_name[name] for name in COMMON if name in by_name]

    return [
        {"name": group, "keys": buckets[group]}
        for group in GROUP_ORDER
        if buckets[group]
    ]
