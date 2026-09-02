// keybot frontend -- plain JS, no build step.

const api = {
  async listScripts() {
    return (await fetch("/api/scripts")).json();
  },
  async getScript(id) {
    return (await fetch(`/api/scripts/${id}`)).json();
  },
  async createScript(data) {
    return fetchJson("/api/scripts", "POST", data);
  },
  async updateScript(id, data) {
    return fetchJson(`/api/scripts/${id}`, "PUT", data);
  },
  async deleteScript(id) {
    return fetchJson(`/api/scripts/${id}`, "DELETE");
  },
  async copyScript(id) {
    return fetchJson(`/api/scripts/${id}/copy`, "POST", {});
  },
  async previewScript(id) {
    return (await fetch(`/api/scripts/${id}/preview`)).json();
  },
  async runScript(id, times) {
    return fetchJson(`/api/scripts/${id}/run`, "POST", { times: times || null });
  },
  async deviceStatus() {
    return fetchJson("/api/device/status", "GET");
  },
  async deviceStop() {
    return fetchJson("/api/device/stop", "POST", {});
  },
  async deployStart() {
    return fetchJson("/api/device/deploy", "POST", {});
  },
  async deployStatus() {
    return fetchJson("/api/device/deploy/status", "GET");
  },
  async getSettings() {
    return (await fetch("/api/settings")).json();
  },
  async setSettings(data) {
    return fetchJson("/api/settings", "PUT", data);
  },
};

async function fetchJson(url, method, body) {
  const opts = { method, headers: {} };
  if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const resp = await fetch(url, opts);
  const text = await resp.text();
  let data;
  try {
    data = text ? JSON.parse(text) : {};
  } catch {
    data = { detail: text };
  }
  if (!resp.ok) {
    const err = new Error(data.detail || `request failed (${resp.status})`);
    err.status = resp.status;
    throw err;
  }
  return data;
}

const main = document.getElementById("main");
let allScripts = [];

// Sidebar collapsible sections
function initSidebarSections() {
  const titles = document.querySelectorAll(".sidebar-section-title");
  titles.forEach(title => {
    title.addEventListener("click", () => {
      const sectionName = title.dataset.section;
      const content = title.nextElementSibling;
      const isExpanded = title.classList.contains("expanded");

      if (isExpanded) {
        title.classList.remove("expanded");
        title.classList.add("collapsed");
        content.classList.add("hidden");
      } else {
        title.classList.remove("collapsed");
        title.classList.add("expanded");
        content.classList.remove("hidden");
      }
    });
  });
}

// -----
// Recording mode
// -----

let recordingState = {
  isRecording: false,
  startTime: null,
  lastKeyTime: null,
  keystrokeCount: 0,
  capturedScript: [],
  elapsedTimer: null,
};

const recordingToggleBtn = document.getElementById("recording-toggle-btn");
const recordingSaveBtn = document.getElementById("recording-save-btn");
const recordingCancelBtn = document.getElementById("recording-cancel-btn");
const recordingStatus = document.getElementById("recording-status");
const recordingStatusText = document.getElementById("recording-status-text");
const recordingKeysCount = document.getElementById("recording-keys");
const recordingElapsed = document.getElementById("recording-elapsed");
const recordingPreview = document.getElementById("recording-preview");
const recordingError = document.getElementById("recording-error");

recordingToggleBtn.addEventListener("click", async () => {
  if (recordingState.isRecording) {
    stopRecording();
  } else {
    startRecording();
  }
});

recordingSaveBtn.addEventListener("click", async () => {
  await saveRecordedScript();
});

recordingCancelBtn.addEventListener("click", () => {
  resetRecording();
});

