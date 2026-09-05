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
const { FakeEvent, document, elementsById } = require("./fake_dom.js");

const REPO = path.resolve(__dirname, "..");
const APP_JS = path.join(REPO, "webapp/app/static/app.js");

// What the device stub does with a /api/device/press request.
const press = {
  // Every request that has been made, in the order it was made.
  sent: [],
  // Requests still waiting for an answer, when holdAnswers is on.
  waiting: [],
  holdAnswers: false,
  supported: true,
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
  if (url === "/api/device/press") {
    const key = JSON.parse(opts.body).key;
    press.sent.push(key);
    if (press.holdAnswers) {
      return new Promise((resolve) => press.waiting.push({ key, resolve }));
    }
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

const context = vm.createContext({
  document,
  window: { location: { href: "/" } },
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
  await context.saveRecordedScript();
  return savedSteps;
}

// Lets every pending promise settle, the way the browser would between
// keystrokes. Nothing here waits on real time.
async function settle(rounds = 20) {
  for (let i = 0; i < rounds; i++) await new Promise((r) => setImmediate(r));
}

function type(...codes) {
  for (const code of codes) {
    document.dispatchEvent(
      new FakeEvent("keydown", { bubbles: true, code, key: code.replace("Key", "").toLowerCase() })
    );
  }
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

  const failed = results.filter(([ok]) => !ok).length;
  console.log("");
  console.log(`${results.length - failed} of ${results.length} passed`);
  process.exit(failed === 0 ? 0 : 1);
}

main();
