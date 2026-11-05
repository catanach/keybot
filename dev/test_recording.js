// Tests for sending recorded keys to the Pico as they are typed (issue #17),
// run without a browser or hardware.
//
//     node dev/test_recording.js
//
// The real webapp/app/static/app.js runs against the stand-in DOM in
// dev/fake_dom.js -- the same harness the key picker is tested with. The
// device is a stub whose replies this file controls, so the things that are
// hard to try by hand can be tried here: a board that answers slowly, a
// board that stops answering, and someone typing faster than Wi-Fi.

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { FakeEvent, document, elementsById, makeWindow, makeClock } = require("./fake_dom.js");

const REPO = path.resolve(__dirname, "..");
const APP_JS = path.join(REPO, "webapp/app/static/app.js");

// What the device stub does with a /api/device/press request.
const press = {
  // Every key pressed, in order. Releases are kept separately so the older
  // assertions still read as "which keys reached the PS5".
  sent: [],
  // down: and up: in order, for the tests that care which was which.
  events: [],
  // How many times the board was told a take is starting.
  wakes: 0,
  // Requests still waiting for an answer, when holdAnswers is on.
  waiting: [],
  holdAnswers: false,
  supported: true,
  // What the board reports it actually held the key for, in seconds, on the
  // key-up response. null stands for firmware that reports nothing, which is
  // also what a duplicate or out of order release gets.
  heldAnswer: null,
};

function jsonResponse(body, ok = true, status = 200) {
  const text = JSON.stringify(body);
  return {
    ok,
    status,
    text: () => Promise.resolve(text),
    json: () => Promise.resolve(JSON.parse(text)),
  };
}

function unreachable() {
  return jsonResponse({ detail: "can't reach device at http://x: timed out" }, false, 502);
}

// The steps of the last recording that was saved, as the server received
// them. This is where "the key still landed in the script" is checked.
let savedSteps = null;

function fakeFetch(url, opts = {}) {
  if (url === "/api/scripts" && opts.method === "POST") {
    savedSteps = JSON.parse(opts.body).steps;
    return Promise.resolve(jsonResponse({ id: "new", name: "Recording", steps: savedSteps }));
  }
  if (url === "/api/recordings/save") {
    const body = JSON.parse(opts.body);
    savedSteps = body.steps;
    return Promise.resolve(
      jsonResponse({
        script: { id: "new", name: body.name, steps: savedSteps },
        target: null,
        warning: "",
      })
    );
  }
  if (url === "/api/recordings/next-name") {
    return Promise.resolve(jsonResponse({ name: "Recording 1" }));
  }
  if (url === "/api/device/key-down" || url === "/api/device/press") {
    const key = JSON.parse(opts.body).key;
    press.sent.push(key);
    press.events.push("down:" + key);
    if (press.holdAnswers) {
      return new Promise((resolve) => press.waiting.push({ key, resolve }));
    }
    return Promise.resolve(jsonResponse({ ok: true }));
  }
  if (url === "/api/device/key-up") {
    const key = JSON.parse(opts.body).key;
    press.events.push("up:" + key);
    const body = { ok: true };
    if (press.heldAnswer !== null) body.held = press.heldAnswer;
    return Promise.resolve(jsonResponse(body));
  }
  if (url === "/api/device/wake") {
    press.wakes++;
    return Promise.resolve(jsonResponse({ ok: true }));
  }
  if (url === "/api/device/press/supported") {
    return Promise.resolve(jsonResponse({ supported: press.supported }));
  }
  if (url === "/api/keycodes") return Promise.resolve(jsonResponse({ groups: [] }));
  if (url === "/api/scripts") return Promise.resolve(jsonResponse([]));
  if (url === "/api/history") return Promise.resolve(jsonResponse([]));
  if (url === "/api/settings") {
    return Promise.resolve(jsonResponse({ device_url: "http://localhost:8085" }));
  }
  if (url === "/api/device/status") {
    return Promise.resolve(jsonResponse({ detail: "no device in this test" }, false, 502));
  }
  return Promise.resolve(jsonResponse({}));
}

