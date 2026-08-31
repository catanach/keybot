# keybot

Files and a deploy script for the Raspberry Pi Pico WH keyboard-emulation project.

## Folder layout

- `src/` — the actual code that runs on the Pico (`code.py`, `script_runner.py`), plus a `settings.toml.example` template for your Wi-Fi credentials.
- `dev/` — a local stand-in for the Pico's server, for testing scripts on your Mac without the hardware. See "Developing without the Pico" below.
- `lib/` — put the CircuitPython firmware `.uf2` file here, along with the `adafruit_hid` and `adafruit_httpserver` library folders. `deploy.sh` reads from this folder.
- `deploy.sh` — copies everything onto the Pico. Safe to run more than once.

`script_runner.py` holds the actual "run the script, track progress, handle stop/times" logic, and both `src/code.py` (on the Pico) and `dev/server.py` (on your Mac) use it the same way. Only the key-press action itself differs between the two.

## One-time setup of this folder

1. Download the CircuitPython firmware `.uf2` for the Pico W from [circuitpython.org/board/raspberry_pi_pico_w](https://circuitpython.org/board/raspberry_pi_pico_w/) and place it in `lib/`.
2. Download the CircuitPython library bundle (version 10.x) from [circuitpython.org/libraries](https://circuitpython.org/libraries), unzip it, and copy the `adafruit_hid` and `adafruit_httpserver` folders from inside its `lib/` folder into this project's `lib/` folder.
3. Copy `src/settings.toml.example` to `src/settings.toml` and fill in your real Wi-Fi network name and password. This file is gitignored, so your credentials never get committed.
4. In Terminal, make the deploy script runnable (only needed once):
   ```
   chmod +x deploy.sh
   ```

## Deploying to a freshly reset Pico

1. Put the Pico into bootloader mode: hold the BOOTSEL button, plug it into your Mac, wait a couple seconds, then let go. It should show up as "RPI-RP2" in Finder.
2. Run:
   ```
   ./deploy.sh
   ```
   This flashes the CircuitPython firmware. Wait for the board to restart and show up as "CIRCUITPY" in Finder.
3. Run `./deploy.sh` again. This time it copies `code.py`, `script_runner.py`, `settings.toml`, and the two library folders onto the board.

## Deploying updates later

Any time you change something in `src/` or `lib/`, plug the Pico into your Mac and run `./deploy.sh` again. It only flashes firmware if the board is in bootloader mode, and only copies files if it's already running CircuitPython, so it's safe to run repeatedly without thinking about which state the board is in.

**Important:** don't have a wired PS5 controller plugged in at the same time as the Pico. The PS5 doesn't tolerate two USB HID devices at once, and this causes an "unsupported file system" error and a hung server. Use Bluetooth for the controller instead, or unplug it while the Pico is connected.

## Using it

- `http://<pico-ip>:5000/start` begins running the script in `script.json` (or the built-in default if none has been pushed yet), looping until stopped.
- `http://<pico-ip>:5000/start?times=5` runs the script exactly 5 times and then stops on its own.
- `http://<pico-ip>:5000/stop` stops it early.
- `http://<pico-ip>:5000/status` reports the current state as JSON: whether it's running, how many loops it's completed, which step it's on, the total number of steps, and the target loop count (`null` if it was started without a `times` value).
- `http://<pico-ip>:5000/update` (POST, with a JSON body like `[["press", "ENTER", 0.1], ["wait", 5]]`) saves a new script and restarts the board to start using it immediately.

## Developing without the Pico

`dev/server.py` runs the exact same routes and script logic on your Mac, so you can write and test a script before pushing it to the actual hardware. It doesn't press real keys, it just prints what it would press.

```
python3 dev/server.py
```

Then in another Terminal tab, hit it exactly like you would the real Pico:

```
curl http://localhost:8085/status
curl "http://localhost:8085/start?times=2"
curl http://localhost:8085/stop
curl -X POST http://localhost:8085/update -d '[["press", "ENTER", 0.1], ["wait", 2]]'
```

It keeps its own `dev/script.json`, separate from the one on the Pico, so testing locally never touches the board's saved script.
