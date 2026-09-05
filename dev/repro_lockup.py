"""Reproduces the "the Pico stops responding until I unplug it" bug
(issue #2) against the dev server, with no hardware involved.

Run it with:
    python3 dev/repro_lockup.py

It starts its own copy of dev/server.py on a spare port, pushes a script
that fails partway through, starts it, and then checks whether the device
is still usable afterwards. Each case prints PASS (the device recovered on
its own) or FAIL (it's wedged and would need a power cycle).

The cases are the shapes of failure Rosy can actually cause from the
webapp, and each one goes through the same script_runner logic the Pico
runs, so a pass here means the same thing happens on the board:

  1. a malformed step (a "wait" with no duration);
  2. a key name that doesn't exist ("UP" - the real name is "UP_ARROW");
  3. a step type the device doesn't know;
  4. a request body that isn't a script at all.

Since nested repeats landed, the device checks a whole program when it
arrives rather than only when it runs, so 1, 3 and 4 are now turned down
at the door with an explanation and never get the chance to stop a run.
That is a better outcome than recovering from them, and it is what these
cases now expect. Number 2 can still only be found while running: whether
a key name exists is something only the board's keyboard library knows.

Exit code is 0 only if every case recovered.
"""

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = int(os.environ.get("KEYBOT_REPRO_PORT", "8099"))
BASE = "http://127.0.0.1:{}".format(PORT)

GOOD_SCRIPT = [["press", "ENTER", 0.05], ["wait", 0.05]]


def get(path):
    """Returns (status_code, body_text). A dead or unreachable server, and
    a handler that blew up, both come back as a status of 0."""
    try:
        with urllib.request.urlopen(BASE + path, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, "{}: {}".format(type(e).__name__, e)


def post(path, payload):
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        BASE + path, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()
    except Exception as e:
        return 0, "{}: {}".format(type(e).__name__, e)


def start_server():
    env = dict(os.environ)
    env["KEYBOT_DEV_PORT"] = str(PORT)
    env["KEYBOT_DEV_SCRIPT"] = os.path.join(HERE, "repro_script.json")
    proc = subprocess.Popen(
        [sys.executable, os.path.join(HERE, "server.py")],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    for _ in range(50):
        if get("/status")[0] == 200:
            return proc
        time.sleep(0.2)
    proc.kill()
    raise SystemExit("dev server never came up on port {}".format(PORT))


def wait_for_idle(seconds=5.0):
    """Polls /status until the run is over. Returns the last status body,
    or None if /status stopped answering at all."""
    deadline = time.monotonic() + seconds
    last = None
    while time.monotonic() < deadline:
        code, body = get("/status")
        if code != 200:
            return None
        last = json.loads(body)
        if not last.get("running"):
            return last
        time.sleep(0.1)
    return last


def confirm_still_usable():
    """The real test: after the failure, can Rosy just push a working
    script and run it again, without touching the hardware?"""
    code, body = post("/update", GOOD_SCRIPT)
    if code != 200:
        print("  FAIL: can't push a new script afterwards ({} {})".format(code, body[:80]))
        return False
    code, body = get("/start?times=1")
    if code != 200:
        print("  FAIL: can't start again afterwards ({} {})".format(code, body[:80]))
        return False
    status = wait_for_idle()
    if status is None:
        print("  FAIL: /status stopped answering during the recovery run")
        return False
    if status.get("loop_count") != 1:
        print("  FAIL: the recovery run never finished -> {}".format(json.dumps(status)))
        return False
    print("  PASS: recovered -- a new script ran to completion, no power cycle")
    return True


def check_bad_script(name, bad_script):
    """Pushes a script that fails partway through, runs it, and checks the
    device is still there and can say what went wrong."""
    print("\n--- {} ---".format(name))
    code, body = post("/update", bad_script)
    print("  push script    -> {} {}".format(code, body.strip()[:120]))
    if code != 200:
        print("  FAIL: the device refused a script it should have accepted")
        return False

    code, body = get("/start?times=1")
    print("  start          -> {} {}".format(code, body.strip()[:120]))
    if code != 200:
        print("  FAIL: couldn't start the run")
        return False

    status = wait_for_idle()
    if status is None:
        print("  FAIL: /status stopped answering -- the device is unreachable")
        return False
    if status.get("running"):
        print("  FAIL: still stuck on 'running' -- nothing new can start")
        return False
    if not status.get("last_error"):
        print("  FAIL: the run died but nothing was reported back to the webapp")
        return False
    print("  reported error -> {}".format(status["last_error"]))
    return confirm_still_usable()


def check_bad_request(name, payload):
    """Sends something the device should refuse outright -- a bad step, or
    something that isn't a script at all. It should say no, in words, and
    carry on as if nothing happened."""
    print("\n--- {} ---".format(name))
    code, body = post("/update", payload)
    print("  push           -> {} {}".format(code, body.strip()[:120]))
    if code != 400:
        print("  FAIL: expected a 400 with an explanation, got {}".format(code))
        return False
    return confirm_still_usable()


def main():
    proc = start_server()
    try:
        results = [
            check_bad_request(
                'malformed step: a "wait" with no duration',
                [["press", "ENTER", 0.05], ["wait"]],
            ),
            check_bad_script(
                'key name that does not exist: "UP" instead of "UP_ARROW"',
                [["press", "UP", 0.05]],
            ),
            check_bad_request(
                'step type the device does not know: "hold"',
                [["hold", "ENTER", 0.05]],
            ),
            check_bad_request(
                "request body that isn't a script at all",
                {"steps": [["press", "ENTER", 0.05]]},
            ),
        ]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            proc.kill()
        leftover = os.path.join(HERE, "repro_script.json")
        if os.path.exists(leftover):
            os.remove(leftover)

    print("\n=======================================")
    print("  {} of {} cases recovered".format(sum(1 for r in results if r), len(results)))
    print("=======================================")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
