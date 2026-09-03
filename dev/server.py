"""A local stand-in for the Pico's HTTP server, so you can test scripts on
your Mac without the physical hardware. Same routes, same JSON shapes, same
script format as code.py -- it doesn't press real keys, it just waits the
same amount of time a real press would take.

Note on /deploy_code: this dev server accepts the same request the real
Pico does and reports success, but it doesn't actually restart itself the
way a real firmware deploy does (there's no separate "board" to reboot
here). It's only useful for checking that the webapp's deploy flow calls
the right endpoints in the right order, not for testing what happens to a
real device during a restart -- that only the physical Pico can tell you.

Run it with:
    python3 dev/server.py

Then hit it exactly like you would the real Pico, e.g.:
    curl http://localhost:8085/status
    curl "http://localhost:8085/start?times=2"
    curl http://localhost:8085/stop
    curl -X POST http://localhost:8085/update -d '[["press", "ENTER", 0.1], ["wait", 2]]'
"""

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from script_runner import ScriptRunner, DEFAULT_SCRIPT  # noqa: E402

# Where this dev server keeps the script pushed to it. Overridable so a
# test run (dev/repro_lockup.py) does not overwrite your working script.
SCRIPT_FILE = os.environ.get(
    "KEYBOT_DEV_SCRIPT", os.path.join(os.path.dirname(__file__), "script.json")
)

# The key names the Pico will accept, taken from the adafruit_hid Keycode
# library in lib/. The dev server checks against this list so that a key
# name the real board would reject fails here too, instead of only showing
# up once the script is running on the hardware.
KEYCODE_NAMES = frozenset(
    list("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    + [
        "ZERO", "ONE", "TWO", "THREE", "FOUR",
        "FIVE", "SIX", "SEVEN", "EIGHT", "NINE",
        "ENTER", "RETURN", "ESCAPE", "BACKSPACE", "TAB", "SPACE", "SPACEBAR",
        "MINUS", "EQUALS", "LEFT_BRACKET", "RIGHT_BRACKET", "BACKSLASH",
        "POUND", "SEMICOLON", "QUOTE", "GRAVE_ACCENT", "COMMA", "PERIOD",
        "FORWARD_SLASH", "CAPS_LOCK",
        "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11",
        "F12", "F13", "F14", "F15", "F16", "F17", "F18", "F19", "F20",
        "F21", "F22", "F23", "F24",
        "PRINT_SCREEN", "SCROLL_LOCK", "PAUSE", "INSERT", "HOME", "PAGE_UP",
        "DELETE", "END", "PAGE_DOWN",
        "RIGHT_ARROW", "LEFT_ARROW", "DOWN_ARROW", "UP_ARROW",
        "KEYPAD_NUMLOCK", "KEYPAD_FORWARD_SLASH", "KEYPAD_ASTERISK",
        "KEYPAD_MINUS", "KEYPAD_PLUS", "KEYPAD_ENTER", "KEYPAD_ZERO",
        "KEYPAD_ONE", "KEYPAD_TWO", "KEYPAD_THREE", "KEYPAD_FOUR",
        "KEYPAD_FIVE", "KEYPAD_SIX", "KEYPAD_SEVEN", "KEYPAD_EIGHT",
        "KEYPAD_NINE", "KEYPAD_PERIOD", "KEYPAD_BACKSLASH", "KEYPAD_EQUALS",
        "APPLICATION", "POWER",
        "LEFT_CONTROL", "CONTROL", "LEFT_SHIFT", "SHIFT", "LEFT_ALT", "ALT",
        "OPTION", "LEFT_GUI", "GUI", "WINDOWS", "COMMAND",
        "RIGHT_CONTROL", "RIGHT_SHIFT", "RIGHT_ALT", "RIGHT_GUI",
    ]
)

DEPLOYABLE_FILES = ("code.py", "script_runner.py")

try:
    with open(SCRIPT_FILE, "r") as f:
        SCRIPT = json.load(f)
    if not isinstance(SCRIPT, list):
        SCRIPT = DEFAULT_SCRIPT
except (OSError, ValueError):
    # Missing or unreadable saved script: fall back to the built-in one
    # rather than failing to start. Same as code.py.
    SCRIPT = DEFAULT_SCRIPT


