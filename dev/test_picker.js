// Tests for the editor's key picker, run without a browser.
//
//     node dev/test_picker.js
//
// Issue #7 shipped a picker that did not work on the page: rows opened with
// an empty key box and the dropdown never appeared. Nothing here needs the
// Pico, the webapp, or a browser: the real webapp/app/static/app.js is run
// against the stand-in DOM in dev/fake_dom.js, using the real step-row
// markup from the real templates and the real payload the server sends.

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { execFileSync } = require("node:child_process");
const { FakeElement, FakeEvent, document, parseFragment, elementsById } = require("./fake_dom.js");

const REPO = path.resolve(__dirname, "..");
const APP_JS = path.join(REPO, "webapp/app/static/app.js");
const INDEX_HTML = path.join(REPO, "webapp/app/templates/index.html");

// The list exactly as the server sends it: read out of the webapp's own
// code rather than typed out here, so this cannot drift from what a browser
// actually receives.
function realKeycodePayload() {
  const script = [
    "import json, sys",
    `sys.path.insert(0, ${JSON.stringify(path.join(REPO, "webapp"))})`,
    "from app import keycodes",
    `keycodes.FIRMWARE_DIR = __import__("pathlib").Path(${JSON.stringify(path.join(REPO, "src"))})`,
    'print(json.dumps({"groups": keycodes.grouped()}))',
  ].join("\n");
  return JSON.parse(execFileSync("python3", ["-c", script], { encoding: "utf-8" }));
}

// The step templates the editor clones, taken from the real page.
function loadTemplates() {
  const html = fs.readFileSync(INDEX_HTML, "utf-8");
  for (const match of html.matchAll(/<template id="(tpl-step-[a-z]+)">([\s\S]*?)<\/template>/g)) {
    const [, id, inner] = match;
    elementsById.set(id, { id, content: { cloneNode: () => parseFragment(inner) } });
  }
}

const KEYCODES = realKeycodePayload();
const SCRIPT = {
  id: "s1",
  name: "XX3 (low ilvl hq craft)",
  description: "",
  steps: [["press", "ENTER", 0.1], ["wait", 2], ["press", "EIGHT", 0.1], ["press", "UP_ARROW", 0.2]],
};

const alerts = [];
const requests = [];
let keycodesFail = false;

function response(body, ok = true, status = 200) {
  const text = JSON.stringify(body);
  return Promise.resolve({
    ok,
    status,
    text: () => Promise.resolve(text),
    json: () => Promise.resolve(JSON.parse(text)),
  });
}

function fakeFetch(url, opts = {}) {
  requests.push({ url, method: opts.method || "GET", body: opts.body });
  if (url === "/api/keycodes") {
    if (keycodesFail) {
      // What the browser sees while the container is restarting.
      return Promise.resolve({
        ok: false,
        status: 502,
        text: () => Promise.resolve("<html>Bad Gateway</html>"),
        json: () => Promise.reject(new SyntaxError("Unexpected token '<'")),
      });
    }
    return response(KEYCODES);
  }
  if (url === "/api/scripts") return response([SCRIPT]);
  if (url === `/api/scripts/${SCRIPT.id}`) return response(SCRIPT);
  if (url.endsWith("/preview")) return response({ ok: true, step_count: 4, duration_seconds: 2.4 });
  if (url === "/api/history") return response([]);
  if (url === "/api/settings") return response({ device_url: "http://localhost:8085" });
  if (url === "/api/device/status") return response({ ok: false, error: "no device in this test" });
  return response({});
}

loadTemplates();
process.on("unhandledRejection", () => {});

const context = vm.createContext({
  document,
  window: { location: { href: "/" } },
  navigator: { platform: "MacIntel" },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
  fetch: fakeFetch,
  alert: (message) => alerts.push(message),
  confirm: () => true,
  console,
  setInterval: () => 0,
  clearInterval: () => {},
  setTimeout: (fn) => { fn(); return 0; },
  clearTimeout: () => {},
  Event: FakeEvent,
});
vm.runInContext(fs.readFileSync(APP_JS, "utf-8"), context, { filename: "app.js" });

// --- the tests ----------------------------------------------------------

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

function pressRow(keyName) {
  const row = context.buildStepRow(["press", keyName, 0.1], SCRIPT.id);
  document.body.appendChild(row);
  return {
    row,
    hidden: row.querySelector(".step-key"),
    search: row.querySelector(".step-key-search"),
    options: row.querySelector(".step-key-options"),
    error: row.querySelector(".step-key-error"),
    capture: row.querySelector(".step-key-capture"),
  };
}

function optionLabels(options) {
  return options.querySelectorAll(".key-option").map(o => o.textContent);
}

