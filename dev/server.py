"""A local stand-in for the Pico's HTTP server, so you can test scripts on
your Mac without the physical hardware. Same routes, same JSON shapes, same
script format as code.py -- it just prints what it would press instead of
actually pressing a key.

Run it with:
    python3 dev/server.py

Then hit it exactly like you would the real Pico, e.g.:
    curl http://localhost:5000/status
    curl http://localhost:5000/start?times=2
    curl http://localhost:5000/stop
    curl -X POST http://localhost:5000/update -d '[["press", "ENTER", 0.1], ["wait", 2]]'
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

SCRIPT_FILE = os.path.join(os.path.dirname(__file__), "script.json")

try:
    with open(SCRIPT_FILE, "r") as f:
        SCRIPT = json.load(f)
except OSError:
    SCRIPT = DEFAULT_SCRIPT


def press_fn(keycode_name, hold):
    print(f"  press {keycode_name} (hold {hold}s)")
    time.sleep(hold)


def sleep_fn(duration):
    end_time = time.monotonic() + duration
    while time.monotonic() < end_time:
        if runner.stop_requested:
            return
        time.sleep(0.05)


runner = ScriptRunner(SCRIPT, press_fn, sleep_fn)


def background_loop():
    while True:
        if runner.running:
            print(f"--- starting loop {runner.loop_count + 1} ---")
            runner.run_one_pass()
        else:
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
            times = params.get("times", [None])[0]
            runner.start(int(times) if times else None)
            self._send_text("started")
        elif parsed.path == "/stop":
            runner.stop()
            self._send_text("stopping")
        elif parsed.path == "/status":
            self._send_json(runner.status())
        else:
            self._send_text("not found", code=404)

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path == "/update":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            new_script = json.loads(body)
            runner.set_script(new_script)
            with open(SCRIPT_FILE, "w") as f:
                json.dump(new_script, f)
            self._send_text("updated")
        else:
            self._send_text("not found", code=404)

    def log_message(self, format, *args):
        # Quieter default logging. Comment this out if you want to see
        # every HTTP request as it comes in.
        pass


if __name__ == "__main__":
    threading.Thread(target=background_loop, daemon=True).start()
    server = HTTPServer(("0.0.0.0", 5000), Handler)
    print("Dev server running at http://localhost:5000")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
