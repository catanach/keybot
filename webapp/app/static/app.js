// keybot frontend -- plain JS, no build step.

// Utility: debounce function for performance
function debounce(func, wait) {
  let timeout;
  return function executedFunction(...args) {
    const later = () => {
      clearTimeout(timeout);
      func(...args);
    };
    clearTimeout(timeout);
    timeout = setTimeout(later, wait);
  };
}

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
let lastRunScriptId = localStorage.getItem("lastRunScriptId") || null;
let isEditingScript = false;
let favorites = new Set(JSON.parse(localStorage.getItem("favorites") || "[]"));
let recentScriptIds = JSON.parse(localStorage.getItem("recentScriptIds") || "[]"); // Track up to 5 recent scripts

// Keyboard shortcuts setup
document.addEventListener("keydown", (e) => {
  // There is deliberately no Cmd/Ctrl + R shortcut. That combination is
  // muscle memory for refreshing the page, and binding it here swallowed
  // the refresh and started a recording instead.
  // Cmd/Ctrl + Enter: run selected script
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    const btn = document.getElementById("run-start-btn");
    btn.click();
  }
  // Cmd/Ctrl + S: save script or save recording
  if ((e.metaKey || e.ctrlKey) && e.key === "s") {
    e.preventDefault();
    const recordingBtn = document.getElementById("recording-save-btn");
    const scriptBtn = document.getElementById("save-btn");
    if (recordingBtn && recordingBtn.style.display !== "none") {
      recordingBtn.click();
    } else if (scriptBtn && !isEditingScript) {
      scriptBtn.click();
    }
  }
});

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

  // Never capture anything while Cmd, Ctrl or Alt is held. Those are
  // browser and OS shortcuts, not keystrokes anyone means to record.
  // The old check only skipped the modifier key itself, so reaching for
  // Cmd+R or Cmd+L dropped a stray letter into the script.
  if (event.metaKey || event.ctrlKey || event.altKey) return;

  // A modifier pressed on its own is never a recordable keystroke.
  if (["Meta", "Control", "Alt", "Shift", "CapsLock"].includes(event.key)) return;

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
    // Optimistic UI: disable button and show saving state
    recordingSaveBtn.disabled = true;
    recordingSaveBtn.textContent = "Saving...";
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
    recordingSaveBtn.disabled = false;
    recordingSaveBtn.textContent = "Save";
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

let scriptFilter = "all";
let scriptSearch = "";

function saveFavorites() {
  localStorage.setItem("favorites", JSON.stringify([...favorites]));
}

function toggleFavorite(scriptId) {
  if (favorites.has(scriptId)) {
    favorites.delete(scriptId);
  } else {
    favorites.add(scriptId);
  }
  saveFavorites();
  filterAndDisplayScripts();
}

