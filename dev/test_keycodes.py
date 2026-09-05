"""Tests for the one shared list of key names, src/keycodes.py.

Run them with:
    python3 -m unittest discover -s dev

Issue #7: the same key names used to be typed out by hand in three places
with nothing keeping them in step. They drifted, and recorded arrow keys
and digits failed once they reached the hardware. These tests are what
keeps that from happening again, without needing the Pico:

  - every name in the shared list is a key the real adafruit_hid library
    in lib/ actually has,
  - every name the webapp's recorder can produce is in the shared list.
"""

import os
import re
import sys
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(REPO, "src"))
from keycodes import KEYCODES  # noqa: E402

KEYCODE_MPY = os.path.join(REPO, "lib", "adafruit_hid", "keycode.mpy")
APP_JS = os.path.join(REPO, "webapp", "app", "static", "app.js")


def names_in_mpy(path):
    """Every name stored inside a compiled CircuitPython module.

    A .mpy file keeps its identifiers as a run of "length, text, 0", where
    the length byte is twice the number of characters. Reading them out is
    the only way to check the library from a Mac: the file is compiled, so
    it can't simply be imported here."""
    with open(path, "rb") as f:
        data = f.read()
    found = set()
    i = 0
    while i < len(data):
        size = data[i]
        if size and size % 2 == 0:
            length = size // 2
            text = data[i + 1:i + 1 + length]
            if (
                i + 1 + length < len(data)
                and data[i + 1 + length] == 0
                and re.fullmatch(rb"[A-Za-z_][A-Za-z0-9_]*", text)
            ):
                found.add(text.decode())
                i += length + 2
                continue
        i += 1
    return found


def names_the_recorder_can_produce(path):
    """Every key name toKeycodeName() in app.js can return: the ones spelled
    out in RECORDER_CODE_MAP, plus the ones it builds from a pattern."""
    with open(path, encoding="utf-8") as f:
        source = f.read()

    body = source.split("const RECORDER_CODE_MAP = {", 1)[1].split("};", 1)[0]
    names = set(re.findall(r':\s*"([A-Z0-9_]+)"', body))

    digits = re.findall(
        r'"([A-Z]+)"', source.split("const DIGIT_NAMES = [", 1)[1].split("];", 1)[0]
    )
    names.update("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    names.update(digits)
    names.update("KEYPAD_" + digit for digit in digits)
    names.update("F{}".format(i) for i in range(1, 25))
    return names


class SharedKeyListTest(unittest.TestCase):
    def test_every_name_is_a_real_key(self):
        library = names_in_mpy(KEYCODE_MPY)
        missing = [name for name, _label in KEYCODES if name not in library]
        self.assertEqual(
            missing,
            [],
            "src/keycodes.py lists keys the board's keyboard library does not have",
        )

    def test_every_key_has_a_label_and_appears_once(self):
        names = [name for name, _label in KEYCODES]
        self.assertEqual(sorted(set(names)), sorted(names), "a key is listed twice")
        for name, label in KEYCODES:
            self.assertTrue(label, "{} has no label to show a person".format(name))

    def test_recorder_can_only_produce_keys_that_exist(self):
        known = {name for name, _label in KEYCODES}
        produced = names_the_recorder_can_produce(APP_JS)
        unknown = sorted(name for name in produced if name not in known)
        self.assertEqual(
            unknown,
            [],
            "the recorder in app.js can produce key names the device does not have",
        )


if __name__ == "__main__":
    unittest.main()