function startRecording() {
  recordingState.isRecording = true;
  recordingState.startTime = Date.now();
  recordingState.lastKeyTime = recordingState.startTime;
  recordingState.keystrokeCount = 0;
  recordingState.capturedScript = [];
  recordingError.textContent = "";

  recordingToggleBtn.textContent = "Stop Recording";
  recordingToggleBtn.classList.add("danger");
  recordingToggleBtn.classList.remove("primary");
  recordingStatus.classList.add("recording");
  recordingStatus.classList.remove("idle");
  recordingStatusText.textContent = "Recording...";
  recordingPreview.style.display = "block";
  recordingPreview.textContent = "[]";
  recordingSaveBtn.style.display = "none";
  recordingCancelBtn.style.display = "none";

  // Start elapsed time counter
  recordingState.elapsedTimer = setInterval(() => {
    const elapsed = (Date.now() - recordingState.startTime) / 1000;
    recordingElapsed.textContent = elapsed < 60
      ? Math.round(elapsed) + "s"
      : Math.floor(elapsed / 60) + "m " + Math.round(elapsed % 60) + "s";
  }, 100);

  // Listen for keypresses (this is a simplified version)
  // In a real implementation, this would hook into the Pico communication
  // For now, we'll simulate keystroke capture from typing in the page
  document.addEventListener("keydown", recordKeystroke);
}

function stopRecording() {
  recordingState.isRecording = false;
  document.removeEventListener("keydown", recordKeystroke);
  clearInterval(recordingState.elapsedTimer);

  recordingToggleBtn.textContent = "Start Recording";
  recordingToggleBtn.classList.add("primary");
  recordingToggleBtn.classList.remove("danger");
  recordingStatus.classList.remove("recording");
  recordingStatus.classList.add("idle");
  recordingStatusText.textContent = "Stopped";
  recordingSaveBtn.style.display = "inline-block";
  recordingCancelBtn.style.display = "inline-block";
}

function recordKeystroke(event) {
  if (!recordingState.isRecording) return;

  // Ignore Cmd/Meta key and modifier-only keys
  if (event.metaKey || event.ctrlKey || event.altKey) {
    if (event.key === "Meta" || event.key === "Control" || event.key === "Alt" || event.key === "Shift") {
      return;
    }
  }

  // Skip certain keys (like Tab, which we use for navigation)
  const skipKeys = ["Tab", "Escape", "F5"];
  if (skipKeys.includes(event.key)) return;

  const now = Date.now();
  const timeSinceLastKey = (now - recordingState.lastKeyTime) / 1000;
  recordingState.lastKeyTime = now;

  // Round to 100ms granularity
  const roundedTime = Math.round(timeSinceLastKey * 10) / 10;

  // Add wait step if time gap > 0.1s
  if (recordingState.keystrokeCount > 0 && roundedTime > 0.1) {
    recordingState.capturedScript.push(["wait", Math.max(0.1, roundedTime)]);
  }

  // Map key to keycode
  let keyCode = event.key.toUpperCase();
  if (event.key === "Enter") keyCode = "ENTER";
  if (event.key === " ") keyCode = "SPACE";
  if (event.key === "Backspace") keyCode = "BACKSPACE";
  if (event.key === "Delete") keyCode = "DELETE";
  if (event.key === "ArrowUp") keyCode = "UP";
  if (event.key === "ArrowDown") keyCode = "DOWN";
  if (event.key === "ArrowLeft") keyCode = "LEFT";
  if (event.key === "ArrowRight") keyCode = "RIGHT";

  recordingState.capturedScript.push(["press", keyCode, 0.1]);
  recordingState.keystrokeCount++;

  recordingKeysCount.textContent = recordingState.keystrokeCount;
  updateRecordingPreview();
}

function updateRecordingPreview() {
  const preview = recordingState.capturedScript.slice(-10).map(step => {
    if (step[0] === "press") {
      return `["press", "${step[1]}", ${step[2]}]`;
    } else if (step[0] === "wait") {
      return `["wait", ${step[1]}]`;
    }
    return JSON.stringify(step);
  }).join("\n");
  recordingPreview.textContent = preview;
  recordingPreview.scrollTop = recordingPreview.scrollHeight;
}

