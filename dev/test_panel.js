// Tests what the run panel says while a nested script is running, without a
// browser, a webapp or hardware.
//
//     node dev/test_panel.js
//
// This is the half of issue #3 that Rosy actually looks at. "Warm up, then
// Gathering a thousand times, then Cash out" is one loop of one, so the old
// panel read "Loop 0 / 1" for four hours -- less than it told her before.
// The device now reports which part it is on, which iteration of it, and
// how long is left, and this checks the panel says so in words.

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { FakeEvent, document, elementsById } = require("./fake_dom.js");

const REPO = path.resolve(__dirname, "..");
const APP_JS = path.join(REPO, "webapp/app/static/app.js");

// What the device says while it is 738 iterations into the second of three
// parts, with a bit over an hour to go.
let deviceStatus = {
  running: true,
  loop_count: 0,
  target_loops: 1,
  current_step: 3,
  total_steps: 9,
  depth: 2,
  position: { part: 2, parts: 3, iteration: 738, iterations: 1000 },
  estimated_seconds_remaining: 4320,
  last_error: null,
  last_fault: null,
  features: ["repeat"],
  part_names: ["Warm up", "Gathering", "Cash out"],
};

function jsonResponse(body) {
  const text = JSON.stringify(body);
  return { ok: true, status: 200, text: () => Promise.resolve(text), json: () => Promise.resolve(JSON.parse(text)) };
}

function fakeFetch(url) {
  if (url === "/api/device/status") return Promise.resolve(jsonResponse(deviceStatus));
  if (url === "/api/scripts") return Promise.resolve(jsonResponse([]));
  if (url === "/api/keycodes") return Promise.resolve(jsonResponse({ groups: [] }));
  if (url === "/api/history") return Promise.resolve(jsonResponse([]));
  if (url === "/api/settings") return Promise.resolve(jsonResponse({ device_url: "http://localhost:8085" }));
  if (url === "/api/device/press/supported") return Promise.resolve(jsonResponse({ supported: true }));
  return Promise.resolve(jsonResponse({}));
}

const context = vm.createContext({
  document,
  window: { location: { href: "/" } },
  navigator: { platform: "MacIntel" },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: fakeFetch,
  alert: () => {},
  confirm: () => true,
  console: Object.assign(Object.create(console), { warn: () => {} }),
  setInterval: () => 0,
  clearInterval: () => {},
  setTimeout: (fn) => { fn(); return 0; },
  clearTimeout: () => {},
  Event: FakeEvent,
});

async function settle(rounds = 40) {
  for (let i = 0; i < rounds; i++) await new Promise((r) => setImmediate(r));
}

const results = [];
function test(name, fn) {
  try {
    fn();
    results.push([true, name]);
    console.log("PASS " + name);
  } catch (e) {
    results.push([false, name]);
    console.log("FAIL " + name + "\n      " + String(e.message).split("\n").join("\n      "));
  }
}

function text(id) {
  return elementsById.get(id).textContent;
}

async function main() {
  vm.runInContext(fs.readFileSync(APP_JS, "utf-8"), context, { filename: "app.js" });
  await settle();

  // The fake DOM invents any element asked for, so the rows below would
  // pass even if the page had never gained them. Check the real page.
  test("the page has the rows the panel fills in", () => {
    const page = fs.readFileSync(path.join(REPO, "webapp/app/templates/index.html"), "utf-8");
    for (const id of ["st-part", "st-loop-label", "st-loop", "st-step", "st-eta"]) {
      assert.ok(page.includes(`id="${id}"`), "index.html has no " + id);
    }
  });

  test("it says which part of the job is running", () => {
    assert.strictEqual(text("st-part"), "part 2 of 3");
  });

  test("it says which repeat of that part, by name", () => {
    assert.strictEqual(text("st-loop"), "Gathering, 738 of 1000");
    assert.strictEqual(text("st-loop-label"), "Repeat");
  });

  test("it says roughly how long is left", () => {
    assert.strictEqual(text("st-eta"), "about 1h 12m left");
  });

  test("it says which step inside the repeat", () => {
    assert.strictEqual(text("st-step"), "4 / 9");
  });

  // A script that isn't simply a list of other scripts has no parts to
  // count, so the honest thing is the step number.
  deviceStatus = Object.assign({}, deviceStatus, {
    position: { part: 1, parts: 2, iteration: null, iterations: null },
    depth: 1,
    current_step: 0,
    total_steps: 2,
    part_names: [],
  });
  await context.pollStatus();
  await settle();

  test("a script with no named parts falls back to the step number", () => {
    assert.strictEqual(text("st-part"), "step 1 of 2");
    assert.strictEqual(text("st-loop"), "0 / 1");
    assert.strictEqual(text("st-loop-label"), "Loop");
  });

  // A failure deep inside a repeat, with the part named by the webapp.
  deviceStatus = Object.assign({}, deviceStatus, {
    running: false,
    last_error:
      "stopped at part 2 (Gathering), repeat 738 of 1000, step 4: " +
      "ValueError: there is no key called 'UP'",
  });
  await context.pollStatus();
  await settle();

  test("a failure inside a repeat is shown with its position", () => {
    const shown = text("st-fault");
    assert.ok(shown.includes("part 2 (Gathering)"), "no part in: " + shown);
    assert.ok(shown.includes("repeat 738 of 1000"), "no repeat in: " + shown);
    assert.ok(shown.includes("there is no key called 'UP'"), "no reason in: " + shown);
  });

  test("the time left goes away when nothing is running", () => {
    assert.strictEqual(text("st-eta"), "-");
  });

  const passed = results.filter(([ok]) => ok).length;
  console.log(`\n${passed} of ${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

main();
