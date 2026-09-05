# keybot

Files and a deploy script for the Raspberry Pi Pico WH keyboard-emulation project.

## Folder layout

- `src/` — the actual code that runs on the Pico (`code.py`, `script_runner.py`, `keycodes.py`), plus a `settings.toml.example` template for your Wi-Fi credentials.
- `dev/` — a local stand-in for the Pico's server, for testing scripts on your Mac without the hardware. See "Developing without the Pico" below.
- `lib/` — put the CircuitPython firmware `.uf2` file here, along with the `adafruit_hid` and `adafruit_httpserver` library folders. `deploy.sh` reads from this folder.
- `deploy.sh` — copies everything onto the Pico. Safe to run more than once.

`script_runner.py` holds the actual "run the script, track progress, handle stop/times" logic, and both `src/code.py` (on the Pico) and `dev/server.py` (on your Mac) use it the same way. Only the key-press action itself differs between the two.

`keycodes.py` is the one list of key names, as `(NAME, label)` pairs. The dev server checks against it, the webapp serves it to the editor's key picker at `/api/keycodes`, and the board checks it against the real `adafruit_hid` library when it boots and reports a fault if the two have drifted apart. Adding a key means adding it there and nowhere else.

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
3. Run `./deploy.sh` again. This time it copies `code.py`, `script_runner.py`, `keycodes.py`, `settings.toml`, and the two library folders onto the board.

## Deploying updates later

Any time you change something in `src/` or `lib/`, plug the Pico into your Mac and run `./deploy.sh` again. It only flashes firmware if the board is in bootloader mode, and only copies files if it's already running CircuitPython, so it's safe to run repeatedly without thinking about which state the board is in.

**Important:** don't have a wired PS5 controller plugged in at the same time as the Pico. The PS5 doesn't tolerate two USB HID devices at once, and this causes an "unsupported file system" error and a hung server. Use Bluetooth for the controller instead, or unplug it while the Pico is connected.

## Using it