async function saveRecordedScript() {
  if (recordingState.capturedScript.length === 0) {
    recordingError.textContent = "No keystrokes recorded.";
    return;
  }

  const name = `Recording ${new Date().toLocaleString()}`;
  try {
    const saved = await api.createScript({
      name,
      description: "Script recorded from keyboard input",
      steps: recordingState.capturedScript
    });
    recordingError.textContent = "";
    resetRecording();
    await renderList();
  } catch (e) {
    recordingError.textContent = "Couldn't save: " + e.message;
  }
}

function resetRecording() {
  recordingState = {
    isRecording: false,
    startTime: null,
    lastKeyTime: null,
    keystrokeCount: 0,
    capturedScript: [],
    elapsedTimer: null,
  };
  recordingToggleBtn.textContent = "Start Recording";
  recordingToggleBtn.classList.add("primary");
  recordingToggleBtn.classList.remove("danger");
  recordingStatus.classList.remove("recording");
  recordingStatus.classList.add("idle");
  recordingStatusText.textContent = "Ready";
  recordingKeysCount.textContent = "0";
  recordingElapsed.textContent = "0s";
  recordingPreview.style.display = "none";
  recordingPreview.textContent = "";
  recordingSaveBtn.style.display = "none";
  recordingCancelBtn.style.display = "none";
  recordingError.textContent = "";
}

// -----
// Script list
// -----

async function renderList() {
  allScripts = await api.listScripts();
  refreshRunSelect();

  main.innerHTML = "";

  const header = document.createElement("div");
  header.className = "list-header";
  header.innerHTML = `<h2 style="margin:0">Scripts</h2>`;
  const newBtn = document.createElement("button");
  newBtn.className = "btn primary";
  newBtn.textContent = "+ New script";
  newBtn.onclick = () => renderEditor(null);
  header.appendChild(newBtn);
  main.appendChild(header);

  if (allScripts.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No scripts yet. Create one to get started.";
    main.appendChild(empty);
    return;
  }

  for (const s of allScripts) {
    const card = document.createElement("div");
    card.className = "script-card";
    card.innerHTML = `
      <div class="script-card-info">
        <h3>${escapeHtml(s.name)}</h3>
        <p>${escapeHtml(s.description || "")} &middot; ${s.step_count} step${s.step_count === 1 ? "" : "s"}</p>
      </div>
      <div class="script-card-actions">
        <button class="btn small" data-act="edit">Edit</button>
        <button class="btn small" data-act="copy">Copy</button>
        <button class="btn small danger" data-act="delete">Delete</button>
      </div>
    `;
    card.querySelector('[data-act="edit"]').onclick = () => renderEditor(s.id);
    card.querySelector('[data-act="copy"]').onclick = async () => {
      await api.copyScript(s.id);
      renderList();
    };
    card.querySelector('[data-act="delete"]').onclick = async () => {
      if (confirm(`Delete "${s.name}"? This can't be undone.`)) {
        await api.deleteScript(s.id);
        renderList();
      }
    };
    main.appendChild(card);
  }
}

// -----
// Script editor
// -----

async function renderEditor(scriptId) {
  const isNew = scriptId === null;
  const script = isNew
    ? { id: null, name: "", description: "", steps: [] }
    : await api.getScript(scriptId);

  main.innerHTML = "";
  const editor = document.createElement("div");
  editor.className = "editor";
  editor.innerHTML = `
    <h2>${isNew ? "New script" : "Edit script"}</h2>
    <label class="field-label">Name</label>
    <input type="text" id="f-name" value="${escapeAttr(script.name)}">
    <label class="field-label">Description (optional)</label>
    <textarea id="f-desc">${escapeHtml(script.description || "")}</textarea>
    <label class="field-label">Steps</label>
    <div class="steps-list" id="steps-list"></div>
    <button class="btn small" id="add-step">+ Add step</button>
    <div class="button-row">
      <button class="btn primary" id="save-btn">Save</button>
      <button class="btn" id="cancel-btn">Cancel</button>
    </div>
    <div id="preview-box"></div>
  `;
  main.appendChild(editor);

  const stepsList = editor.querySelector("#steps-list");
  for (const step of script.steps) {
    stepsList.appendChild(buildStepRow(step, script.id));
  }

  editor.querySelector("#add-step").onclick = () => {
    stepsList.appendChild(buildStepRow(["press", "", 0.1], script.id));
  };
  editor.querySelector("#cancel-btn").onclick = () => renderList();
  editor.querySelector("#save-btn").onclick = async () => {
    const name = editor.querySelector("#f-name").value.trim();
    if (!name) {
      alert("Give the script a name.");
      return;
    }
    const steps = readSteps(stepsList);
    const data = { name, description: editor.querySelector("#f-desc").value, steps };
    try {
      let saved;
      if (isNew) {
        saved = await api.createScript(data);
      } else {
        saved = await api.updateScript(script.id, data);
      }
      await showPreview(saved.id, editor.querySelector("#preview-box"));
      allScripts = await api.listScripts();
      refreshRunSelect();
      renderEditor(saved.id);
    } catch (e) {
      alert("Couldn't save: " + e.message);
    }
  };

  if (!isNew) {
    await showPreview(script.id, editor.querySelector("#preview-box"));
  }
}

