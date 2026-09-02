import os
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

keyboard = Keyboard(usb_hid.devices)

# The most recent thing that went wrong outside of a script run (a bad
# request, a failed write, a hiccup in the web server). Reported by
# /status so a problem is visible from the webapp instead of only being
# visible as a board that stopped answering.
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
        # The board's filesystem is read-only whenever it's mounted over
        # USB. The copy on /status is enough in that case.
        pass


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
    # Missing or unreadable saved script: fall back to the built-in one
    # rather than failing to boot.
    SCRIPT = DEFAULT_SCRIPT

# Set by /deploy_code once new firmware has been written to disk. Checked
# in the main loop, and only acted on once nothing is running, so a deploy
# never cuts off a script mid-step.
code_deploy_requested = False

# The files a deploy is allowed to replace. Anything else is refused.
DEPLOYABLE_FILES = ("code.py", "script_runner.py")


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
    # A client that connects and then says nothing must not be able to
    # park the main loop waiting on it.
    server.socket_timeout = 2

    runner = ScriptRunner(SCRIPT, press_fn, None, keyboard.release_all)
    runner.sleep_fn = make_sleep_fn(server, runner)

    @server.route("/start")
    def start_handler(request):
        if not runner.script:
            return Response(request, "error: no script loaded", status=(400, "Bad Request"))

        times_param = request.query_params.get("times")
        try:
            times = int(times_param) if times_param else None
        except ValueError:
            return Response(
                request,
                "error: times must be a whole number, got '{}'".format(times_param),
                status=(400, "Bad Request"),
            )

        runner.start(times)
        return Response(request, "ok")

    @server.route("/stop")
    def stop_handler(request):
        if request.query_params.get("after_current"):
            runner.finish_current_loop()
        else:
            runner.stop()
        return Response(request, "ok")

    @server.route("/update", methods=["POST"])
    def update_handler(request):
        try:
            new_script = request.json()
        except Exception as e:
            return Response(
                request, "error: invalid JSON body ({})".format(e), status=(400, "Bad Request")
            )
        # Swap the script in place. No restart, so this can't race a
        # follow-up /start call the way reloading the whole board used to.
        try:
            runner.set_script(new_script)
        except ValueError as e:
            return Response(request, "error: {}".format(e), status=(400, "Bad Request"))
        try:
            with open("/script.json", "w") as f:
                json.dump(new_script, f)
        except OSError:
            # Not fatal: the new script is already live in memory, it just
            # won't be there anymore after the next power cycle.
            pass
        return Response(request, "ok")

    @server.route("/deploy_code", methods=["POST"])
    def deploy_code_handler(request):
        global code_deploy_requested
        try:
            files = request.json()
        except Exception as e:
            return Response(
                request, "error: invalid JSON body ({})".format(e), status=(400, "Bad Request")
            )
        if not isinstance(files, dict) or not files:
            return Response(
                request,
                "error: expected an object of filename -> file contents",
                status=(400, "Bad Request"),
            )
        for name in files:
            if name not in DEPLOYABLE_FILES:
                return Response(
                    request,
                    "error: '{}' is not a file this device accepts".format(name),
                    status=(400, "Bad Request"),
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

    @server.route("/status")
    def status_handler(request):
        state = runner.status()
        state["last_fault"] = last_fault
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
            # Nothing that happens while serving a request or running a
            # script is allowed to end this loop. That's what used to
            # leave the board silent until it was unplugged. Note what
            # happened, drop back to idle, and keep serving.
            log_error("while running", e)
            runner.running = False
            runner.stop_requested = False
            try:
                keyboard.release_all()
            except Exception as release_error:
                log_error("releasing the keys", release_error)
            time.sleep(0.1)

except Exception as e:
    # Something outside the main loop failed -- most likely Wi-Fi or
    # starting the server, so there's nothing left answering that could
    # explain it. Write it down and restart, which is the same thing
    # unplugging the board does, without anyone having to be there.
    log_error("startup", e)
    time.sleep(5)
    supervisor.reload()