def press_fn(keycode_name, hold):
    # No real key is pressed here, but an unknown key name has to fail the
    # same way it does on the Pico, where it's an error from Keycode.
    if keycode_name not in KEYCODE_NAMES:
        raise ValueError("there is no key called '{}'".format(keycode_name))
    time.sleep(hold)


def sleep_fn(duration):
    end_time = time.monotonic() + duration
    while time.monotonic() < end_time:
        if runner.stop_requested:
            return
        time.sleep(0.05)


def release_fn():
    # Nothing is really held down here; the Pico releases every key at
    # this point, so the shape of a run matches.
    pass


# tick_fn mirrors the firmware: the real board serves HTTP here. This dev
# server answers on its own thread, so it only needs to count the yields
# for the tests.
tick_count = [0]


def tick_fn():
    tick_count[0] += 1


runner = ScriptRunner(SCRIPT, press_fn, sleep_fn, release_fn, tick_fn)

# Matches code.py: the most recent problem outside of a script run,
# reported by /status.
last_fault = None


def background_loop():
    global last_fault
    while True:
        try:
            if runner.running:
                runner.run_one_pass()
            else:
                time.sleep(0.1)
        except Exception as e:
            # Same guarantee code.py makes on the Pico: nothing ends this
            # loop, or the device would go quiet until it was restarted.
            last_fault = "while running: {}: {}".format(type(e).__name__, e)
            runner.running = False
            runner.stop_requested = False
            time.sleep(0.1)


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text, code=200):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/start":
            if not runner.script:
                self._send_text("error: no script loaded", code=400)
                return

            times_param = params.get("times", [None])[0]
            try:
                times = int(times_param) if times_param else None
            except ValueError:
                self._send_text(
                    "error: times must be a whole number, got '{}'".format(times_param),
                    code=400,
                )
                return

            # Mirrors code.py: a fault describes the previous run, so
            # starting a new one clears it.
            global last_fault
            last_fault = None

            runner.start(times)
            self._send_text("ok")
        elif parsed.path == "/stop":
            if params.get("after_current", [None])[0]:
                runner.finish_current_loop()
            else:
                runner.stop()
            self._send_text("ok")
        elif parsed.path == "/status":
            state = runner.status()
            state["last_fault"] = last_fault
            self._send_json(state)
        else:
            self._send_text("not found", code=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/update":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                new_script = json.loads(body)
            except json.JSONDecodeError as e:
                self._send_text("error: invalid JSON body ({})".format(e), code=400)
                return
            try:
                runner.set_script(new_script)
            except ValueError as e:
                self._send_text("error: {}".format(e), code=400)
                return
            with open(SCRIPT_FILE, "w") as f:
                json.dump(new_script, f)
            self._send_text("ok")
        elif parsed.path == "/deploy_code":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            try:
                files = json.loads(body)
            except json.JSONDecodeError as e:
                self._send_text("error: invalid JSON body ({})".format(e), code=400)
                return
            if not isinstance(files, dict) or not files:
                self._send_text(
                    "error: expected an object of filename -> file contents", code=400
                )
                return
            for name in files:
                if name not in DEPLOYABLE_FILES:
                    self._send_text(
                        "error: '{}' is not a file this device accepts".format(name), code=400
                    )
                    return
            # Not actually applied -- see the module docstring. This just
            # confirms the request shape is right.
            self._send_text("ok, restarting")
        else:
            self._send_text("not found", code=404)

    def log_message(self, format, *args):
        # Quieter default logging. Comment this out if you want to see
        # every HTTP request as it comes in.
        pass


if __name__ == "__main__":
    # Port is 8085 to match the webapp's default device URL. Override it
    # with KEYBOT_DEV_PORT when you want a second copy running alongside
    # (the lockup repro in dev/repro_lockup.py does this).
    port = int(os.environ.get("KEYBOT_DEV_PORT", "8085"))
    threading.Thread(target=background_loop, daemon=True).start()
    server = HTTPServer(("0.0.0.0", port), Handler)
    print("Dev server running at http://localhost:{}".format(port))
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