function filterAndDisplayScripts() {
  const filtered = allScripts.filter(s => {
    const matchesSearch = s.name.toLowerCase().includes(scriptSearch.toLowerCase()) ||
                          (s.description || "").toLowerCase().includes(scriptSearch.toLowerCase());
    return matchesSearch;
  });

  // Sort: favorites first
  filtered.sort((a, b) => {
    const aFav = favorites.has(a.id) ? 0 : 1;
    const bFav = favorites.has(b.id) ? 0 : 1;
    return aFav - bFav;
  });

  // Clear and rebuild list
  const listContainer = document.getElementById("scripts-list");
  if (!listContainer) return;
  listContainer.innerHTML = "";

  if (filtered.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = scriptSearch ? "No scripts match your search." : "No scripts yet. Create one to get started.";
    listContainer.appendChild(empty);
    return;
  }

  for (const s of filtered) {
    const card = document.createElement("div");
    card.className = "script-card";
    card.innerHTML = `
      <button class="script-card-star ${favorites.has(s.id) ? "favorited" : ""}" data-id="${s.id}" title="Add to favorites">
        ${favorites.has(s.id) ? "⭐" : "☆"}
      </button>
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

    card.querySelector(".script-card-star").onclick = (e) => {
      e.preventDefault();
      toggleFavorite(s.id);
    };

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
    listContainer.appendChild(card);
  }

  // Update count
  const countEl = document.getElementById("scripts-count");
  if (countEl) {
    countEl.textContent = scriptSearch ? `${filtered.length} result${filtered.length !== 1 ? "s" : ""}` : `${filtered.length} script${filtered.length !== 1 ? "s" : ""}`;
  }
}

async function renderList() {
  isEditingScript = false;
  allScripts = await api.listScripts();
  refreshRunSelect();
  refreshRecentScripts();

  main.innerHTML = "";

  const header = document.createElement("div");
  header.className = "list-header";

  const headerTop = document.createElement("div");
  headerTop.className = "list-header-top";

  const title = document.createElement("h2");
  title.style.margin = "0";
  title.textContent = "Scripts";

  const newBtn = document.createElement("button");
  newBtn.className = "btn primary";
  newBtn.textContent = "+ New script";
  newBtn.onclick = () => renderEditor(null);

  headerTop.appendChild(title);
  headerTop.appendChild(newBtn);
  header.appendChild(headerTop);

  // Add search and filter row
  const searchContainer = document.createElement("div");
  searchContainer.style.display = "flex";
  searchContainer.style.gap = "12px";
  searchContainer.style.alignItems = "center";

  const searchBox = document.createElement("div");
  searchBox.className = "script-search";
  searchBox.innerHTML = `<span class="script-search-icon">🔍</span><input type="text" id="scripts-search" placeholder="Search scripts...">`;

  const countLabel = document.createElement("span");
  countLabel.id = "scripts-count";
  countLabel.className = "script-count";
  countLabel.textContent = `${allScripts.length} script${allScripts.length !== 1 ? "s" : ""}`;

  searchContainer.appendChild(searchBox);
  searchContainer.appendChild(countLabel);
  header.appendChild(searchContainer);

  main.appendChild(header);

  // Setup search input with debounce
  const debouncedSearch = debounce((value) => {
    scriptSearch = value;
    filterAndDisplayScripts();
  }, 150);

  document.getElementById("scripts-search").oninput = (e) => {
    debouncedSearch(e.target.value);
  };

  if (allScripts.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No scripts yet. Create one to get started.";
    main.appendChild(empty);
    return;
  }

  // Create list container
  const listContainer = document.createElement("div");
  listContainer.id = "scripts-list";
  main.appendChild(listContainer);

  // Initial display
  filterAndDisplayScripts();
}

// -----
// Script editor
// -----

async function renderEditor(scriptId) {
  isEditingScript = true;
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
  editor.querySelector("#cancel-btn").onclick = () => {
    isEditingScript = false;
    renderList();
  };
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
      refreshRecentScripts();
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

// Status polling state and local countdown timer
let statusPollState = {
  pollTimer: null,
  isRunning: false,
};

// Local countdown timer state (client-side, deterministic timing)
let countdownState = {
  totalDurationMs: null,
  startTime: null,
  updateAnimationFrameId: null,
  timerEl: null,
};

const POLL_INTERVAL = 5000; // Poll device every 5 seconds (verification only, not for timing)

function refreshRunSelect() {
  const sel = document.getElementById("run-script-select");
  const current = sel.value || lastRunScriptId;
  sel.innerHTML = "";
  for (const s of allScripts) {
    const opt = document.createElement("option");
    opt.value = s.id;
    opt.textContent = (s.id === lastRunScriptId ? "↻ " : "") + s.name;
    sel.appendChild(opt);
  }
  if (current) sel.value = current;
}

function addToRecentScripts(scriptId) {
  // Remove if already in list, then add to front
  recentScriptIds = recentScriptIds.filter(id => id !== scriptId);
  recentScriptIds.unshift(scriptId);
  // Keep only last 5
  recentScriptIds = recentScriptIds.slice(0, 5);
  localStorage.setItem("recentScriptIds", JSON.stringify(recentScriptIds));
  refreshRecentScripts();
}

function refreshRecentScripts() {
  const container = document.getElementById("recent-scripts-container");
  const list = document.getElementById("recent-scripts-list");
  if (!container || !list) return;

  // Filter to only scripts that still exist
  const existingRecentIds = recentScriptIds.filter(id =>
    allScripts.some(s => s.id === id)
  );

  if (existingRecentIds.length === 0) {
    container.style.display = "none";
    return;
  }

  container.style.display = "block";
  list.innerHTML = "";

  for (const id of existingRecentIds) {
    const script = allScripts.find(s => s.id === id);
    if (!script) continue;

    const btn = document.createElement("button");
    btn.className = "recent-script-btn";
    btn.textContent = script.name;
    btn.onclick = () => {
      document.getElementById("run-script-select").value = id;
    };
    list.appendChild(btn);
  }
}

document.getElementById("run-start-btn").onclick = async () => {
  const errBox = document.getElementById("run-error");
  const btn = document.getElementById("run-start-btn");
  const stopBtn = document.getElementById("run-stop-btn");
  errBox.textContent = "";
  const scriptId = document.getElementById("run-script-select").value;
  const timesVal = document.getElementById("run-times").value;
  const times = timesVal ? parseInt(timesVal, 10) : null;
  if (!scriptId) {
    errBox.textContent = "Pick a script first.";
    return;
  }
  try {
    // Optimistic UI: disable button and show loading state
    btn.disabled = true;
    btn.textContent = "Starting...";

    // Fetch preview to get duration_seconds BEFORE starting
    const preview = await api.previewScript(scriptId);
    if (!preview.ok) {
      throw new Error("Cannot run: " + preview.error);
    }

    // Calculate total duration client-side
    const durationSeconds = preview.duration_seconds;
    const loopCount = times || 1;
    const totalDurationMs = durationSeconds * loopCount * 1000;

    // Start the script
    await api.runScript(scriptId, times);
    lastRunScriptId = scriptId;
    localStorage.setItem("lastRunScriptId", scriptId);
    addToRecentScripts(scriptId);

    // Start the local countdown timer with the calculated duration
    startLocalCountdown(totalDurationMs);

    // Initial status poll and periodic polling (5 seconds, for verification only)
    await pollStatus();
    if (statusPollState.pollTimer) clearInterval(statusPollState.pollTimer);
    statusPollState.pollTimer = setInterval(pollStatus, POLL_INTERVAL);
  } catch (e) {
    errBox.textContent = e.message;
    btn.disabled = false;
    btn.textContent = "Start";
  }
};

document.getElementById("run-stop-btn").onclick = async () => {
  const errBox = document.getElementById("run-error");
  errBox.textContent = "";
  try {
    // Stop the local countdown immediately
    stopLocalCountdown();
    // Stop device polling
    if (statusPollState.pollTimer) {
      clearInterval(statusPollState.pollTimer);
      statusPollState.pollTimer = null;
    }
    // Send stop request to device
    await api.deviceStop();
    // Verify device stopped
    await pollStatus();
  } catch (e) {
    errBox.textContent = e.message;
  }
};

function updateDeviceIndicator(status) {
  const dot = document.querySelector(".device-indicator-dot");
  const label = document.getElementById("device-indicator-label");
  if (!dot || !label) return;

  dot.className = "device-indicator-dot";
  if (status === "connected") {
    dot.classList.add("connected");
    label.textContent = "Connected";
  } else if (status === "unreachable") {
    dot.classList.add("unreachable");
    label.textContent = "Unreachable";
  } else {
    dot.classList.add("connecting");
    label.textContent = "Connecting";
  }
}

async function pollStatus() {
  try {
    const s = await api.deviceStatus();
    const wasRunning = statusPollState.isRunning;

    const runningEl = document.getElementById("st-running");
    runningEl.textContent = s.running ? "yes" : "no";
    runningEl.classList.toggle("status-running", s.running);
    runningEl.classList.toggle("status-idle", !s.running);
    const target = s.target_loops === null || s.target_loops === undefined ? "∞" : s.target_loops;
    document.getElementById("st-loop").textContent = `${s.loop_count} / ${target}`;
    document.getElementById("st-step").textContent = `${s.current_step + 1} / ${s.total_steps}`;

    // Update device indicator
    updateDeviceIndicator("connected");

    // Manage countdown state
    if (s.running && !wasRunning) {
      statusPollState.isRunning = true;
    } else if (!s.running && wasRunning) {
      stopLocalCountdown();
      statusPollState.isRunning = false;
    }
  } catch (e) {
    // Device unreachable
    stopLocalCountdown();
    statusPollState.isRunning = false;

    const runningEl = document.getElementById("st-running");
    runningEl.textContent = "unreachable";
    runningEl.classList.remove("status-running", "status-idle");
    document.getElementById("st-loop").textContent = "-";
    document.getElementById("st-step").textContent = "-";

    // Update device indicator
    updateDeviceIndicator("unreachable");
  }
}

function updateLocalCountdownDisplay() {
  const etaEl = document.getElementById("st-eta");
  if (countdownState.totalDurationMs === null || countdownState.startTime === null) {
    etaEl.textContent = "-";
    return;
  }

  const now = Date.now();
  const elapsedMs = now - countdownState.startTime;
  const remainingMs = Math.max(0, countdownState.totalDurationMs - elapsedMs);
  const remainingSeconds = remainingMs / 1000;

  const displayValue = formatDuration(remainingSeconds);
  etaEl.textContent = displayValue;

  // Stop if countdown is done
  if (remainingMs === 0) {
    stopLocalCountdown();
  }
}

function startLocalCountdown(totalDurationMs) {
  // Cancel any existing countdown
  if (countdownState.updateAnimationFrameId !== null) {
    cancelAnimationFrame(countdownState.updateAnimationFrameId);
  }

  countdownState.totalDurationMs = totalDurationMs;
  countdownState.startTime = Date.now();

  function animationLoop() {
    updateLocalCountdownDisplay();
    if (countdownState.totalDurationMs !== null) {
      countdownState.updateAnimationFrameId = requestAnimationFrame(animationLoop);
    }
  }

  animationLoop();
}

function stopLocalCountdown() {
  if (countdownState.updateAnimationFrameId !== null) {
    cancelAnimationFrame(countdownState.updateAnimationFrameId);
    countdownState.updateAnimationFrameId = null;
  }
  countdownState.totalDurationMs = null;
  countdownState.startTime = null;
  document.getElementById("st-eta").textContent = "-";
}

// Initialize device indicator and perform initial status poll
updateDeviceIndicator("connecting");
pollStatus();

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

  // Initial status poll and setup animation loop
  await pollStatus();

  // Add keyboard shortcut hints
  const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform);
  const cmdKey = isMac ? "⌘" : "Ctrl";
  document.getElementById("recording-toggle-btn").title = `${cmdKey}+R: Toggle recording`;
  document.getElementById("run-start-btn").title = `${cmdKey}+Enter: Run script`;

  // Display keyboard hints in sidebar if desired
  const sidebar = document.getElementById("sidebar");
  const shortcutsHint = document.createElement("div");
  shortcutsHint.style.cssText = "font-size: 11px; color: var(--muted); padding: 10px; border-top: 1px solid var(--border); margin-top: auto; text-align: center;";
  shortcutsHint.textContent = `Shortcuts: ${cmdKey}+R record • ${cmdKey}+⏎ run • ${cmdKey}+S save`;
  sidebar.appendChild(shortcutsHint);
})();