process.on("unhandledRejection", () => {});

const testWindow = makeWindow();
const clock = makeClock();
const context = vm.createContext({
  document,
  window: testWindow,
  navigator: { platform: "MacIntel" },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: fakeFetch,
  alert: () => {},
  confirm: () => true,
  console,
  setInterval: () => 0,
  clearInterval: () => {},
  setTimeout: (fn) => { fn(); return 0; },
  clearTimeout: () => {},
  Event: FakeEvent,
  Date: clock.Date,
});
vm.runInContext(fs.readFileSync(APP_JS, "utf-8"), context, { filename: "app.js" });

// The switch is a real checkbox on the page; the stand-in DOM makes a plain
// element for it, so its state is set here the way the browser would.
const liveToggle = elementsById.get("recording-live");
const liveRow = elementsById.get("recording-live-row");
const banner = elementsById.get("recording-banner");
const problem = elementsById.get("recording-live-problem");
const preview = elementsById.get("recording-preview");
const keysCount = elementsById.get("recording-keys");
const statusText = elementsById.get("recording-status-text");

// The recording's own state is private to app.js, so what it recorded is
// read the way a person would see it: the counter, the preview, and what
// Save actually sends to the server.
async function saveAndReadSteps() {
  savedSteps = null;
  // Stop is what puts the save panel up and fills the name in. Saving from
  // a recording that is still going is not something the page offers.
  if (statusText.textContent === "Recording...") context.stopRecording();
  await settle();
  elementsById.get("recording-name").value = "Recording 1";
  await context.saveRecordedScript();
  return savedSteps;
}

// Lets every pending promise settle, the way the browser would between
// keystrokes. Nothing here waits on real time.
async function settle(rounds = 20) {
  for (let i = 0; i < rounds; i++) await new Promise((r) => setImmediate(r));
}

function keyEvent(kind, code, extra = {}) {
  return new FakeEvent(kind, {
    bubbles: true,
    code,
    key: code.replace("Key", "").toLowerCase(),
    ...extra,
  });
}

// A real key goes down and comes back up. type() sent only keydown, which
// was invisible while the page ignored keyup and would have left every
// test's key held down forever once it stopped ignoring it.
function down(code, extra = {}) {
  document.dispatchEvent(keyEvent("keydown", code, extra));
}

function up(code) {
  document.dispatchEvent(keyEvent("keyup", code));
}

function type(...codes) {
  for (const code of codes) {
    down(code);
    up(code);
  }
}

// Holds a key for a given number of milliseconds on the fake clock, firing
// the auto-repeat keydowns the OS would fire while it is held down. repeats
// defaults to what macOS does at roughly 10 per second.
function hold(code, ms, { repeats = Math.max(0, Math.floor(ms / 100) - 1) } = {}) {
  down(code);
  for (let i = 0; i < repeats; i++) {
    clock.advance(100);
    down(code, { repeat: true });
  }
  clock.set(clock.now() + (ms - repeats * 100));
  up(code);
}

// Moves the clock without touching a key, for the gaps between keystrokes.
function pause(ms) {
  clock.advance(ms);
}

function answerNext() {
  const call = press.waiting.shift();
  call.resolve(jsonResponse({ ok: true }));
  return call.key;
}

async function freshRecording({ live = true } = {}) {
  // Answer anything still in flight first. A real request would time out on
  // its own; here it would sit in the queue forever and stall the next test.
  press.holdAnswers = false;
  while (press.waiting.length > 0) press.waiting.shift().resolve(jsonResponse({ ok: true }));
  await settle();

  context.stopRecording();
  context.resetRecording();
  press.sent = [];
  press.events = [];
  press.heldAnswer = null;
  liveToggle.checked = live;
  context.startRecording();
  await settle();
}

const results = [];
async function test(name, fn) {
  try {
    await fn();
    results.push([true, name]);
    console.log("PASS " + name);
  } catch (e) {
    results.push([false, name]);
    console.log("FAIL " + name + "\n      " + String(e.message).split("\n").join("\n      "));
  }
}