async function main() {
  await context.loadKeycodes();

  await test("an existing step opens showing its key, not an empty box", () => {
    const { hidden, search } = pressRow("ENTER");
    assert.strictEqual(hidden.value, "ENTER");
    assert.strictEqual(search.value, "Enter (ENTER)");
  });

  await test("a key whose everyday name differs shows both spellings", () => {
    assert.strictEqual(pressRow("EIGHT").search.value, "8 (EIGHT)");
    assert.strictEqual(pressRow("UP_ARROW").search.value, "Up arrow (UP_ARROW)");
  });

  await test("typing 'up' offers the up arrow", () => {
    const { search, options } = pressRow("");
    search.typeText("up");
    assert.strictEqual(options.hidden, false, "the dropdown stayed closed");
    assert.ok(optionLabels(options).includes("Up arrow (UP_ARROW)"), optionLabels(options).slice(0, 5).join(" | "));
  });

  await test("typing '8' offers the digit", () => {
    const { search, options } = pressRow("");
    search.typeText("8");
    assert.ok(optionLabels(options).includes("8 (EIGHT)"), optionLabels(options).slice(0, 5).join(" | "));
  });

  await test("typing something that is not a key says so", () => {
    const { search, options } = pressRow("");
    search.typeText("zzz");
    assert.strictEqual(optionLabels(options).length, 0);
    assert.match(options.textContent, /No key matches that/);
  });

  await test("focusing the box opens the whole list", () => {
    const { search, options } = pressRow("");
    search.focus();
    assert.strictEqual(options.hidden, false);
    assert.strictEqual(optionLabels(options).length, 129);
  });

  await test("choosing an option fills in the row", () => {
    const { hidden, search, options } = pressRow("");
    search.typeText("down");
    const option = options.querySelectorAll(".key-option").find(o => o.textContent === "Down arrow (DOWN_ARROW)");
    option.dispatchEvent(new FakeEvent("mousedown", { bubbles: true }));
    assert.strictEqual(hidden.value, "DOWN_ARROW");
    assert.strictEqual(search.value, "Down arrow (DOWN_ARROW)");
    assert.strictEqual(options.hidden, true);
  });

  await test("'Press a key' captures the next keypress into the row", () => {
    const { hidden, search, capture } = pressRow("");
    capture.click();
    assert.strictEqual(capture.textContent, "Press any key");
    document.dispatchEvent(new FakeEvent("keydown", { bubbles: true, code: "ArrowUp", key: "ArrowUp" }));
    assert.strictEqual(hidden.value, "UP_ARROW");
    assert.strictEqual(search.value, "Up arrow (UP_ARROW)");
    assert.strictEqual(capture.textContent, "Press a key");
  });

  await test("a key the device does not have is kept, shown, and flagged", () => {
    const { row, hidden, search, error } = pressRow("UP");
    assert.strictEqual(search.value, "UP", "the value someone saved earlier must stay on screen");
    assert.strictEqual(hidden.value, "");
    assert.strictEqual(error.textContent, "There is no key called 'UP'. Pick a key.");
    assert.ok(row.classList.contains("step-invalid"));
  });

  await test("a script with a bad key cannot be saved", async () => {
    alerts.length = 0;
    requests.length = 0;
    await context.renderEditor(SCRIPT.id);
    const editor = document.getElementById("main").querySelector(".editor");
    const rows = editor.querySelector("#steps-list");
    rows.appendChild(context.buildStepRow(["press", "UP", 0.1], SCRIPT.id));
    await editor.querySelector("#save-btn").onclick();
    assert.deepStrictEqual(alerts, ["One step still needs a key."]);
    assert.strictEqual(requests.filter(r => r.method === "PUT").length, 0, "it saved anyway");
  });

  await test("a script nobody edited saves back exactly as it was", () => {
    const rows = new FakeElement("div");
    for (const step of SCRIPT.steps) rows.appendChild(context.buildStepRow(step, SCRIPT.id));
    const { steps, unresolved } = context.readSteps(rows);
    assert.strictEqual(unresolved, false);
    // Compared as text: the steps are built inside the sandbox, so their
    // arrays are not the same objects the test's own arrays are.
    assert.strictEqual(JSON.stringify(steps), JSON.stringify(SCRIPT.steps));
  });

  await test("a key list that fails to load says so and can be retried", async () => {
    // What a page open during a webapp restart sees.
    keycodesFail = true;
    await context.loadKeycodes();
    await context.renderEditor(SCRIPT.id);
    const editor = document.getElementById("main").querySelector(".editor");
    const warning = editor.querySelector("#key-list-warning");
    assert.ok(warning, "nothing on screen said the key list was missing");
    assert.match(warning.textContent, /The list of keys didn't load/);

    // Rows still show the key each step holds, and do not call it wrong.
    const firstRow = editor.querySelector("#steps-list").children[0];
    assert.strictEqual(firstRow.querySelector(".step-key-search").value, "ENTER");
    assert.strictEqual(firstRow.querySelector(".step-key-error").textContent, "");

    // Saving is refused, and says which thing is missing.
    alerts.length = 0;
    await editor.querySelector("#save-btn").onclick();
    assert.deepStrictEqual(alerts, [
      "The list of keys hasn't loaded, so nothing can be saved yet. Use Try again above.",
    ]);

    // The webapp comes back, and Try again puts the pickers to work without
    // losing the edit in progress.
    keycodesFail = false;
    editor.querySelector("#f-name").value = "renamed while it was broken";
    await editor.querySelector("#retry-keycodes").onclick();
    assert.ok(editor.querySelector("#key-list-warning") === null, "the warning stayed up");
    assert.strictEqual(firstRow.querySelector(".step-key-search").value, "Enter (ENTER)");
    assert.strictEqual(firstRow.querySelector(".step-key").value, "ENTER");
    assert.strictEqual(editor.querySelector("#f-name").value, "renamed while it was broken");

    const { steps, unresolved } = context.readSteps(editor.querySelector("#steps-list"));
    assert.strictEqual(unresolved, false);
    assert.strictEqual(JSON.stringify(steps), JSON.stringify(SCRIPT.steps));
  });

  const failed = results.filter(([ok]) => !ok).length;
  console.log("");
  console.log(`${results.length - failed} of ${results.length} passed`);
  process.exit(failed === 0 ? 0 : 1);
}

main();
