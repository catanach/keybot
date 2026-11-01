// Tests for where a finished recording goes (issue #19), run without a
// browser, a webapp or hardware.
//
//     node dev/test_recording_save.js
//
// The real webapp/app/static/app.js runs against the stand-in DOM in
// dev/fake_dom.js, with a stub server whose answers each test controls.
// The reload test boots the page twice over one browser storage, which is
// the only way to check that a take survives the tab going away -- the
// thing that used to lose one, silently, after the keys had already been
// pressed on the PS5.

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { execFileSync } = require("node:child_process");

const REPO = path.resolve(__dirname, "..");
const APP_JS = path.join(REPO, "webapp/app/static/app.js");
const INDEX_HTML = path.join(REPO, "webapp/app/templates/index.html");

// The key list exactly as the server sends it, read out of the webapp's own
// code so this cannot drift from what a browser receives.
const KEYCODES = JSON.parse(
  execFileSync(
    "python3",
    [
      "-c",
      [
        "import json, sys",
        `sys.path.insert(0, ${JSON.stringify(path.join(REPO, "webapp"))})`,
        "from app import keycodes",
        `keycodes.FIRMWARE_DIR = __import__("pathlib").Path(${JSON.stringify(
          path.join(REPO, "src")
        )})`,
        'print(json.dumps({"groups": keycodes.grouped()}))',
      ].join("\n"),
    ],
    { encoding: "utf-8" }
  )
);

const TARGET_SCRIPT = {
  id: "s1",
  name: "Overnight farm",
  description: "",
  rev: 4,
  steps: [
    ["press", "ENTER", 0.1],
    ["wait", 2],
    ["press", "EIGHT", 0.1],
    ["press", "UP_ARROW", 0.2],
  ],
};

// What the stub server does. Each test sets what it needs before booting.
const server = {
  scripts: [],
  nextName: "Recording 1",
  preview: { ok: true, step_count: 4, duration_seconds: 2.4, limit: 500 },
  saveStatus: 200,
  saveBody: null,
  lastRecording: null,
  requests: [],
};

function resetServer() {
  server.scripts = [TARGET_SCRIPT];
  server.nextName = "Recording 1";
  server.preview = { ok: true, step_count: 4, duration_seconds: 2.4, limit: 500 };
  server.saveStatus = 200;
  server.saveBody = null;
  server.lastRecording = null;
  server.requests = [];
}

function jsonResponse(body, ok = true, status = 200) {
  const text = JSON.stringify(body);
  return Promise.resolve({
    ok,
    status,
    text: () => Promise.resolve(text),
    json: () => Promise.resolve(JSON.parse(text)),
  });
}

function summary(script) {
  return {
    id: script.id,
    name: script.name,
    description: script.description || "",
    rev: script.rev,
    step_count: script.steps.length,
  };
}

function fakeFetch(url, opts = {}) {
  const method = opts.method || "GET";
  const body = opts.body ? JSON.parse(opts.body) : null;
  server.requests.push({ url, method, body });

  if (url === "/api/keycodes") return jsonResponse(KEYCODES);
  if (url === "/api/scripts" && method === "GET") {
    return jsonResponse(server.scripts.map(summary));
  }
  if (url === "/api/scripts" && method === "POST") {
    const created = { id: "rec1", name: body.name, description: "", rev: 1, steps: body.steps };
    server.scripts = server.scripts.concat([created]);
    server.lastRecording = body;
    return jsonResponse(created);
  }
  if (url === "/api/scripts/preview") return jsonResponse(server.preview);
  if (url === "/api/recordings/next-name") return jsonResponse({ name: server.nextName });
  if (url === "/api/recordings/save") {
    server.lastRecording = body;
    if (server.saveStatus !== 200) {
      return jsonResponse(server.saveBody, false, server.saveStatus);
    }
    return jsonResponse(
      server.saveBody || {
        script: { id: "rec1", name: body.name, steps: body.steps },
        target: null,
        warning: "",
      }
    );
  }
  if (url.endsWith("/preview")) return jsonResponse(server.preview);
  if (url === "/api/history") return jsonResponse([]);
  if (url === "/api/settings") return jsonResponse({ device_url: "http://localhost:8085" });
  if (url === "/api/device/status") {
    return jsonResponse({ detail: "no device in this test" }, false, 502);
  }
  if (url === "/api/device/press/supported") return jsonResponse({ supported: true });

  const match = /^\/api\/scripts\/([^/]+)$/.exec(url);
  if (match) {
    const found = server.scripts.find((s) => s.id === match[1]);
    if (!found) return jsonResponse({ detail: "script not found" }, false, 404);
    return jsonResponse(found);
  }
  return jsonResponse({});
}