async function main() {
  await test("the switch is hidden when the board's firmware has no /press", async () => {
    press.supported = false;
    await context.loadLivePressSupport();
    assert.strictEqual(liveRow.hidden, true);

    await freshRecording();
    type("KeyA");
    await settle();
    assert.deepStrictEqual(press.sent, [], "it sent a key to firmware that has no /press");
    assert.deepStrictEqual(await saveAndReadSteps(), [["press", "A", 0.1]]);

    press.supported = true;
    await context.loadLivePressSupport();
    assert.strictEqual(liveRow.hidden, false);
  });

  await test("keys are sent in the order they were typed, one at a time", async () => {
    await freshRecording();
    press.holdAnswers = true;

    type("KeyA", "KeyB", "KeyC");
    await settle();
    assert.deepStrictEqual(press.sent, ["A"], "more than one request was in flight at once");

    assert.strictEqual(answerNext(), "A");
    await settle();
    assert.deepStrictEqual(press.sent, ["A", "B"]);

    assert.strictEqual(answerNext(), "B");
    await settle();
    assert.deepStrictEqual(press.sent, ["A", "B", "C"]);

    answerNext();
    await settle();
    assert.deepStrictEqual(press.sent, ["A", "B", "C"], "the queue sent something twice");
  });

  await test("typing far ahead of the board stops the sending, not the recording", async () => {
    await freshRecording();
    press.holdAnswers = true;

    // One request goes out and stalls; the rest pile up behind it.
    const typed = ["KeyA", "KeyB", "KeyC", "KeyD", "KeyE", "KeyF", "KeyG", "KeyH",
                   "KeyI", "KeyJ", "KeyK", "KeyL", "KeyM"];
    type(...typed);
    await settle();

    assert.deepStrictEqual(press.sent, ["A"], "it kept sending past the backlog limit");
    assert.match(problem.textContent, /too far behind to keep up/);
    assert.strictEqual(problem.style.display, "block");

    // Recording never stopped.
    assert.strictEqual(keysCount.textContent, String(typed.length));
    assert.strictEqual(statusText.textContent, "Recording...");

    // Nothing more is sent, even once the board catches up.
    answerNext();
    await settle();
    type("KeyN");
    await settle();
    assert.deepStrictEqual(press.sent, ["A"]);

    // Every key typed is in the saved script, the sent ones and the rest.
    const pressed = (await saveAndReadSteps())
      .filter((step) => step[0] === "press")
      .map((step) => step[1]);
    assert.deepStrictEqual(pressed, [...typed, "KeyN"].map((c) => c.replace("Key", "")));
  });

  await test("a board that stops answering says so, and a key that failed is still recorded", async () => {
    await freshRecording();
    press.holdAnswers = true;

    type("KeyA");
    await settle();
    press.waiting.shift().resolve(unreachable());
    await settle();

    assert.match(problem.textContent, /Not reaching the Pico/);
    assert.match(problem.textContent, /Check it's powered on/);

    // The key that failed to send is in the script like any other, with
    // nothing marking it out.
    assert.match(preview.textContent, /\["press", "A", 0.1\]/);
    assert.strictEqual(keysCount.textContent, "1");
  });

  await test("the warning clears the moment a send succeeds", async () => {
    // Carries on from the recording above, which is showing the warning.
    assert.match(problem.textContent, /Not reaching the Pico/);
    press.holdAnswers = false;

    type("KeyB");
    await settle();
    assert.strictEqual(problem.textContent, "");
    assert.strictEqual(problem.style.display, "none");
    assert.deepStrictEqual(press.sent, ["A", "B"]);
  });

  await test("the board's own words are shown when it is busy with a script", async () => {
    await freshRecording();
    press.holdAnswers = true;
    type("KeyA");
    await settle();
    press.waiting.shift().resolve(
      jsonResponse({ detail: "“XX3” is running, so that key was not sent" }, false, 409)
    );
    await settle();
    assert.strictEqual(problem.textContent, "“XX3” is running, so that key was not sent");
  });

  await test("with the switch off, keys are recorded and nothing is sent", async () => {
    await freshRecording({ live: false });
    type("KeyA", "KeyB");
    await settle();
    assert.deepStrictEqual(press.sent, []);
    const pressed = (await saveAndReadSteps()).filter((step) => step[0] === "press");
    assert.strictEqual(pressed.length, 2);
  });

  await test("the banner says whether keys are reaching the PS5", async () => {
    await freshRecording({ live: false });
    assert.strictEqual(
      banner.textContent,
      "Recording. Every key you press is saved to the script but not sent to " +
        "the PS5. Typing anywhere on this page is captured."
    );

    // Flicking the switch mid-recording changes what the banner promises.
    liveToggle.checked = true;
    liveToggle.dispatchEvent(new FakeEvent("change", { bubbles: true }));
    assert.strictEqual(
      banner.textContent,
      "Recording. Every key you press is sent to the PS5 and saved to the " +
        "script. Typing anywhere on this page is captured."
    );

    context.stopRecording();
    assert.strictEqual(banner.style.display, "none");
  });

  // ----- a held key is one hold, recorded and sent -----

  await test("holding a key records one press with how long it was held", async () => {
    await freshRecording({ live: false });
    hold("KeyS", 1000);
    const steps = await saveAndReadSteps();
    assert.deepStrictEqual(steps, [["press", "S", 1.0]]);
  });

  await test("the auto-repeat keydowns the OS fires add no extra steps", async () => {
    await freshRecording({ live: false });
    hold("KeyS", 1000, { repeats: 10 });
    assert.strictEqual(keysCount.textContent, "1", "one keystroke, not eleven");
    const steps = await saveAndReadSteps();
    assert.strictEqual(steps.length, 1, "and one step, not eleven");
  });

  await test("a quick tap still records as a 0.1 press", async () => {
    await freshRecording({ live: false });
    type("KeyA");
    const steps = await saveAndReadSteps();
    assert.deepStrictEqual(steps, [["press", "A", 0.1]]);
  });

  await test("the gap after a hold is measured from when the key came up", async () => {
    await freshRecording({ live: false });
    type("KeyA");
    pause(1000);
    hold("KeyS", 2000);
    pause(1000);
    type("KeyD");
    const steps = await saveAndReadSteps();
    assert.deepStrictEqual(steps, [
      ["press", "A", 0.1],
      ["wait", 1],
      ["press", "S", 2.0],
      ["wait", 1],
      ["press", "D", 0.1],
    ]);
  });

  await test("a held key reaches the PS5 as a down and an up, not a tap", async () => {
    await freshRecording({ live: true });
    hold("KeyS", 2000, { repeats: 19 });
    await settle();
    assert.deepStrictEqual(press.events, ["down:S", "up:S"]);
  });

  await test("the key stays down on the board for as long as the finger", async () => {
    await freshRecording({ live: true });
    down("KeyS");
    await settle();
    assert.deepStrictEqual(press.events, ["down:S"], "still held, nothing released yet");
    pause(3000);
    up("KeyS");
    await settle();
    assert.deepStrictEqual(press.events, ["down:S", "up:S"]);
  });

  await test("stopping mid-hold writes the duration and releases the key", async () => {
    await freshRecording({ live: true });
    down("KeyS");
    pause(2400);
    const steps = await saveAndReadSteps();
    assert.deepStrictEqual(steps, [["press", "S", 2.4]]);
    assert.ok(press.events.includes("up:S"), "Stop must not leave the key down");
  });

  await test("losing focus mid-hold closes it and releases the key", async () => {
    await freshRecording({ live: true });
    down("KeyS");
    pause(1500);
    testWindow.fire("blur");
    await settle();
    assert.deepStrictEqual(press.events, ["down:S", "up:S"]);
    assert.match(
      elementsById.get("recording-error").textContent,
      /Left this window while S was down/
    );
  });

  await test("with the switch off nothing is pressed or released", async () => {
    await freshRecording({ live: false });
    hold("KeyS", 1500);
    await settle();
    assert.deepStrictEqual(press.events, []);
  });

  await test("the board is told a take is starting, before any key", async () => {
    press.wakes = 0;
    await freshRecording({ live: true });
    await settle();
    assert.strictEqual(press.wakes, 1, "so the first key is not the slow one");
  });

  await test("a release still goes out after the backlog has given up", async () => {
    await freshRecording({ live: true });
    press.holdAnswers = true;
    down("KeyS");
    await settle();
    for (let i = 0; i < 40; i++) {
      type("KeyA");
      await settle(2);
    }
    press.holdAnswers = false;
    while (press.waiting.length > 0) press.waiting.shift().resolve(jsonResponse({ ok: true }));
    await settle();
    assert.ok(
      press.events.includes("up:S"),
      "giving up on typing must not strand S on the console"
    );
  });

  // The hold the board reports beats the one the browser timed
  //
  // The browser measures the finger: keydown to keyup. The board measures
  // the press it actually made, which is what the console saw and what
  // playback will reproduce. The two differ by the gap between the down
  // request's latency and the up request's, so the board's figure wins.

  await test("the hold the board reports replaces the one the browser timed", async () => {
    await freshRecording({ live: true });
    press.heldAnswer = 2.063;
    hold("KeyS", 2000);
    const steps = await saveAndReadSteps();
    assert.deepStrictEqual(steps, [["press", "S", 2.06]]);
  });

  await test("holds keep hundredths, so the board's figure is not rounded away", async () => {
    await freshRecording({ live: true });
    press.heldAnswer = 1.24;
    hold("KeyS", 1200);
    const steps = await saveAndReadSteps();
    assert.deepStrictEqual(steps, [["press", "S", 1.24]]);
  });

  await test("a board that reports nothing leaves the browser's figure alone", async () => {
    await freshRecording({ live: true });
    press.heldAnswer = null;
    hold("KeyS", 2000);
    const steps = await saveAndReadSteps();
    assert.deepStrictEqual(steps, [["press", "S", 2]]);
  });

  await test("with the switch off the browser's figure is what gets saved", async () => {
    await freshRecording({ live: false });
    press.heldAnswer = 9.99;
    hold("KeyS", 1500);
    const steps = await saveAndReadSteps();
    assert.deepStrictEqual(
      steps,
      [["press", "S", 1.5]],
      "nothing was sent, so the board has nothing to report about"
    );
  });

  await test("a board-reported tap still gets the floor, not a hold too short to feel", async () => {
    await freshRecording({ live: true });
    press.heldAnswer = 0.012;
    type("KeyA");
    const steps = await saveAndReadSteps();
    assert.deepStrictEqual(steps, [["press", "A", 0.1]]);
  });

  await test("waits stay on the 0.1 grid", async () => {
    await freshRecording({ live: true });
    press.heldAnswer = 0.5;
    hold("KeyS", 500);
    pause(1370);
    hold("KeyD", 500);
    const steps = await saveAndReadSteps();
    assert.deepStrictEqual(steps, [
      ["press", "S", 0.5],
      ["wait", 1.4],
      ["press", "D", 0.5],
    ]);
  });

  await test("a save does not outrun the board's answer", async () => {
    await freshRecording({ live: true });
    press.heldAnswer = 3.21;
    down("KeyS");
    await settle();
    pause(3200);
    // The release is answered only after Save has been asked for, which is
    // the race: without waiting for the queue, the last key of a take keeps
    // the browser's estimate.
    press.holdAnswers = true;
    up("KeyS");
    const saving = saveAndReadSteps();
    await settle();
    press.holdAnswers = false;
    while (press.waiting.length > 0) {
      press.waiting.shift().resolve(jsonResponse({ ok: true, held: 3.21 }));
    }
    const steps = await saving;
    assert.deepStrictEqual(steps, [["press", "S", 3.21]]);
  });

  const failed = results.filter(([ok]) => !ok).length;
  console.log("");
  console.log(`${results.length - failed} of ${results.length} passed`);
  process.exit(failed === 0 ? 0 : 1);
}

main();
