// Tests that the page still works when its HTML is missing an element that
// app.js expects, run without a browser or hardware.
//
//     node dev/test_startup.js
//
// This is the failure that happened twice for real: a browser held a cached
// index.html from before the "send keys as they are typed" checkbox existed
// and loaded a fresh app.js that expects it. app.js wires its elements at
// the top level, so the missing checkbox threw while the file was still
// loading and nothing after that line ever ran -- no status polling, no
// script list. The page drew itself and then did nothing at all.
//
// A missing checkbox should cost the checkbox. Everything below is that
// promise, written down: the real webapp/app/static/app.js is loaded against
// a DOM with "recording-live" taken out, and the rest of the page is
// expected to come up as usual.

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { FakeEvent, document, elementsById, missingIds } = require("./fake_dom.js");

const REPO = path.resolve(__dirname, "..");
const APP_JS = path.join(REPO, "webapp/app/static/app.js");

// The element the stale HTML did not have.
const MISSING_ID = "recording-live";
missingIds.add(MISSING_ID);

const SCRIPTS = [
  { id: "s1", name: "Warm up", steps: [["press", "A", 0.1]] },
  { id: "s2", name: "Grind loop", steps: [["press", "B", 0.1]] },
];

function jsonResponse(body, ok = true, status = 200) {
  const text = JSON.stringify(body);
  return {
    ok,
    status,
    text: () => Promise.resolve(text),
    json: () => Promise.resolve(JSON.parse(text)),
  };
}

function fakeFetch(url) {
  if (url === "/api/scripts") return Promise.resolve(jsonResponse(SCRIPTS));
  if (url === "/api/keycodes") return Promise.resolve(jsonResponse({ groups: [] }));
  if (url === "/api/history") return Promise.resolve(jsonResponse([]));
  if (url === "/api/settings") {
    return Promise.resolve(jsonResponse({ device_url: "http://localhost:8085" }));
  }
  if (url === "/api/device/press/supported") {
    return Promise.resolve(jsonResponse({ supported: true }));
  }
  if (url === "/api/device/status") {
    return Promise.resolve(jsonResponse({ running: false, loop: 0, loops: 0, step: 0, steps: 0 }));
  }
  return Promise.resolve(jsonResponse({}));
}

process.on("unhandledRejection", (e) => {
  console.log("UNHANDLED REJECTION " + (e && e.stack ? e.stack : e));
});

// Everything app.js says on the console, so the test can check it named the
// element it could not find.
const warnings = [];

const context = vm.createContext({
  document,
  window: { location: { href: "/" } },
  navigator: { platform: "MacIntel" },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: fakeFetch,
  alert: () => {},
  confirm: () => true,
  console: Object.assign(Object.create(console), {
    warn: (...args) => { warnings.push(args.join(" ")); },
  }),
  setInterval: () => 0,
  clearInterval: () => {},
  setTimeout: (fn) => { fn(); return 0; },
  clearTimeout: () => {},
  Event: FakeEvent,
});

// Lets every pending promise settle, the way the browser would.
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

async function main() {
  // Loading the file is the first assertion. If this throws, the page is
  // dead in a browser too, and nothing below can be checked at all.
  let loadError = null;
  try {
    vm.runInContext(fs.readFileSync(APP_JS, "utf-8"), context, { filename: "app.js" });
  } catch (e) {
    loadError = e;
  }
  test("app.js loads with " + MISSING_ID + " missing from the page", () => {
    assert.strictEqual(loadError, null, "loading threw: " + (loadError && loadError.stack));
  });

  if (loadError) {
    console.log("\n0 of 4 passed -- app.js did not load, so the rest could not be tried.");
    process.exit(1);
  }

  await settle();

  test("it says on the console which element it could not find", () => {
    const named = warnings.filter((w) => w.includes(MISSING_ID));
    assert.strictEqual(named.length, 1, "expected one warning naming " + MISSING_ID +
      ", got: " + JSON.stringify(warnings));
  });

  test("the status panel is filled in", () => {
    assert.strictEqual(elementsById.get("st-running").textContent, "not running");
    assert.strictEqual(elementsById.get("run-stop-btn").disabled, true);
  });

  test("the script list is rendered", () => {
    const listed = elementsById.get("main").textContent;
    for (const script of SCRIPTS) {
      assert.ok(listed.includes(script.name), "the list is missing " + script.name);
    }
  });

  const passed = results.filter(([ok]) => ok).length;
  console.log(`\n${passed} of ${results.length} passed`);
  process.exit(passed === results.length ? 0 : 1);
}

main();
