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
    curl "http://localhost:8085/press?key=ENTER&hold=0.1"
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
from keycodes import KEYCODES  # noqa: E402
from script_runner import (  # noqa: E402
    ScriptRunner,
    DEFAULT_SCRIPT,
    program_for_saving,
    program_from_saved,
)

# Where this dev server keeps the script pushed to it. Overridable so a
# test run (dev/repro_lockup.py) does not overwrite your working script.
SCRIPT_FILE = os.environ.get(
    "KEYBOT_DEV_SCRIPT", os.path.join(os.path.dirname(__file__), "script.json")
)

# The key names the Pico will accept, from the one shared list in
# src/keycodes.py -- the same file the board itself checks against the real
# adafruit_hid library at boot. Checking here means a key name the real
# board would reject fails on your Mac too, instead of only showing up
# once the script is running on the hardware.
KEYCODE_NAMES = frozenset(name for name, _label in KEYCODES)

DEPLOYABLE_FILES = ("code.py", "script_runner.py", "keycodes.py")

# Mirrors code.py: the longest a single /press may hold a key down.
MAX_HOLD = 1.0

try:
    with open(SCRIPT_FILE, "r") as f:
        SCRIPT = program_from_saved(json.load(f))
except (OSError, ValueError):
    # Missing, unreadable, or written by different firmware: fall back to
    # the built-in one rather than failing to start. Same as code.py.
    SCRIPT = DEFAULT_SCRIPT


def press_fn(keycode_name, hold):
    # No real key is pressed here, but an unknown key name has to fail the
    # same way it does on the Pico, where it's an error from Keycode.
    if keycode_name not in KEYCODE_NAMES:
        raise ValueError("there is no key called '{}'".format(keycode_name))
    time.sleep(hold)


def sleep_fn(duration):
    # Mirrors code.py, which uses whole nanoseconds because a float clock
    # loses resolution over a long run.
    end_time = time.monotonic_ns() + int(duration * 1000000000)
    while time.monotonic_ns() < end_time:
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
host_writes = False


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
            # Mirrors code.py: the run's own ending gets an explanation too.
            if runner.running and not runner.last_error:
                runner.last_error = "the run stopped: {}: {}".format(
                    type(e).__name__, e
                )
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
        elif parsed.path == "/host_writes":
            # Mirrors the firmware. Nothing to remount here; the dev server
            # just records the request so the webapp path can be tested.
            global host_writes
            host_writes = params.get("enabled", ["1"])[0] != "0"
            self._send_text("ok")
        elif parsed.path == "/stop":
            if params.get("after_current", [None])[0]:
                runner.finish_current_loop()
            else:
                runner.stop()
            self._send_text("ok")
        elif parsed.path == "/press":
            # Mirrors code.py: one key, pressed before this answers. The
            # firmware also refuses while a firmware deploy is pending;
            # there is no counterpart here, because this server never
            # restarts itself (see the module docstring).
            if runner.running:
                self._send_text("a script is running, so that key was not sent", code=409)
                return
            key = params.get("key", [None])[0]
            if not key:
                self._send_text("error: press needs a key", code=400)
                return
            hold_param = params.get("hold", [None])[0] or "0.1"
            try:
                hold = float(hold_param)
            except ValueError:
                self._send_text(
                    "error: hold must be a number, got '{}'".format(hold_param), code=400
                )
                return
            if hold < 0 or hold > MAX_HOLD:
                self._send_text(
                    "error: hold must be between 0 and {} seconds".format(MAX_HOLD), code=400
                )
                return
            try:
                press_fn(key, hold)
            except ValueError as e:
                self._send_text("error: {}".format(e), code=400)
                return
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
            # Mirrors code.py: refused, not staged, while a run is going.
            if runner.running:
                self._send_text(
                    "a script is running, so it was not replaced", code=409
                )
                return
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
                json.dump(program_for_saving(new_script), f)
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
