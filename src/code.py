import gc
import os
import sys
import time
import json
import wifi
import socketpool
import supervisor
import usb_hid
from adafruit_hid.keyboard import Keyboard
from adafruit_hid.keycode import Keycode
from adafruit_httpserver import Server, Response

from script_runner import ScriptRunner, DEFAULT_SCRIPT

try:
    from keycodes import KEYCODES
except ImportError:
    # Not sent keycodes.py yet. Guarded because an ImportError out here
    # would leave the board with no server and no way to deploy a fix.
    KEYCODES = None

keyboard = Keyboard(usb_hid.devices)

# The most recent thing that went wrong outside a script run. Reported by
# /status, so a problem shows up in the webapp and not as a silent board.
last_fault = None


def log_error(context, error):
    """Records an error without ever raising. Kept in memory for /status,
    and written to a file so it survives a restart."""
    global last_fault
    last_fault = "{}: {}: {}".format(context, type(error).__name__, error)
    try:
        with open("/error_log.txt", "w") as f:
            f.write(last_fault + "\n")
    except OSError:
        # Read-only whenever the drive is mounted over USB. /status is
        # enough in that case.
        pass


def bad_request(request, message):
    """Turns down a request, saying what was wrong in plain words."""
    return Response(request, "error: " + message, status=(400, "Bad Request"))


def press_fn(keycode_name, hold):
    keycode = getattr(Keycode, keycode_name, None)
    if keycode is None:
        raise ValueError("there is no key called '{}'".format(keycode_name))
    keyboard.press(keycode)
    try:
        time.sleep(hold)
    finally:
        # Even if the wait is interrupted, the key doesn't stay down.
        keyboard.release(keycode)


try:
    with open("/script.json", "r") as f:
        SCRIPT = json.load(f)
    if not isinstance(SCRIPT, list):
        SCRIPT = DEFAULT_SCRIPT
except (OSError, ValueError):
    # Missing or unreadable: use the built-in script rather than fail to boot.
    SCRIPT = DEFAULT_SCRIPT

# Set by /deploy_code once new firmware is on disk. The main loop acts on it
# only when nothing is running, so a deploy never cuts off a script mid-step.
code_deploy_requested = False

# The files a deploy is allowed to replace. Anything else is refused.
DEPLOYABLE_FILES = ("code.py", "script_runner.py", "keycodes.py")

# The longest a single /press may hold a key down.
MAX_HOLD = 1.0


if KEYCODES:
    # Drift between the shared key list and this board's keyboard library
    # made recorded arrows fail mid-script. Say so at boot instead.
    missing = [name for name, _label in KEYCODES if getattr(Keycode, name, None) is None]
    if missing:
        log_error(
            "checking the key list",
            ValueError("this board's keyboard library has no " + ", ".join(missing)),
        )
    # Checked: the board needs the memory more than it needs the names.
    KEYCODES = None
    sys.modules.pop("keycodes", None)


def make_sleep_fn(server, runner):
    def sleep_fn(duration):
        end_time = time.monotonic() + duration
        while time.monotonic() < end_time:
            server.poll()
            if runner.stop_requested:
                return
            time.sleep(0.1)

    return sleep_fn


