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

keyboard = Keyboard(usb_hid.devices)


def press(keycode, hold=0.1):
    keyboard.press(keycode)
    time.sleep(hold)
    keyboard.release(keycode)


DEFAULT_SCRIPT = [
    ["press", "ENTER", 0.1],
    ["wait", 5.5],
    ["press", "ENTER", 0.1],
    ["wait", 1.5],
    ["press", "ONE", 0.1],
    ["wait", 3],
    ["press", "TWO", 0.1],
    ["wait", 3],
]

try:
    with open("/script.json", "r") as f:
        SCRIPT = json.load(f)
except OSError:
    SCRIPT = DEFAULT_SCRIPT

running = False
stop_requested = False
reload_requested = False

# Progress tracking, reported by /status.
loop_count = 0
current_step = 0
target_loops = None  # None means "loop forever until /stop"


def interruptible_wait(duration, server):
    end_time = time.monotonic() + duration
    while time.monotonic() < end_time:
        server.poll()
        if stop_requested:
            return
        time.sleep(0.1)


try:
    wifi.radio.connect(
        os.getenv("CIRCUITPY_WIFI_SSID"), os.getenv("CIRCUITPY_WIFI_PASSWORD")
    )

    pool = socketpool.SocketPool(wifi.radio)
    server = Server(pool, debug=True)

    @server.route("/start")
    def start_handler(request):
        global running, stop_requested, loop_count, current_step, target_loops
        times_param = request.query_params.get("times")
        target_loops = int(times_param) if times_param else None
        loop_count = 0
        current_step = 0
        running = True
        stop_requested = False
        return Response(request, "started")

    @server.route("/stop")
    def stop_handler(request):
        global stop_requested
        stop_requested = True
        return Response(request, "stopping")

    @server.route("/update", methods=["POST"])
    def update_handler(request):
        global reload_requested
        new_script = request.json()
        with open("/script.json", "w") as f:
            json.dump(new_script, f)
        reload_requested = True
        return Response(request, "updated, restarting")

    @server.route("/status")
    def status_handler(request):
        status = {
            "running": running,
            "loop_count": loop_count,
            "current_step": current_step,
            "total_steps": len(SCRIPT),
            "target_loops": target_loops,
        }
        return Response(request, json.dumps(status), content_type="application/json")

    server.start(str(wifi.radio.ipv4_address))

    while True:
        server.poll()

        if reload_requested:
            time.sleep(0.5)
            supervisor.reload()

        if running:
            for i, step in enumerate(SCRIPT):
                if stop_requested:
                    break
                current_step = i
                if step[0] == "press":
                    press(getattr(Keycode, step[1]), step[2])
                elif step[0] == "wait":
                    interruptible_wait(step[1], server)

            if stop_requested:
                running = False
                stop_requested = False
            else:
                loop_count += 1
                if target_loops is not None and loop_count >= target_loops:
                    running = False
        else:
            time.sleep(0.1)

except Exception:
    pass