process.on("unhandledRejection", () => {});

// Boots the page: a DOM that has never been used, the real app.js, and the
// browser storage handed in -- which is what makes a reload a reload.
function boot(store) {
  delete require.cache[require.resolve("./fake_dom.js")];
  const dom = require("./fake_dom.js");

  const html = fs.readFileSync(INDEX_HTML, "utf-8");
  for (const found of html.matchAll(/<template id="(tpl-step-[a-z]+)">([\s\S]*?)<\/template>/g)) {
    const [, id, inner] = found;
    dom.elementsById.set(id, { id, content: { cloneNode: () => dom.parseFragment(inner) } });
  }

  const confirms = [];
  let confirmAnswer = true;
  const alerts = [];
  const context = vm.createContext({
    document: dom.document,
    window: { location: { href: "/" } },
    navigator: { platform: "MacIntel" },
    localStorage: {
      getItem: (key) => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => store.set(key, String(value)),
      removeItem: (key) => store.delete(key),
    },
    fetch: fakeFetch,
    alert: (message) => alerts.push(message),
    confirm: (message) => {
      confirms.push(message);
      return confirmAnswer;
    },
    console,
    setInterval: () => 0,
    clearInterval: () => {},
    setTimeout: (fn) => {
      fn();
      return 0;
    },
    clearTimeout: () => {},
    Event: dom.FakeEvent,
  });
  vm.runInContext(fs.readFileSync(APP_JS, "utf-8"), context, { filename: "app.js" });

  const page = {
    context,
    dom,
    confirms,
    alerts,
    answerConfirm(answer) {
      confirmAnswer = answer;
    },
    el(id) {
      return dom.document.getElementById(id);
    },
    text(id) {
      return page.el(id).textContent;
    },
    type(...codes) {
      for (const code of codes) {
        dom.document.dispatchEvent(
          new dom.FakeEvent("keydown", {
            bubbles: true,
            code,
            key: code.replace("Key", "").toLowerCase(),
          })
        );
      }
    },
  };
  return page;
}

// Lets every pending promise settle, the way a browser would between one
// thing happening and the next. Nothing here waits on real time.
async function settle(rounds = 30) {
  for (let i = 0; i < rounds; i++) await new Promise((r) => setImmediate(r));
}