- `http://<pico-ip>:5000/start` begins running the script in `script.json` (or the built-in default if none has been pushed yet), looping until stopped. Returns `ok`, or an error message with an explanation if something's wrong (like a missing script).
- `http://<pico-ip>:5000/start?times=5` runs the script exactly 5 times and then stops on its own.
- `http://<pico-ip>:5000/stop` stops it early. Returns `ok`.
- `http://<pico-ip>:5000/status` reports the current state as JSON, meant for polling while a script runs:
  - `running` — whether it's currently going
  - `loop_count` — how many full passes it's completed
  - `target_loops` — how many were requested (`null` if started without a `times` value, meaning it loops forever until stopped)
  - `current_step` / `total_steps` — which step it's on, and how many there are where it is. Inside a repeat these are the steps of the repeated script, not of the whole job.
  - `position` — where the run has got to, one level deep: `part` of `parts` at the top level, and `iteration` of `iterations` when that part is a repeat (both `null` when it isn't). `null` when nothing is running. The device counts; it has never heard of script names, so the webapp puts those back.
  - `depth` — how many levels of repeat are open, counting the program itself as one
  - `features` — what this firmware can do, e.g. `["repeat"]`. The webapp asks before it sends a program, and writes every step out in full for a board that doesn't say it.
  - `mem_free` — bytes of free memory on the board, from `gc.mem_free()`. This is what `MAX_PROGRAM_NODES` in `script_runner.py` was set from.
  - `estimated_seconds_remaining` — a rough estimate of how much longer it'll take, based on the script's own wait times (`null` when `target_loops` is `null`, since there's no fixed end point to estimate toward)
  - `last_error` — why the last run stopped early, in plain language (e.g. `stopped at step 2 of 5: there is no key called 'UP'`, or `stopped at part 2, repeat 738 of 1000, step 4: there is no key called 'UP'` inside a repeat), or `null` if it finished normally. A step that fails stops that run, releases every key, and gets reported here; it never takes the device down with it.
  - `last_fault` — the last problem outside of a script run (a failed write, a hiccup in the web server), or `null`. Also written to `error_log.txt` on the board so it survives a restart.
- `http://<pico-ip>:5000/press?key=ENTER&hold=0.1` presses one key straight away and returns `ok` once it has been pressed and released. This is what the webapp's recorder calls for each key, so a recording is felt on the PS5 as it is typed. `hold` is optional (0.1 seconds by default) and cannot be longer than 1 second, because nothing else is served while a key is held down. It is refused with a 409 while a script is running or while the board is restarting for new firmware, so a live key can never land in the middle of a run.
- `http://<pico-ip>:5000/update` (POST, with a JSON body like `[["press", "ENTER", 0.1], ["wait", 5]]`) saves a new program and starts using it straight away. Returns `ok`, an error message saying what is wrong with the program, or a 409 while a script is running — a program is never swapped out from under a run, so stop it first.

### Programs, and repeating without writing it out

A program is a JSON list of steps, and there are three kinds:

```
["press", "ENTER", 0.1]              press a key for a tenth of a second
["wait", 5]                          wait five seconds
["repeat", 1000, [ ...steps... ]]    do those steps a thousand times
```

A repeat holds the steps it repeats, rather than a copy of them per
iteration. That is the whole of issue #3: "warm up, then gather a thousand
times, then cash out" is a handful of steps the board can hold, not six
thousand it cannot. The board OOMed on a 19KB request once, and that is the
constraint everything here is shaped by.

Nothing else changes. A flat list of presses and waits is still a valid
program, so every script written before this still runs, and `script.json`
now carries the format it was written in so firmware too old to read it
falls back to its built-in script rather than half-running something.

The webapp is where scripts refer to each other. A `["run", other_script, 1000]`
step in the editor compiles to one `["repeat", 1000, [...]]` step before
anything is sent; cycles, missing scripts and bad steps are caught there, and
the board never learns that scripts can refer to each other at all.

What the board checks when a program arrives, rather than while running it:
scripts nested no more than 8 deep, no more steps than `MAX_PROGRAM_NODES`
(counting a repeat as one step plus its contents, never multiplied by its
count), and no empty repeat body — which would otherwise spin through a
million iterations doing nothing. Repeat counts themselves are not capped.
That is the feature.

The two firmware files are sent to the board one per request and have to fit
in its memory, so both are written tersely and their reasoning lives here
rather than in comments beside the code.

## Developing without the Pico

`dev/server.py` runs the exact same routes and script logic on your Mac, so you can write and test a script before pushing it to the actual hardware. It doesn't press real keys, it just waits the same amount of time a real press would take.

```
python3 dev/server.py
```

Then in another Terminal tab, hit it exactly like you would the real Pico:

```
curl http://localhost:8085/status
curl "http://localhost:8085/start?times=2"
curl http://localhost:8085/stop
curl -X POST http://localhost:8085/update -d '[["press", "ENTER", 0.1], ["wait", 2]]'
curl "http://localhost:8085/press?key=ENTER&hold=0.1"
```

It keeps its own `dev/script.json`, separate from the one on the Pico, so testing locally never touches the board's saved script. It also refuses key names the real board would refuse, so a typo like `UP` (the real name is `UP_ARROW`) shows up on your Mac instead of on the hardware.

### Tests

Six things to run, none of which needs the Pico:

```
python3 -m unittest discover -s dev   # the script logic, repeats, compiling, what gets deployed, /press
python3 dev/repro_lockup.py           # the device recovers from bad scripts
node dev/test_picker.js               # the editor's key picker
node dev/test_recording.js            # sending recorded keys to the device
node dev/test_startup.js              # the page still works with an element missing
node dev/test_panel.js                # what the run panel says during a nested run
```

`dev/test_repeats.py` runs a thousand iterations in milliseconds with a
no-op sleep. If repeats were ever written out again rather than held as one
step, those tests would be the first thing to notice.

`dev/test_flatten.py` compiles scripts the way the webapp does, with its own
empty data directory, so it needs neither Docker nor a device.

`dev/test_panel.js` is the half of nested runs Rosy actually looks at: "A,
then B a thousand times, then C" is one loop of one, so a panel that only
counts loops would read `0 / 1` for four hours. It checks the panel says
which part, which repeat of it, and how long is left.

`dev/test_picker.js` runs the editor's key picker without a browser: the real
`app.js`, the real step-row markup from the real page, and the real payload
`/api/keycodes` sends, driven through a small stand-in for a browser in
`dev/fake_dom.js`. It exists because the picker once shipped looking correct
in the code and completely broken on the page, and nothing here could tell
the difference.

`dev/test_recording.js` uses that same stand-in browser for the other half of
recording: the keys going to the device as they are typed. It drives a stubbed
device that can be made slow, unreachable, or busy, which is how the awkward
cases -- typing faster than Wi-Fi, a board that stops answering mid-recording --
get tested without unplugging anything.

`dev/test_startup.js` loads the real `app.js` against a page that is missing an
element it expects, and checks that the rest of the page still comes up. That
happened for real: a browser held an `index.html` from before the "send keys as
they are typed" checkbox existed, `app.js` threw while it was still loading, and
everything after that line -- the status polling, the script list -- never ran.
The page looked normal and did nothing at all. A missing control should cost
that control and nothing else.

`dev/repro_lockup.py` starts its own copy of the dev server on a spare port, feeds it the kinds of broken script the webapp can produce, and checks that the device is still answering and still usable afterwards. Every case has to print PASS.

The webapp has its own tests, which need pytest (a development tool -- it is deliberately kept out of `webapp/requirements.txt` so it never ships inside the container image):

```
python3 -m pytest webapp/tests   # the run history, the key list, and how the page is served
```

## Management webapp

`webapp/` is a small web app for managing scripts without hand-writing JSON or curl commands. It runs entirely in Docker, so nothing needs to be installed on your Mac except Docker itself.

### One-time setup

Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) if you don't already have it.

### Running it

```
cd webapp
docker compose up
```

Then open [http://localhost:8000](http://localhost:8000) in your browser. Stop it with Ctrl+C, or `docker compose down` from the same folder.

Your scripts are saved as JSON files under `webapp/data/scripts/` (created automatically, gitignored), one file per script, so they survive restarting the container and you can peek at them directly if you're curious.

### What it does

- Create, edit, copy, and delete scripts, each with a name and an optional description.
- A script's steps are either `Press` (a key and hold time), `Wait` (seconds), or `Run script` (another script and how many times to repeat it inline). The key is chosen from a searchable list of the keys the device actually has -- type `up` for the up arrow or `8` for the digit, or click "Press a key" and press it. A script saved before this list existed that names a key the device does not have is flagged in place, and cannot be saved again until a real key is picked.
- The "Run script" step type is how you compose scripts: a script that runs Script A once, then Script B 1000 times, then Script C once is just three "Run script" steps. Each one becomes a single repeat step, so what reaches the Pico is a handful of steps whatever the counts are -- 1000 repeats is not 1000 steps. The references are still resolved here, and circular ones (A running B running A) are still caught immediately with a clear error rather than hanging the device.
- A board running firmware older than this doesn't understand repeats, so the webapp checks first and writes every step out in full for it, as it always did. That is capped at 2,000 steps, and a job too big for it is refused with a message saying to deploy the current firmware from the Firmware panel, which then runs the repeats itself.
- A persistent panel on the right lets you pick a script, optionally give it a repeat count, and hit Start or Stop. While something is running it shows where the run has got to -- `part 2 of 3`, `Gathering, 738 of 1000`, `about 1h 12m left` -- and which step it is on inside that part. The time left comes from the device, which is the only thing that knows which repeat it is on, and is counted down between checks. A script that isn't simply a list of other scripts has no parts to count, so the panel shows the step number instead of inventing them.
- Starting a script while one is already running is refused, in those words: the device will not take a new program mid-run, because that is what would let a job be swapped out part way through a repeat. The panel keeps checking the device from the moment the page loads until it closes, so opening it partway through an overnight run shows that run -- it does not have to be the page that started it.
- The Record section captures what you type into a script, and -- with "Send keys to the PS5 while I record" switched on, which is the default -- sends each key to the device as you press it, so you can see what you are recording happen on the PS5. Keys are sent one at a time, in the order they were typed. They go over Wi-Fi, so live presses lag slightly; the timings written into the script come from the browser's clock and are unaffected, so replaying the script is as accurate as it ever was. If the board stops answering, recording carries on and says so above the preview, and a key that failed to send is still in the script. If typing gets more than about ten keys ahead of the board, sending stops for the rest of that recording rather than pressing keys long after you typed them. The switch is hidden entirely if the firmware on the board is older than this feature.
- The History view lists the last 50 runs: which script, how it ended (finished, you stopped it, failed, lost contact, or "stop requested, unconfirmed" -- we asked it to stop and then lost the board before it said it had), how many loops it got through, and why it stopped if something went wrong. The webapp watches the device itself every 5 seconds, so a run is recorded whether or not a browser is open -- including one that ends overnight. History lives in `webapp/data/history.json`.

### Pointing it at the Pico or the dev server

The panel's "Device settings" section holds one setting: the device URL. It defaults to `http://host.docker.internal:8085`, which reaches `dev/server.py` if it's running directly on your Mac (this special hostname is how a Docker container reaches something on its own host machine — a plain `localhost` won't work here, since that would mean "inside the container").

To point it at the real Pico instead, change this to the Pico's own address, e.g. `http://192.168.10.22:5000`.

## Running the webapp

Two commands, from the `webapp/` folder:

    make deploy    # start it (or restart it after a change)
    make stop      # stop it

It serves at http://localhost:8000. `make health-check` says whether the webapp
itself is answering; whether the *Pico* is reachable is shown in the app's own
Device Status panel, which is a different question.

The other scripts in `webapp/` are not for running by hand:

- `update_and_rebuild.sh` is run every two minutes by a LaunchAgent. It pushes
  any commits the team has made, rebuilds the container when `webapp/` changes,
  and drains the GitHub queue. `setup-launchd.sh` installs a separate agent, `com.keybot.webapp.monitor`,
  which restarts the container if the webapp stops answering.
- `start-docker-and-app.sh` is a helper it calls when Docker is not running.
- `gh-bridge.sh` posts queued GitHub issues and comments. See
  `docs/issue-grooming.md`.

### Deploying while a nested run is going

A firmware deploy waits for the pass in progress to finish, so a step is
never cut off half way. Under nesting the whole job is one pass, so a deploy
started during a long run will wait its five minutes and then stop, saying
the script is still running, that nothing was sent, and that the Pico is
unchanged. That is accurate: stop the run first, then deploy.

## Updating the firmware

From the next restart after `boot.py` is installed, the board owns its own
filesystem. That is what makes the Deploy button in the webapp work: the Pico
can rewrite its own `code.py`, `script_runner.py` and `keycodes.py` over WiFi. Before this,
it could not, and every deploy failed with "Read-only filesystem".

The trade is that CIRCUITPY is read-only on the Mac while this is active, so
you cannot drag files onto it.

A Pico W has no reset button, only BOOTSEL, so every way back is a cable
action:

1. **While the board still answers**, use "Hand the drive back to the Mac"
   under Firmware in the webapp. Unplug and replug afterwards and CIRCUITPY
   is writable on the Mac again. It works by writing a `HOST_WRITES` file
   that `boot.py` looks for; delete that file to give the drive back.
2. **If the board no longer answers**, unplug and replug it twice in quick
   succession, the second time within about a second of the first. That
   enters safe mode, where CircuitPython skips `boot.py`, so CIRCUITPY
   mounts writable and files can be dragged on by hand.
3. **Last resort**, hold BOOTSEL while plugging in. The board comes up as
   RPI-RP2 and a fresh `.uf2` can be flashed, which erases everything.

`boot.py` itself is deliberately not deployable over the air. A broken
`code.py` can be replaced remotely; a broken `boot.py` cannot.

### What actually gets sent

Each file goes to the board in one request, and the board has to hold that
whole request in memory to receive it. Measured on the real thing: a ~12.6KB
body arrives and runs, a ~18.9KB one fails with a MemoryError, and the
allocation that fails is smaller than the body -- so it is fragmentation,
not a tidy free-memory limit, and free memory itself swings by around 14KB
between garbage collections.

So the webapp takes the comments and docstrings out before sending, and
`src/` keeps them. They are blanked where they stand rather than deleted, so
every line keeps its line number and an error from the board still points at
the right line of the file you are reading. The deploy message says what
each file weighs on the wire. At the time of writing:

```
keycodes.py        3,841 -> 3,179 bytes
script_runner.py  15,768 -> 10,076 bytes
code.py           11,082 -> 8,296 bytes
```

`deploy.sh`, which copies files over USB, sends them as they are: dragging a
file onto CIRCUITPY writes it straight to flash, so none of this applies.
