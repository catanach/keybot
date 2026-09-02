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


def press_fn(keycode_name, hold):
    keycode = getattr(Keycode, keycode_name)
    keyboard.press(keycode)
    time.sleep(hold)
    keyboard.release(keycode)


try:
    with open("/script.json", "r") as f:
        SCRIPT = json.load(f)
except OSError:
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

    runner = ScriptRunner(SCRIPT, press_fn, None)
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
        runner.set_script(new_script)
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
            with open("/" + name, "w") as f:
                f.write(content)
        code_deploy_requested = True
        return Response(request, "ok, restarting")

    @server.route("/status")
    def status_handler(request):
        return Response(
            request, json.dumps(runner.status()), content_type="application/json"
        )

    server.start(str(wifi.radio.ipv4_address))

    while True:
        server.poll()

        if code_deploy_requested and not runner.running:
            time.sleep(0.5)
            supervisor.reload()

        if runner.running:
            runner.run_one_pass()
        else:
            time.sleep(0.1)

except Exception as e:
    # Something we didn't handle killed the server. Leave a one-line note
    # behind so this isn't a silent, unexplained death next time.
    try:
        with open("/error_log.txt", "w") as f:
            f.write("keybot crashed: {}: {}\n".format(type(e).__name__, e))
    except OSError:
        pass
