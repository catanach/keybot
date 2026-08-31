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

reload_requested = False


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

        verbose_param = request.query_params.get("verbose")
        verbose = verbose_param in ("1", "true", "True")

        runner.start(times, verbose)
        return Response(request, "ok")

    @server.route("/stop")
    def stop_handler(request):
        runner.stop()
        return Response(request, "ok")

    @server.route("/update", methods=["POST"])
    def update_handler(request):
        global reload_requested
        try:
            new_script = request.json()
        except Exception as e:
            return Response(
                request, "error: invalid JSON body ({})".format(e), status=(400, "Bad Request")
            )
        with open("/script.json", "w") as f:
            json.dump(new_script, f)
        reload_requested = True
        return Response(request, "ok, restarting")

    @server.route("/status")
    def status_handler(request):
        return Response(
            request, json.dumps(runner.status()), content_type="application/json"
        )

    server.start(str(wifi.radio.ipv4_address))

    while True:
        server.poll()

        if reload_requested:
            time.sleep(0.5)
            supervisor.reload()

        if runner.running:
            runner.run_one_pass()
        else:
            time.sleep(0.1)

except Exception:
    pass