try:
    wifi.radio.connect(
        os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD")
    )

    pool = socketpool.SocketPool(wifi.radio)
    server = Server(pool, debug=True)
    # A client that connects and says nothing must not park the main loop.
    server.socket_timeout = 2

    runner = ScriptRunner(SCRIPT, press_fn, None, keyboard.release_all, server.poll)
    runner.sleep_fn = make_sleep_fn(server, runner)

    @server.route("/start")
    def start_handler(request):
        if not runner.script:
            return bad_request(request, "no script loaded")

        times_param = request.query_params.get("times")
        try:
            times = int(times_param) if times_param else None
        except ValueError:
            return bad_request(
                request, "times must be a whole number, got '{}'".format(times_param)
            )

        # A fault describes the previous run and otherwise survives until
        # reboot. Clear it, or the webapp shows it over a healthy run.
        global last_fault
        last_fault = None

        runner.start(times)
        return Response(request, "ok")

    @server.route("/stop")
    def stop_handler(request):
        if request.query_params.get("after_current"):
            runner.finish_current_loop()
        else:
            runner.stop()
        return Response(request, "ok")

    @server.route("/host_writes")
    def host_writes_handler(request):
        """Hands the drive back to the Mac, or takes it back again. boot.py
        leaves the filesystem alone whenever a HOST_WRITES file exists, so
        this takes effect on the next power cycle -- unplugging it."""
        wanted = request.query_params.get("enabled", "1") != "0"
        try:
            if wanted:
                with open("/HOST_WRITES", "w") as f:
                    f.write("")
            else:
                try:
                    os.remove("/HOST_WRITES")
                except OSError:
                    pass
        except OSError as e:
            return Response(
                request,
                "error: couldn't change who owns the drive ({}). The board may "
                "already have handed it to the Mac.".format(e),
                status=(500, "Internal Server Error"),
            )
        return Response(request, "ok")

    @server.route("/update", methods=["POST"])
    def update_handler(request):
        try:
            new_script = request.json()
        except Exception as e:
            return bad_request(request, "invalid JSON body ({})".format(e))
        # Swapped in place: no restart, so this cannot race a /start.
        try:
            runner.set_script(new_script)
        except ValueError as e:
            return bad_request(request, str(e))
        try:
            with open("/script.json", "w") as f:
                json.dump(new_script, f)
        except OSError:
            # Not fatal: the script is live in memory, just not after a
            # power cycle.
            pass
        return Response(request, "ok")

    @server.route("/deploy_code", methods=["POST"])
    def deploy_code_handler(request):
        global code_deploy_requested
        try:
            files = request.json()
        except Exception as e:
            return bad_request(request, "invalid JSON body ({})".format(e))
        if not isinstance(files, dict) or not files:
            return bad_request(request, "expected an object of filename -> file contents")
        for name in files:
            if name not in DEPLOYABLE_FILES:
                return bad_request(
                    request, "'{}' is not a file this device accepts".format(name)
                )
        for name, content in files.items():
            try:
                with open("/" + name, "w") as f:
                    f.write(content)
            except OSError as e:
                log_error("writing " + name, e)
                return Response(
                    request,
                    "error: couldn't write {} ({}). The board is unchanged"
                    " if this was the first file.".format(name, e),
                    status=(500, "Internal Server Error"),
                )
        code_deploy_requested = True
        return Response(request, "ok, restarting")

    @server.route("/press")
    def press_handler(request):
        """Presses one key straight away, for the webapp's recorder, so a
        recording is felt on the PS5 as it is typed. The press happens here
        rather than on a queue, so "ok" means pressed and released."""
        conflict = None
        if runner.running:
            conflict = "a script is running, so that key was not sent"
        elif code_deploy_requested:
            conflict = "the board is restarting for new firmware, so that key was not sent"
        if conflict:
            return Response(request, conflict, status=(409, "Conflict"))
        key = request.query_params.get("key")
        if not key:
            return bad_request(request, "press needs a key")
        hold_param = request.query_params.get("hold") or "0.1"
        try:
            hold = float(hold_param)
        except ValueError:
            return bad_request(request, "hold must be a number, got '{}'".format(hold_param))
        # Nothing else is served while a key is held down, so a long hold is
        # a way to make the board ignore everyone.
        if hold < 0 or hold > MAX_HOLD:
            return bad_request(
                request, "hold must be between 0 and {} seconds".format(MAX_HOLD)
            )
        try:
            press_fn(key, hold)
        except ValueError as e:
            return bad_request(request, str(e))
        return Response(request, "ok")

    @server.route("/status")
    def status_handler(request):
        state = runner.status()
        state["last_fault"] = last_fault
        # Free heap, so a program's size limit can be set from a real
        # number measured on this board rather than guessed at.
        state["mem_free"] = gc.mem_free()
        return Response(request, json.dumps(state), content_type="application/json")

    server.start(str(wifi.radio.ipv4_address))

    while True:
        try:
            server.poll()

            if code_deploy_requested and not runner.running:
                time.sleep(0.5)
                supervisor.reload()

            if runner.running:
                runner.run_one_pass()
            else:
                time.sleep(0.1)
        except Exception as e:
            # Nothing here may end this loop -- that is what used to leave
            # the board silent until it was unplugged. Note it and serve on.
            log_error("while running", e)
            runner.running = False
            runner.stop_requested = False
            try:
                keyboard.release_all()
            except Exception as release_error:
                log_error("releasing the keys", release_error)
            time.sleep(0.1)

except Exception as e:
    # Something outside the main loop failed -- most likely Wi-Fi or the
    # server -- so nothing is left answering. Write it down and restart.
    log_error("startup", e)
    time.sleep(5)
    supervisor.reload()