async function showPreview(scriptId, box) {
  try {
    const p = await api.previewScript(scriptId);
    if (p.ok) {
      box.className = "preview-box";
      box.textContent = `Expands to ${p.step_count} step${p.step_count === 1 ? "" : "s"}, about ${formatDuration(p.duration_seconds)} per run.`;
    } else {
      box.className = "preview-box error";
      box.textContent = "Can't run this yet: " + p.error;
    }
  } catch (e) {
    box.className = "preview-box error";
    box.textContent = "Couldn't check this script: " + e.message;
  }
}

function buildStepRow(step, ownScriptId) {
  const kind = step[0];
  const tpl = document.getElementById(`tpl-step-${kind}`) || document.getElementById("tpl-step-press");
  const node = tpl.content.cloneNode(true).querySelector(".step");

  if (kind === "press") {
    node.querySelector(".step-key").value = step[1] || "";
    node.querySelector(".step-hold").value = step[2] ?? 0.1;
  } else if (kind === "wait") {
    node.querySelector(".step-seconds").value = step[1] ?? 1;
  } else if (kind === "run") {
    const sel = node.querySelector(".step-ref");
    populateScriptSelect(sel, ownScriptId);
    sel.value = step[1] || "";
    node.querySelector(".step-times").value = step[2] ?? 1;
  }

  node.querySelector(".step-kind").onchange = (e) => {
    const newKind = e.target.value;
    const defaults = { press: ["press", "", 0.1], wait: ["wait", 1], run: ["run", "", 1] };
    const replacement = buildStepRow(defaults[newKind], ownScriptId);
    node.replaceWith(replacement);
  };
  node.querySelector(".step-remove").onclick = () => node.remove();
  node.querySelector(".step-up").onclick = () => {
    const prev = node.previousElementSibling;
    if (prev) node.parentNode.insertBefore(node, prev);
  };
  node.querySelector(".step-down").onclick = () => {
    const next = node.nextElementSibling;
    if (next) node.parentNode.insertBefore(next, node);
  };

  return node;
}

function populateScriptSelect(select, excludeId) {
  select.innerHTML = "";
  for (const s of allScripts) {
    if (s.id === excludeId) continue;
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.name;
    select.appendChild(opt);
  }
}

function readSteps(stepsList) {
  const steps = [];
  for (const node of stepsList.children) {
    const kind = node.dataset.kind;
    if (kind === "press") {
      const key = node.querySelector(".step-key").value.trim();
      const hold = parseFloat(node.querySelector(".step-hold").value) || 0;
      if (key) steps.push(["press", key, hold]);
    } else if (kind === "wait") {
      const seconds = parseFloat(node.querySelector(".step-seconds").value) || 0;
      steps.push(["wait", seconds]);
    } else if (kind === "run") {
      const ref = node.querySelector(".step-ref").value;
      const times = parseInt(node.querySelector(".step-times").value, 10) || 1;
      if (ref) steps.push(["run", ref, times]);
    }
  }
  return steps;
}

// -----
// Sidebar: run controls + status polling + settings
// -----

