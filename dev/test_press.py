"""Tests for /press, the route the webapp's recorder calls for each key.

Run them with:
    python3 -m unittest discover -s dev

These run against dev/server.py, which mirrors code.py's handler, so they
say what the firmware does without needing the Pico plugged in. What they
cannot show is the press itself: the dev server waits the length of the hold
instead of pressing a real key. Only the hardware can prove that part.
"""

import json
import os
import subprocess
import sys
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("KEYBOT_PRESS_TEST_PORT", "8098"))
BASE = "http://127.0.0.1:{}".format(PORT)
SCRIPT_FILE = os.path.join(HERE, "press_test_script.json")


def get(path):
    """Returns (status_code, body_text)."""
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def press(**params):
    return get("/press?" + urllib.parse.urlencode(params))


def post(path, payload):
    body = json.dumps(payload).encode()
    request = urllib.request.Request(
        BASE + path, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


class PressTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ)
        env["KEYBOT_DEV_PORT"] = str(PORT)
        env["KEYBOT_DEV_SCRIPT"] = SCRIPT_FILE
        cls.proc = subprocess.Popen(
            [sys.executable, os.path.join(HERE, "server.py")],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        for _ in range(50):
            try:
                if get("/status")[0] == 200:
                    return
            except OSError:
                pass
            time.sleep(0.2)
        cls.proc.kill()
        raise AssertionError("dev server never came up on port {}".format(PORT))

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()
        if os.path.exists(SCRIPT_FILE):
            os.remove(SCRIPT_FILE)

    def tearDown(self):
        get("/stop")

    def test_a_key_is_pressed_and_the_answer_waits_for_it(self):
        started = time.monotonic()
        status, body = press(key="ENTER", hold=0.2)
        self.assertEqual((status, body), (200, "ok"))
        # "ok" means pressed and released, not "queued": the answer cannot
        # come back before the key has been held for as long as it was asked.
        self.assertGreaterEqual(time.monotonic() - started, 0.2)

    def test_a_key_the_device_does_not_have_is_refused(self):
        status, body = press(key="UP", hold=0.1)
        self.assertEqual(status, 400)
        self.assertIn("there is no key called 'UP'", body)

    def test_a_missing_key_is_refused(self):
        status, body = press(hold=0.1)
        self.assertEqual(status, 400)
        self.assertIn("press needs a key", body)

    def test_a_hold_that_is_not_a_number_is_refused(self):
        status, body = press(key="ENTER", hold="ages")
        self.assertEqual(status, 400)
        self.assertIn("hold must be a number", body)

    def test_a_hold_over_the_cap_is_refused(self):
        # A long hold would leave the board deaf to everyone else for as
        # long as the key was down, so one request cannot ask for it.
        started = time.monotonic()
        status, body = press(key="ENTER", hold=30)
        self.assertEqual(status, 400)
        self.assertIn("hold must be between 0 and 1.0 seconds", body)
        self.assertLess(time.monotonic() - started, 5, "it held the key anyway")

    def test_a_key_is_refused_while_a_script_is_running(self):
        self.assertEqual(post("/update", [["wait", 3]])[0], 200)
        self.assertEqual(get("/start?times=1")[0], 200)

        status, body = press(key="ENTER", hold=0.1)
        self.assertEqual(status, 409)
        self.assertEqual(body, "a script is running, so that key was not sent")

        # And it works again as soon as the run is over.
        get("/stop")
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if json.loads(get("/status")[1]).get("running") is False:
                break
            time.sleep(0.1)
        self.assertEqual(press(key="ENTER", hold=0.1), (200, "ok"))


if __name__ == "__main__":
    unittest.main()