function draftIn(store) {
  const raw = store.get("recordingDraft");
  return raw ? JSON.parse(raw) : null;
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

async function recordThreeKeys(store) {
  const page = boot(store);
  await settle();
  page.el("recording-live").checked = true;
  page.context.startRecording();
  page.type("KeyA", "KeyB", "KeyC");
  await settle();
  return page;
}

async function main() {
  await test("a recording survives the page being reloaded under it", async () => {
    resetServer();
    const store = new Map();
    await recordThreeKeys(store);
    // The tab goes away here, mid-recording, with nothing saved.
    assert.strictEqual(draftIn(store).steps.filter((s) => s[0] === "press").length, 3);

    const reopened = boot(store);
    await settle();

    assert.strictEqual(reopened.el("recording-save-panel").style.display, "block");
    assert.strictEqual(reopened.text("recording-keys"), "3");
    assert.match(reopened.text("recording-save-summary"), /^Recorded 3 keys over /);

    // And it is a real take, not just a number on screen.
    reopened.el("recording-name").value = "Recording 1";
    await reopened.context.saveRecordedScript();
    await settle();
    assert.deepStrictEqual(
      server.lastRecording.steps.filter((s) => s[0] === "press").map((s) => s[1]),
      ["A", "B", "C"]
    );
    assert.strictEqual(draftIn(store), null, "the draft outlived the save");
  });

  await test("the panel offers the script the editor was showing, by name", async () => {
    resetServer();
    const page = boot(new Map());
    await settle();
    await page.context.renderEditor("s1");
    page.context.startRecording();
    page.type("KeyA");
    await settle();
    page.context.stopRecording();
    await settle();

    assert.strictEqual(page.el("recording-save-target-row").style.display, "block");
    assert.strictEqual(page.text("recording-save-target-label"), "Part of “Overnight farm”");
    // A new script is what it offers first.
    assert.strictEqual(page.el("recording-save-new").checked, true);
    assert.strictEqual(page.el("recording-save-target").checked, false);
    assert.strictEqual(page.el("recording-name").value, "Recording 1");
  });

  await test("a script deleted between Stop and Save is offered no more", async () => {
    resetServer();
    const page = boot(new Map());
    await settle();
    await page.context.renderEditor("s1");
    page.context.startRecording();
    page.type("KeyA");
    await settle();
    // Deleted in another tab while she was still typing.
    server.scripts = [];
    page.context.stopRecording();
    await settle();

    assert.strictEqual(page.el("recording-save-target").disabled, true);
    assert.match(page.text("recording-save-target-note"), /isn't there any more/);
    assert.strictEqual(page.el("recording-save-new").checked, true);
  });

  await test("discarding says the keys already reached the PS5", async () => {
    resetServer();
    const store = new Map();
    const page = await recordThreeKeys(store);
    page.context.stopRecording();
    await settle();

    page.answerConfirm(false);
    page.el("recording-cancel-btn").click();
    assert.strictEqual(
      page.confirms[page.confirms.length - 1],
      "Discard 3 recorded keys? They were already sent to the PS5 and can't be un-sent."
    );
    // Saying no keeps the take, and keeps the copy kept for a reload.
    assert.strictEqual(page.text("recording-keys"), "3");
    assert.strictEqual(draftIn(store).steps.length > 0, true);

    page.answerConfirm(true);
    page.el("recording-cancel-btn").click();
    assert.strictEqual(page.el("recording-save-panel").style.display, "none");
    assert.strictEqual(draftIn(store), null);
  });

  await test("a recording saved with the Run step unadded says so and is kept", async () => {
    resetServer();
    const store = new Map();
    const page = await recordThreeKeys(store);
    page.context.stopRecording();
    await settle();
    server.saveBody = {
      script: { id: "rec1", name: "Recording 3", steps: [] },
      target: null,
      warning:
        "Saved as “Recording 3”, but couldn't add the Run step to “Gathering”. " +
        "The recording is safe, add the step yourself.",
    };
    await page.context.saveRecordedScript();
    await settle();

    assert.match(page.text("recording-note"), /couldn't add the Run step/);
    assert.strictEqual(page.el("recording-note").style.display, "block");
    // It was saved, so the panel is done with and nothing is left to lose.
    assert.strictEqual(page.el("recording-save-panel").style.display, "none");
    assert.strictEqual(draftIn(store), null);
  });

  await test("a script changed in another tab leaves the recording where it is", async () => {
    resetServer();
    const store = new Map();
    const page = await recordThreeKeys(store);
    page.context.stopRecording();
    await settle();
    page.el("recording-save-target").checked = true;
    page.el("recording-save-target").dispatchEvent(
      new page.dom.FakeEvent("change", { bubbles: true })
    );
    server.saveStatus = 409;
    server.saveBody = {
      detail: "“Overnight farm” changed in another tab, reload before saving",
    };
    await page.context.saveRecordedScript();
    await settle();

    assert.strictEqual(
      page.text("recording-error"),
      "“Overnight farm” changed in another tab, reload before saving"
    );
    // Nothing was thrown away: the panel, the keys and the saved copy are
    // all still there to try again with.
    assert.strictEqual(page.el("recording-save-panel").style.display, "block");
    assert.strictEqual(page.text("recording-keys"), "3");
    assert.strictEqual(draftIn(store).steps.filter((s) => s[0] === "press").length, 3);
  });

  await test("joining the open script adds rows to the editor and saves nothing over it", async () => {
    resetServer();
    const store = new Map();
    const page = boot(store);
    await settle();
    await page.context.renderEditor("s1");
    page.context.startRecording();
    page.type("KeyA");
    await settle();
    page.context.stopRecording();
    await settle();
    page.el("recording-save-target").checked = true;
    page.el("recording-save-target").dispatchEvent(
      new page.dom.FakeEvent("change", { bubbles: true })
    );
    page.el("recording-name").value = "Recording 1";
    await page.context.saveRecordedScript();
    await settle();

    const rows = page.el("steps-list").children;
    assert.strictEqual(rows.length, TARGET_SCRIPT.steps.length + 2);
    const gap = rows[rows.length - 2];
    assert.strictEqual(gap.dataset.kind, "wait");
    assert.strictEqual(gap.querySelector(".step-seconds").value, 1);
    assert.strictEqual(gap.querySelector(".step-note").textContent, "Gap before the recorded keys");
    const run = rows[rows.length - 1];
    assert.strictEqual(run.dataset.kind, "run");
    assert.strictEqual(run.querySelector(".step-ref").value, "rec1");
    assert.strictEqual(run.querySelector(".step-times").value, 1);

    // The recording is a script of its own, and the script being joined was
    // never written to -- her unsaved rows are still hers to save.
    assert.deepStrictEqual(server.lastRecording.steps, [["press", "A", 0.1]]);
    const puts = server.requests.filter((r) => r.method === "PUT");
    assert.deepStrictEqual(puts, [], "it saved over the script open in the editor");
    assert.strictEqual(draftIn(store), null);
  });

  await test("a join that would not fit on the board is refused before anything is written", async () => {
    resetServer();
    const store = new Map();
    const page = boot(store);
    await settle();
    await page.context.renderEditor("s1");
    page.context.startRecording();
    page.type("KeyA");
    await settle();
    page.context.stopRecording();
    await settle();
    page.el("recording-save-target").checked = true;
    page.el("recording-save-target").dispatchEvent(
      new page.dom.FakeEvent("change", { bubbles: true })
    );
    page.el("recording-name").value = "Recording 1";
    // What the rows in the editor really cost -- unsaved ones included.
    server.preview = { ok: true, step_count: 499, duration_seconds: 10, limit: 500 };
    const before = page.el("steps-list").children.length;
    await page.context.saveRecordedScript();
    await settle();

    assert.match(page.text("recording-error"), /at 502 steps, and the Pico can hold 500/);
    assert.strictEqual(page.el("steps-list").children.length, before);
    assert.strictEqual(
      server.requests.filter((r) => r.url === "/api/scripts" && r.method === "POST").length,
      0,
      "it wrote the recording before finding out it would not fit"
    );
    assert.strictEqual(page.text("recording-keys"), "1");
    assert.strictEqual(draftIn(store).steps.length, 1);
  });

  const failed = results.filter(([ok]) => !ok).length;
  console.log("");
  console.log(`${results.length - failed} of ${results.length} passed`);
  process.exit(failed === 0 ? 0 : 1);
}

main();