function refreshRunSelect() {
  const sel = document.getElementById("run-script-select");
  const current = sel.value;
  sel.innerHTML = "";
  for (const s of allScripts) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = s.name;
    sel.appendChild(opt);
  }
  if (current) sel.value = current;
}

document.getElementById("run-start-btn").onclick = async () => {
  const errBox = document.getElementById("run-error");
  errBox.textContent = "";
  const scriptId = document.getElementById("run-script-select").value;
  const timesVal = document.getElementById("run-times").value;
  const times = timesVal ? parseInt(timesVal, 10) : null;
  if (!scriptId) {
    errBox.textContent = "Pick a script first.";
    return;
  }
  try {
    await api.runScript(scriptId, times);
    pollStatus();
  } catch (e) {
    errBox.textContent = e.message;
  }
};

document.getElementById("run-stop-btn").onclick = async () => {
  const errBox = document.getElementById("run-error");
  errBox.textContent = "";
  try {
    await api.deviceStop();
    pollStatus();
  } catch (e) {
    errBox.textContent = e.message;
  }
};

async function pollStatus() {
  try {
    const s = await api.deviceStatus();
    document.getElementById("st-running").textContent = s.running ? "yes" : "no";
    const target = s.target_loops === null || s.target_loops === undefined ? "∞" : s.target_loops;
    document.getElementById("st-loop").textContent = `${s.loop_count} / ${target}`;
    document.getElementById("st-step").textContent = `${s.current_step + 1} / ${s.total_steps}`;
    document.getElementById("st-eta").textContent =
      s.estimated_seconds_remaining === null || s.estimated_seconds_remaining === undefined
        ? "-"
        : formatDuration(s.estimated_seconds_remaining);
  } catch (e) {
    document.getElementById("st-running").textContent = "unreachable";
    document.getElementById("st-loop").textContent = "-";
    document.getElementById("st-step").textContent = "-";
    document.getElementById("st-eta").textContent = "-";
  }
}

setInterval(pollStatus, 1500);

document.getElementById("device-url-save").onclick = async () => {
  const url = document.getElementById("device-url").value.trim();
  if (!url) return;
  await api.setSettings({ device_url: url });
  pollStatus();
};

async function loadSettings() {
  const s = await api.getSettings();
  document.getElementById("device-url").value = s.device_url;
}

// -----
// Firmware deploy
// -----

const deployBtn = document.getElementById("deploy-btn");
const deployStatusBox = document.getElementById("deploy-status");
let deployPollTimer = null;

deployBtn.onclick = async () => {
  deployBtn.disabled = true;
  deployStatusBox.className = "hint";
  deployStatusBox.textContent = "Starting deploy...";
  try {
    await api.deployStart();
  } catch (e) {
    deployBtn.disabled = false;
    deployStatusBox.className = "hint error";
    deployStatusBox.textContent = e.message;
    return;
  }
  if (deployPollTimer) clearInterval(deployPollTimer);
  deployPollTimer = setInterval(pollDeployStatus, 1200);
  pollDeployStatus();
};

async function pollDeployStatus() {
  let s;
  try {
    s = await api.deployStatus();
  } catch (e) {
    return; // transient; the next tick will try again
  }
  deployStatusBox.textContent = s.message || "";
  deployStatusBox.className = s.phase === "error" ? "hint error" : "hint";
  if (s.phase === "done" || s.phase === "error" || s.phase === "idle") {
    clearInterval(deployPollTimer);
    deployPollTimer = null;
    deployBtn.disabled = false;
  }
}

// -----
// Helpers
// -----

function formatDuration(totalSeconds) {
  const s = Math.round(totalSeconds);
  const m = Math.floor(s / 60);
  const rem = s % 60;
  if (m === 0) return `${rem}s`;
  return `${m}m ${rem}s`;
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

function escapeAttr(str) {
  return escapeHtml(str).replace(/"/g, "&quot;");
}

// -----
// Boot
// -----

(async function init() {
  initSidebarSections();
  await renderList();
  await loadSettings();
  pollStatus();
})();
