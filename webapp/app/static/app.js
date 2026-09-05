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
  async devicePress(key, hold) {
    return fetchJson("/api/device/press", "POST", { key, hold });
  },
  async devicePressSupported() {
    return fetchJson("/api/device/press/supported", "GET");
  },
  async deployStart() {
    return fetchJson("/api/device/deploy", "POST", {});
  },
  async deployStatus() {
    return fetchJson("/api/device/deploy/status", "GET");
  },
  async getHistory() {
    return (await fetch("/api/history")).json();
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

// -----
// Looking elements up
//
// This file wires its controls when it loads. A page whose HTML is older
// than this file -- a browser holding a cached index.html, which has
// happened -- can be missing one of them, and a missing element used to
// stop the whole file dead on the line that touched it: no status polling,
// no script list, a page that drew itself and then did nothing.
//
// So every control is looked up through one of these two. A control that
// isn't on the page costs that one control and says so on the console.
// Nothing else here catches errors: a real bug should still throw.
// -----

function elementOrWarn(id) {
  const el = document.getElementById(id);
  if (!el) {
    console.warn(
      `keybot: this page has no element with id "${id}", so that control does ` +
      `nothing. The page may be older than the app -- reload it, and if that ` +
      `doesn't help the page and the app have got out of step.`
    );
    return null;
  }
  return el;
}

function bindEvent(id, type, handler) {
  const el = elementOrWarn(id);
  if (!el) return null;
  el.addEventListener(type, handler);
  return el;
}

const main = document.getElementById("main");
let allScripts = [];
let lastRunScriptId = localStorage.getItem("lastRunScriptId") || null;
let isEditingScript = false;
let favorites = new Set(JSON.parse(localStorage.getItem("favorites") || "[]"));
let recentScriptIds = JSON.parse(localStorage.getItem("recentScriptIds") || "[]"); // Track up to 5 recent scripts

// The key names the device understands, fetched once from /api/keycodes,
// which reads the same src/keycodes.py the Pico runs. Nothing here keeps
// its own copy of the names -- copies are how they drifted apart before.
let keyGroups = [];
let keysByName = new Map();

// Keyboard shortcuts setup
document.addEventListener("keydown", (e) => {
  // There is deliberately no Cmd/Ctrl + R shortcut. That combination is
  // muscle memory for refreshing the page, and binding it here swallowed
  // the refresh and started a recording instead.
  // Cmd/Ctrl + Enter: run selected script
  if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
    e.preventDefault();
    const btn = document.getElementById("run-start-btn");
    if (btn) btn.click();
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
const recordingBanner = document.getElementById("recording-banner");
const recordingLiveRow = document.getElementById("recording-live-row");
const recordingLiveToggle = document.getElementById("recording-live");
const recordingLiveProblem = document.getElementById("recording-live-problem");

// -----
// Sending keys to the Pico as they are typed
//
// Recording used to be a browser-only affair: keys went into an array and
// nothing reached the device until Save. Each key now also goes to the
// board, one request at a time, in the order it was typed. The queue is
// here rather than on the board because the board has the least memory and
// the least room in code.py, and because a queue there would keep pressing
// keys after the browser had moved on.
// -----

// One request in flight at a time, so keys arrive in the order they were
// typed. Nothing is ever merged or quietly thrown away.
const liveSend = {
  queue: [],
  sending: false,
  // Set when the typing has run so far ahead of the Pico that sending is
  // pointless. Recording carries on; only the sending stops.
  gaveUp: false,
};

// How far behind sending may fall before it stops. Wi-Fi keeps every
// request honest, so a long backlog means keys landing on the PS5 well
// after they were typed -- worse than not sending them at all.
const LIVE_BACKLOG_LIMIT = 10;

// The hold each live key gets, matching the 0.1 recorded for the step, so
// what the PS5 feels now is what it will feel on replay.
const LIVE_HOLD = 0.1;

const LIVE_UNREACHABLE_NOTE =
  "Not reaching the Pico -- still recording your keys, but they aren't being " +
  "sent. Check it's powered on.";
const LIVE_BACKLOG_NOTE =
  "The Pico is too far behind to keep up, so keys have stopped being sent for " +
  "this recording. Your keys are still being saved to the script.";

// Whether the firmware on the board has /press at all. Asked once, when the
// page loads: offering a switch that 404s on every keystroke is worse than
// not offering one. A board that can't be reached is not a board without
// the route, so that leaves the switch alone.
let livePressSupported = true;

async function loadLivePressSupport() {
  try {
    const data = await api.devicePressSupported();
    livePressSupported = data.supported !== false;
  } catch {
    livePressSupported = true;
  }
  // No switch on the page means no live sending, so the row that would
  // hold it has nothing to show either.
  if (recordingLiveRow) {
    recordingLiveRow.hidden = !livePressSupported || !recordingLiveToggle;
  }
}

function liveSendWanted() {
  // Without the switch there is no way to ask for live sending and no way
  // to turn it off again, so it stays off.
  if (!recordingLiveToggle) return false;
  return livePressSupported && recordingLiveToggle.checked === true;
}

function setLiveProblem(text) {
  if (!recordingLiveProblem) return;
  recordingLiveProblem.textContent = text;
  recordingLiveProblem.style.display = text ? "block" : "none";
}

function updateRecordingBanner() {
  if (!recordingState.isRecording) {
    recordingBanner.style.display = "none";
    return;
  }
  recordingBanner.style.display = "block";
  recordingBanner.textContent = liveSendWanted()
    ? "Recording. Every key you press is sent to the PS5 and saved to the " +
      "script. Typing anywhere on this page is captured."
    : "Recording. Every key you press is saved to the script but not sent to " +
      "the PS5. Typing anywhere on this page is captured.";
}

function queueLiveKey(key) {
  if (liveSend.gaveUp) return;
  if (liveSend.queue.length >= LIVE_BACKLOG_LIMIT) {
    liveSend.gaveUp = true;
    liveSend.queue = [];
    setLiveProblem(LIVE_BACKLOG_NOTE);
    return;
  }
  liveSend.queue.push(key);
  sendQueuedKeys();
}

async function sendQueuedKeys() {
  // One at a time: a second caller here would let a later key overtake an
  // earlier one, and the board answers one request at a time anyway.
  if (liveSend.sending) return;
  liveSend.sending = true;
  try {
    while (liveSend.queue.length > 0 && !liveSend.gaveUp) {
      const key = liveSend.queue.shift();
      try {
        await api.devicePress(key, LIVE_HOLD);
        // Whatever was wrong is over. A key that failed on the way stays in
        // the script exactly as it was typed.
        setLiveProblem("");
      } catch (e) {
        // 409 is the board saying it is busy, in its own words. Anything
        // else, at this point, means it isn't answering.
        setLiveProblem(e.status === 409 ? e.message : LIVE_UNREACHABLE_NOTE);
      }
    }
  } finally {
    liveSend.sending = false;
  }
}

function resetLiveSend() {
  liveSend.queue = [];
  liveSend.gaveUp = false;
  setLiveProblem("");
}

bindEvent("recording-toggle-btn", "click", async () => {
  if (recordingState.isRecording) {
    stopRecording();
  } else {
    startRecording();
  }
});

bindEvent("recording-save-btn", "click", async () => {
  await saveRecordedScript();
});

bindEvent("recording-cancel-btn", "click", () => {
  resetRecording();
});

bindEvent("recording-live", "change", () => {
  // Turning it off mid-recording stops the keys already waiting, not just
  // the ones still to come.
  if (!liveSendWanted()) liveSend.queue = [];
  updateRecordingBanner();
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
  resetLiveSend();
  updateRecordingBanner();

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
  updateRecordingBanner();
}

// Browser key events do not use the same names as the keyboard library on
// the Pico. The recorder used to send "UP" and "1", which the device has no
// key for, so any recording containing an arrow or a digit failed at run
// time. These map a physical key to the name the firmware expects. Reading
// event.code rather than event.key means the physical key is captured
// regardless of Shift or keyboard layout.
const RECORDER_CODE_MAP = {
  Enter: "ENTER", NumpadEnter: "KEYPAD_ENTER", Space: "SPACE", Tab: "TAB",
  Backspace: "BACKSPACE", Delete: "DELETE", Escape: "ESCAPE",
  ArrowUp: "UP_ARROW", ArrowDown: "DOWN_ARROW",
  ArrowLeft: "LEFT_ARROW", ArrowRight: "RIGHT_ARROW",
  Home: "HOME", End: "END", PageUp: "PAGE_UP", PageDown: "PAGE_DOWN",
  Insert: "INSERT", CapsLock: "CAPS_LOCK",
  Minus: "MINUS", Equal: "EQUALS",
  BracketLeft: "LEFT_BRACKET", BracketRight: "RIGHT_BRACKET",
  Backslash: "BACKSLASH", Semicolon: "SEMICOLON", Quote: "QUOTE",
  Backquote: "GRAVE_ACCENT", Comma: "COMMA", Period: "PERIOD",
  Slash: "FORWARD_SLASH",
};
const DIGIT_NAMES = ["ZERO", "ONE", "TWO", "THREE", "FOUR", "FIVE", "SIX",
                     "SEVEN", "EIGHT", "NINE"];

function toKeycodeName(event) {
  const code = event.code || "";
  if (Object.prototype.hasOwnProperty.call(RECORDER_CODE_MAP, code)) {
    return RECORDER_CODE_MAP[code];
  }
  let m = /^Key([A-Z])$/.exec(code);
  if (m) return m[1];
  m = /^Digit([0-9])$/.exec(code);
  if (m) return DIGIT_NAMES[Number(m[1])];
  m = /^Numpad([0-9])$/.exec(code);
  if (m) return "KEYPAD_" + DIGIT_NAMES[Number(m[1])];
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(code)) return code;
  // Some layouts and remappers leave event.code empty.
  const key = event.key || "";
  if (/^[a-zA-Z]$/.test(key)) return key.toUpperCase();
  return null;
}

// Everything toKeycodeName can return. If any of it is not a key the
// device has, a recording using that key fails on the hardware -- which is
// the bug that started all of this, so it is checked on every page load
// rather than left to be noticed on the PS5.
function recorderKeycodeNames() {
  const names = new Set(Object.values(RECORDER_CODE_MAP));
  for (const letter of "ABCDEFGHIJKLMNOPQRSTUVWXYZ") names.add(letter);
  for (const digit of DIGIT_NAMES) {
    names.add(digit);
    names.add("KEYPAD_" + digit);
  }
  for (let i = 1; i <= 24; i++) names.add("F" + i);
  return names;
}

// Returns whether the list arrived. It can fail for an ordinary reason --
// the webapp restarts on every deploy, and a page open at that moment gets
// a 502 -- so nothing here is allowed to leave the picker quietly dead.
async function loadKeycodes() {
  try {
    const response = await fetch("/api/keycodes");
    if (!response.ok) throw new Error(`the server answered ${response.status}`);
    const data = await response.json();
    keyGroups = data.groups || [];
  } catch (e) {
    keyGroups = [];
    console.error("keybot: couldn't load the key list from the server: " + e.message);
  }
  keysByName = new Map();
  for (const group of keyGroups) {
    for (const key of group.keys) keysByName.set(key.name, key);
  }
  if (keysByName.size === 0) return false;

  const unknown = [...recorderKeycodeNames()].filter(name => !keysByName.has(name));
  if (unknown.length > 0) {
    console.error(
      "keybot: the recorder can produce key names the device does not have: " +
      unknown.join(", ") +
      ". Recording one of those keys would fail on the Pico. Fix RECORDER_CODE_MAP " +
      "in app.js, or add the names to src/keycodes.py."
    );
  }
  return true;
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

  // F5 stays with the browser so refresh always works. Tab and Escape are
  // recorded: both are ordinary keys in the apps these scripts drive, and
  // the Cancel button is there to stop a recording.
  if (event.key === "F5") return;

  const keyCode = toKeycodeName(event);
  if (keyCode === null) {
    recordingError.textContent =
      'Skipped "' + event.key + '". The keyboard has no key with that name.';
    return;
  }
  event.preventDefault();

  const now = Date.now();
  const timeSinceLastKey = (now - recordingState.lastKeyTime) / 1000;
  recordingState.lastKeyTime = now;

  // Round to 100ms granularity
  const roundedTime = Math.round(timeSinceLastKey * 10) / 10;

  // Add wait step if time gap > 0.1s
  if (recordingState.keystrokeCount > 0 && roundedTime > 0.1) {
    recordingState.capturedScript.push(["wait", Math.max(0.1, roundedTime)]);
  }

  recordingState.capturedScript.push(["press", keyCode, LIVE_HOLD]);
  recordingState.keystrokeCount++;
  // The script has the key either way. Sending it is a separate thing that
  // is allowed to fail without changing what was recorded.
  if (liveSendWanted()) queueLiveKey(keyCode);

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
  resetLiveSend();
  updateRecordingBanner();
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

  // The list is fetched when the page opens, but the webapp restarts on
  // every firmware deploy and a page open at that moment gets nothing. Try
  // again on the way into the editor, which is the only screen that needs it.
  if (keysByName.size === 0) await loadKeycodes();
  if (keysByName.size === 0) showKeyListWarning(editor, stepsList);

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
    if (keysByName.size === 0) {
      alert("The list of keys hasn't loaded, so nothing can be saved yet. Use Try again above.");
      return;
    }
    const { steps, unresolved } = readSteps(stepsList);
    if (unresolved) {
      alert("One step still needs a key.");
      return;
    }
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

// Shown when the key list could not be fetched. Without it no key can be
// picked or checked, so it says so once, at the top, and offers the way out
// rather than making someone reload and lose what they were editing.
function showKeyListWarning(editor, stepsList) {
  const warning = document.createElement("div");
  warning.className = "preview-box error";
  warning.id = "key-list-warning";
  const message = document.createElement("span");
  message.textContent = "The list of keys didn't load, so keys can't be picked or checked. ";
  const retry = document.createElement("button");
  retry.type = "button";
  retry.className = "btn small";
  retry.id = "retry-keycodes";
  retry.textContent = "Try again";
  retry.onclick = async () => {
    retry.disabled = true;
    retry.textContent = "Trying...";
    const loaded = await loadKeycodes();
    retry.disabled = false;
    retry.textContent = "Try again";
    if (!loaded) {
      message.textContent = "Still no list of keys. Is the webapp still running? ";
      return;
    }
    warning.remove();
    // Every press row is showing its key as plain text. Now that the list is
    // here, build the pickers again from what each row already holds.
    for (const row of stepsList.children) {
      if (row.dataset.kind === "press") {
        setUpKeyPicker(row, row.querySelector(".step-key-search").value.trim());
      }
    }
  };
  warning.appendChild(message);
  warning.appendChild(retry);
  editor.insertBefore(warning, stepsList);
}

async function showPreview(scriptId, box) {
  try {
    const p = await api.previewScript(scriptId);
    if (p.ok) {
      box.className = "preview-box";
      box.textContent = `${p.step_count} step${p.step_count === 1 ? "" : "s"} sent to the Pico, about ${formatDuration(p.duration_seconds)} per run.`;
    } else {
      box.className = "preview-box error";
      box.textContent = "Can't run this yet: " + p.error;
    }
  } catch (e) {
    box.className = "preview-box error";
    box.textContent = "Couldn't check this script: " + e.message;
  }
}

// How a key reads in the picker: the everyday name first, then the name
// the device uses, e.g. "8 (EIGHT)". Letters read the same either way, so
// they are not shown twice.
function keyDisplay(key) {
  return key.label === key.name ? key.name : `${key.label} (${key.name})`;
}

// Turns a press row into a searchable key picker. What gets saved is always
// a name from the shared list: a row showing anything else counts as
// unresolved, and readSteps refuses to save it.
function setUpKeyPicker(node, initialName) {
  const hidden = node.querySelector(".step-key");
  const search = node.querySelector(".step-key-search");
  const options = node.querySelector(".step-key-options");
  const errorBox = node.querySelector(".step-key-error");
  const captureBtn = node.querySelector(".step-key-capture");
  let cancelCapture = null;

  function showError(text) {
    errorBox.textContent = text;
    node.classList.toggle("step-invalid", Boolean(text));
  }

  // Shows a key, or shows what was there before and says it is not a key.
  // A name saved by an older version is flagged, never quietly replaced.
  function setKey(name) {
    const key = keysByName.get(name);
    if (key) {
      hidden.value = key.name;
      search.value = keyDisplay(key);
      showError("");
    } else if (name) {
      hidden.value = "";
      search.value = name;
      // With no list loaded, nothing is known about this key either way.
      // The message above the steps explains that; calling every key wrong
      // would be a lie.
      showError(keysByName.size === 0 ? "" : `There is no key called '${name}'. Pick a key.`);
    } else {
      hidden.value = "";
      search.value = "";
      showError("");
    }
  }

  function hideOptions() {
    options.hidden = true;
  }

  function matches(query) {
    const q = query.trim().toLowerCase();
    const found = [];
    for (const group of keyGroups) {
      // Both halves are searched, so "up" finds UP_ARROW and "8" finds EIGHT.
      const keys = group.keys.filter(
        key => !q || key.name.toLowerCase().includes(q) || key.label.toLowerCase().includes(q)
      );
      if (keys.length > 0) found.push({ name: group.name, keys });
    }
    return found;
  }

  function showOptions(query) {
    options.innerHTML = "";
    const groups = matches(query);
    if (groups.length === 0) {
      const empty = document.createElement("div");
      empty.className = "key-option-empty";
      empty.textContent = "No key matches that.";
      options.appendChild(empty);
    }
    for (const group of groups) {
      const heading = document.createElement("div");
      heading.className = "key-option-group";
      heading.textContent = group.name;
      options.appendChild(heading);
      for (const key of group.keys) {
        const option = document.createElement("button");
        option.type = "button";
        option.className = "key-option";
        option.textContent = keyDisplay(key);
        // mousedown, not click: the search box's blur would otherwise land
        // first and close the list out from under the pointer.
        option.onmousedown = (e) => {
          e.preventDefault();
          setKey(key.name);
          hideOptions();
        };
        options.appendChild(option);
      }
    }
    options.hidden = false;
  }

  // What someone typed, turned back into a key: the whole "8 (EIGHT)", the
  // name on its own, or the everyday label all count.
  function resolveTyped(text) {
    const wanted = text.trim().toLowerCase();
    if (!wanted) return "";
    for (const group of keyGroups) {
      for (const key of group.keys) {
        if (
          key.name.toLowerCase() === wanted ||
          key.label.toLowerCase() === wanted ||
          keyDisplay(key).toLowerCase() === wanted
        ) {
          return key.name;
        }
      }
    }
    return null;
  }

  search.onfocus = () => showOptions("");
  search.oninput = () => {
    hidden.value = "";
    showError("");
    showOptions(search.value);
  };
  search.onblur = () => {
    hideOptions();
    const resolved = resolveTyped(search.value);
    if (resolved === null) {
      hidden.value = "";
      showError(`There is no key called '${search.value.trim()}'. Pick a key.`);
    } else {
      setKey(resolved);
    }
  };
  search.onkeydown = (e) => {
    if (e.key === "Escape") {
      hideOptions();
      return;
    }
    if (e.key === "Enter") {
      // Enter takes the first key in the list, which is the one the person
      // typing is looking at.
      e.preventDefault();
      const groups = matches(search.value);
      if (groups.length > 0) {
        setKey(groups[0].keys[0].name);
        hideOptions();
      }
    }
  };

  captureBtn.onclick = () => {
    if (cancelCapture) {
      cancelCapture();
      return;
    }
    const onKeyDown = (event) => {
      // The row can be removed, or changed to a Wait, while this is
      // listening. Stop listening rather than swallowing someone's keypress
      // on behalf of a row that is no longer on the page.
      if (!node.isConnected) {
        cancelCapture();
        return;
      }
      // A modifier held on its own is not the key being captured; keep
      // waiting for the one that follows it.
      if (["Meta", "Control", "Alt", "Shift", "CapsLock"].includes(event.key)) return;
      event.preventDefault();
      event.stopPropagation();
      const name = toKeycodeName(event);
      cancelCapture();
      if (name === null) {
        showError(`There is no key called '${event.key}'. Pick a key.`);
        return;
      }
      setKey(name);
    };
    cancelCapture = () => {
      document.removeEventListener("keydown", onKeyDown, true);
      captureBtn.textContent = "Press a key";
      captureBtn.classList.remove("capturing");
      cancelCapture = null;
    };
    captureBtn.textContent = "Press any key";
    captureBtn.classList.add("capturing");
    document.addEventListener("keydown", onKeyDown, true);
  };

  setKey(initialName || "");
}

function buildStepRow(step, ownScriptId) {
  const kind = step[0];
  const tpl = document.getElementById(`tpl-step-${kind}`) || document.getElementById("tpl-step-press");
  const node = tpl.content.cloneNode(true).querySelector(".step");

  if (kind === "press") {
    setUpKeyPicker(node, step[1] || "");
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

// Reads the rows back out. A press row whose key is not one the device has
// counts as unresolved: the row keeps showing what was there, and nothing
// is saved until someone picks a real key.
function readSteps(stepsList) {
  const steps = [];
  let unresolved = false;
  for (const node of stepsList.children) {
    const kind = node.dataset.kind;
    if (kind === "press") {
      const key = node.querySelector(".step-key").value.trim();
      const hold = parseFloat(node.querySelector(".step-hold").value) || 0;
      if (key) {
        steps.push(["press", key, hold]);
      } else {
        unresolved = true;
      }
    } else if (kind === "wait") {
      const seconds = parseFloat(node.querySelector(".step-seconds").value) || 0;
      steps.push(["wait", seconds]);
    } else if (kind === "run") {
      const ref = node.querySelector(".step-ref").value;
      const times = parseInt(node.querySelector(".step-times").value, 10) || 1;
      if (ref) steps.push(["run", ref, times]);
    }
  }
  return { steps, unresolved };
}

// -----
// Run history
//
// The records come from the server's own poller, which watches the device
// every few seconds whether or not this page is open. Nothing here starts
// or ends a record -- this is only the view.
// -----

function historyPhrase(record) {
  const target =
    record.target_loops === null || record.target_loops === undefined ? "∞" : record.target_loops;
  const loops = record.loops_done || 0;
  if (record.outcome === "finished") return `finished ${loops} of ${target}`;
  // The pass that failed is the one after the passes that completed.
  if (record.outcome === "failed") return `failed at loop ${loops + 1} of ${target}`;
  if (record.outcome === "stopped_by_you") return `you stopped it at loop ${loops} of ${target}`;
  if (record.outcome === "lost_contact") return `lost contact at loop ${loops} of ${target}`;
  // We asked it to stop and then lost contact, so it never confirmed. It
  // may have stopped; it may also still be running.
  if (record.outcome === "stop_unconfirmed")
    return `stop requested, unconfirmed - loop ${loops} of ${target}`;
  return `running, loop ${loops} of ${target}`;
}

// The device says "stopped at step 4 of 12: ...". The row already says
// which loop it was on, so this trims it to "step 4: ...".
function shortenRunError(text) {
  return String(text || "").replace(/^stopped at (step \d+) of \d+/, "$1");
}

function formatRunDuration(startedAt, endedAt) {
  const start = new Date(startedAt);
  const end = new Date(endedAt);
  if (isNaN(start) || isNaN(end)) return null;
  const total = Math.max(0, Math.round((end - start) / 1000));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${total % 60}s`;
  return `${total}s`;
}

// Relative in the row, absolute in the tooltip: "ended 6:41am" today,
// "ended Aug 30" before that.
function formatEndedAt(endedAt) {
  const when = new Date(endedAt);
  if (isNaN(when)) return "";
  if (when.toDateString() === new Date().toDateString()) {
    const time = when
      .toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })
      .toLowerCase()
      .replace(/\s/g, "");
    return `ended ${time}`;
  }
  return `ended ${when.toLocaleDateString([], { month: "short", day: "numeric" })}`;
}

function buildHistoryRow(record) {
  const row = document.createElement("div");
  row.className = "history-row";

  const name = document.createElement("strong");
  name.textContent = record.script_name || "(unknown script)";
  row.appendChild(name);

  const parts = [historyPhrase(record)];
  if (record.outcome === "finished") {
    const duration = formatRunDuration(record.started_at, record.ended_at);
    if (duration) parts.push(duration);
  }
  if (record.error) parts.push(shortenRunError(record.error));
  for (const part of parts) {
    row.appendChild(document.createTextNode(" - " + part));
  }

  if (record.ended_at) {
    row.appendChild(document.createTextNode(" - "));
    const ended = document.createElement("span");
    ended.className = "history-ended";
    ended.textContent = formatEndedAt(record.ended_at);
    ended.title = new Date(record.ended_at).toLocaleString();
    row.appendChild(ended);
  }

  return row;
}

async function renderHistory() {
  isEditingScript = false;
  let records;
  try {
    records = await api.getHistory();
  } catch (e) {
    main.innerHTML = "";
    const failed = document.createElement("div");
    failed.className = "empty-state";
    failed.textContent = "Couldn't load the run history: " + e.message;
    main.appendChild(failed);
    return;
  }

  main.innerHTML = "";

  const header = document.createElement("div");
  header.className = "list-header";

  const headerTop = document.createElement("div");
  headerTop.className = "list-header-top";

  const title = document.createElement("h2");
  title.style.margin = "0";
  title.textContent = "History";

  const backBtn = document.createElement("button");
  backBtn.className = "btn";
  backBtn.textContent = "Back to scripts";
  backBtn.onclick = () => renderList();

  headerTop.appendChild(title);
  headerTop.appendChild(backBtn);
  header.appendChild(headerTop);
  main.appendChild(header);

  const note = document.createElement("p");
  note.className = "history-note";
  note.textContent =
    "Every run is recorded whether or not this page is open. The last 50 are kept.";
  main.appendChild(note);

  if (records.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No runs yet. Pick a script and hit Start.";
    main.appendChild(empty);
    return;
  }

  for (const record of records) {
    main.appendChild(buildHistoryRow(record));
  }
}

bindEvent("history-btn", "click", () => renderHistory());

// -----
// The status panel
//
// One renderer owns this panel: the status rows, the two lines around
// them, the Start button and the Stop button. Nothing else in this file
// writes any of that. The panel used to be painted from half a dozen
// places -- the Start handler, the Stop handler, two branches of the
// poller -- and every one of its bugs came from two of them disagreeing.
//
// The poll is installed once when the page loads and runs until the page
// closes. It is never torn down by Start or Stop: a run keeps going with
// no browser open, so a panel that only polls when this tab started the
// run is a panel that lies.
// -----

const POLL_INTERVAL = 5000; // Ask the device how it's doing every 5 seconds.

// How many checks in a row have to miss before the panel says the board
// has gone quiet. One or two are a Wi-Fi blip; saying "unreachable" on
// the first one made a slow answer look like a dead device.
//
// The server's history poller has a threshold of its own with the same
// value. They are deliberately separate counters: that one runs with no
// browser open and decides what goes in the run history, while this one
// is per-tab and decides only what is on screen. Browsers slow down
// timers in background tabs, so sharing a counter would let a tab nobody
// is looking at spoil a permanent record.
const MISSED_POLLS_BEFORE_QUIET = 3;

// How long the board gets to confirm a stop before the button is offered
// again. Shorter than three poll intervals on purpose: at 15 seconds this
// and the third missed check would fire together and put two different
// explanations of one event on screen.
const STOP_CONFIRM_TIMEOUT_MS = 12000;

// Everything the renderer draws from.
let panel = {
  lastStatus: null, // the last status the device actually returned
  lastStatusAt: null, // when it arrived, for "last seen"
  consecutiveFailedPolls: 0,
  starting: false, // a Start request is in flight
  stopRequestedAt: null, // when we asked it to stop, until it confirms
  stopUnconfirmed: false, // that request went past STOP_CONFIRM_TIMEOUT_MS
  stoppedAt: null, // {loops, target} from the poll that saw the run end
  stopTimeoutTimer: null,
  // The device's own estimate of the time left, and when it said it. The
  // seconds between polls are counted off from there, so the number moves
  // every second but is corrected by the board every poll. The page used to
  // work the whole time out for itself from the script's length, which a
  // nested run makes meaningless: the board is the only thing that knows
  // which repeat it is on.
  eta: null, // {seconds, at}
};

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

// -----
// The renderer
// -----

function partName(status, part) {
  const names = status.part_names || [];
  return names[part - 1] || null;
}

function formatLoops(status) {
  // Inside a repeat, the iteration is the number worth watching: "A, then B
  // a thousand times, then C" is one loop of one, and reading 0 / 1 for four
  // hours is exactly the blindness this panel is for.
  const position = status.position;
  if (position && position.iterations) {
    const count = `${position.iteration} of ${position.iterations}`;
    const name = partName(status, position.part);
    return name ? `${name}, ${count}` : count;
  }
  const target =
    status.target_loops === null || status.target_loops === undefined
      ? "∞"
      : status.target_loops;
  return `${status.loop_count} / ${target}`;
}

function loopLabel(status) {
  return status !== null && status.position && status.position.iterations
    ? "Repeat"
    : "Loop";
}

function formatPosition(status) {
  // Only call them parts when the script really is a list of other scripts,
  // every one of them named. Anything else gets the step number rather than
  // an invented part.
  const position = status.position;
  const names = status.part_names || [];
  if (position && names.length === position.parts && names.every(n => n)) {
    return `part ${position.part} of ${position.parts}`;
  }
  return `step ${status.current_step + 1} of ${status.total_steps}`;
}

function formatEta(status, goneQuiet) {
  // A board that has gone quiet is not telling us anything, and a clock
  // still ticking down would be this page's own guess dressed up as news.
  if (goneQuiet || status === null || !status.running || panel.eta === null) {
    return "-";
  }
  const counted = (Date.now() - panel.eta.at) / 1000;
  return `about ${formatDuration(Math.max(0, panel.eta.seconds - counted))} left`;
}

function formatSteps(status) {
  return `${status.current_step + 1} / ${status.total_steps}`;
}

function stoppedNote(stopped) {
  if (stopped.target === null || stopped.target === undefined) {
    return `Stopped at loop ${stopped.loops}.`;
  }
  return `Stopped at loop ${stopped.loops} of ${stopped.target}.`;
}

function goneQuietNote() {
  if (panel.lastStatus === null) {
    return "No answer from the Pico since this page opened.";
  }
  const seconds = Math.round((Date.now() - panel.lastStatusAt) / 1000);
  const loops = panel.lastStatus.loop_count;
  let note = `Last seen ${seconds} seconds ago at loop ${loops}.`;
  if (panel.stopRequestedAt !== null) {
    note += " The stop was sent; it may already have stopped.";
  }
  return note;
}

function setPanelLine(id, text) {
  const el = document.getElementById(id);
  if (!el) return;
  el.textContent = text;
  el.style.display = text ? "block" : "none";
}

bindEvent("host-writes-btn", "click", async () => {
  const btn = document.getElementById("host-writes-btn");
  const out = document.getElementById("host-writes-status");
  if (!confirm("Hand the Pico's drive back to this Mac?\n\nYou'll be able to drag files onto CIRCUITPY again, but deploying firmware from this page will stop working until you give it back.")) {
    return;
  }
  btn.disabled = true;
  out.textContent = "Asking the Pico...";
  try {
    const r = await fetch("/api/device/host-writes", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled: true }),
    });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "the Pico refused");
    out.textContent = data.message;
  } catch (e) {
    out.textContent = e.message;
  } finally {
    btn.disabled = false;
  }
});

function renderPanel() {
  const status = panel.lastStatus;
  // While we are waiting on a stop, a run of missed checks is the same
  // event, not a second one. Saying both at once would be two messages
  // for one problem.
  const waitingOnStop = panel.stopRequestedAt !== null && !panel.stopUnconfirmed;
  const goneQuiet =
    panel.consecutiveFailedPolls >= MISSED_POLLS_BEFORE_QUIET && !waitingOnStop;

  let statusText;
  let statusClass = null;
  let loopText = "-";
  let partText = "-";
  let stepText = "-";
  let note = "";
  let detail = "";
  let fault = "";
  let indicator;
  let stopEnabled;
  let stopLabel = "Stop";

  if (status !== null) {
    loopText = formatLoops(status);
    partText = formatPosition(status);
    stepText = formatSteps(status);
    // Why a run stopped early. The firmware reports last_error when a step
    // fails and last_fault when it recovers from something worse.
    fault = status.last_error || status.last_fault || "";
  }
  if (panel.stoppedAt !== null) {
    note = stoppedNote(panel.stoppedAt);
  }

  if (goneQuiet) {
    statusText = "not answering";
    detail = goneQuietNote();
    indicator = "unreachable";
    // Enabled so a stop can be tried again at the moment it matters most.
    stopEnabled = true;
  } else if (status === null) {
    // Nothing has come back yet. Say that, rather than showing an idle
    // panel that reads as "nothing is running".
    statusText = "Checking the Pico...";
    indicator = "connecting";
    stopEnabled = false;
  } else if (status.running) {
    indicator = "connected";
    statusClass = "status-running";
    if (waitingOnStop) {
      statusText = "running - finishing the current step";
      stopLabel = "Stopping...";
      stopEnabled = false;
    } else {
      statusText = "running";
      stopEnabled = true;
    }
  } else {
    statusText = "not running";
    statusClass = "status-idle";
    indicator = "connected";
    stopEnabled = false;
  }

  if (panel.stopUnconfirmed) {
    // The board never said it stopped. It may have; it may also still be
    // running and still typing, so the honest thing is to say so and let
    // her send the stop again.
    stopEnabled = true;
    if (!goneQuiet) {
      detail = "The Pico hasn't confirmed it stopped. Try again, or unplug and replug it.";
    }
  }

  const runningEl = document.getElementById("st-running");
  runningEl.textContent = statusText;
  runningEl.classList.toggle("status-running", statusClass === "status-running");
  runningEl.classList.toggle("status-idle", statusClass === "status-idle");
  const loopLabelEl = document.getElementById("st-loop-label");
  if (loopLabelEl) loopLabelEl.textContent = loopLabel(status);
  document.getElementById("st-part").textContent = partText;
  document.getElementById("st-loop").textContent = loopText;
  document.getElementById("st-step").textContent = stepText;
  document.getElementById("st-eta").textContent = formatEta(status, goneQuiet);
  setPanelLine("st-note", note);
  setPanelLine("st-detail", detail);
  setPanelLine("st-fault", fault);
  updateDeviceIndicator(indicator);

  const stopBtn = document.getElementById("run-stop-btn");
  stopBtn.textContent = stopLabel;
  stopBtn.disabled = !stopEnabled;

  const startBtn = document.getElementById("run-start-btn");
  if (panel.starting) {
    startBtn.textContent = "Starting...";
    startBtn.disabled = true;
  } else if (status !== null && status.running) {
    startBtn.textContent = "Running...";
    startBtn.disabled = true;
  } else {
    startBtn.textContent = "Start";
    startBtn.disabled = false;
  }
}

function updateDeviceIndicator(state) {
  const dot = document.querySelector(".device-indicator-dot");
  const label = document.getElementById("device-indicator-label");
  if (!dot || !label) return;

  dot.className = "device-indicator-dot";
  if (state === "connected") {
    dot.classList.add("connected");
    label.textContent = "Connected";
  } else if (state === "unreachable") {
    dot.classList.add("unreachable");
    label.textContent = "Unreachable";
  } else {
    dot.classList.add("connecting");
    label.textContent = "Connecting";
  }
}

// -----
// The poll
// -----

function forgetStopRequest() {
  panel.stopRequestedAt = null;
  panel.stopUnconfirmed = false;
  if (panel.stopTimeoutTimer !== null) {
    clearTimeout(panel.stopTimeoutTimer);
    panel.stopTimeoutTimer = null;
  }
}

// A tab left open keeps running whatever JavaScript it loaded, however old.
// Cache headers cannot help with that, and it has made working code look
// broken more than once. Compare what this tab is running against what the
// server has, and say so rather than letting it be a mystery.
async function checkPageVersion() {
  if (!window.KEYBOT_VERSION) return;
  try {
    const r = await fetch("/api/app-version", { cache: "no-store" });
    if (!r.ok) return;
    const data = await r.json();
    const notice = document.getElementById("stale-page");
    if (notice && data.version && data.version !== window.KEYBOT_VERSION) {
      notice.hidden = false;
    }
  } catch (e) {
    // Offline or restarting. Not worth saying anything about.
  }
}

async function pollStatus() {
  let status;
  try {
    status = await api.deviceStatus();
  } catch {
    panel.consecutiveFailedPolls += 1;
    // One or two misses change nothing on screen: the panel keeps showing
    // the last thing the device actually said.
    renderPanel();
    return;
  }

  const wasRunning = panel.lastStatus !== null && panel.lastStatus.running;
  panel.consecutiveFailedPolls = 0;
  panel.lastStatus = status;
  panel.lastStatusAt = Date.now();

  panel.eta =
    status.running && typeof status.estimated_seconds_remaining === "number"
      ? { seconds: status.estimated_seconds_remaining, at: Date.now() }
      : null;

  if (status.running) {
    panel.stoppedAt = null;
  } else {
    if (wasRunning) {
      // The poll that sees a run end is the one carrying the loop it got
      // to -- the same number the server writes into the run history --
      // so it is taken from here rather than tracked separately.
      panel.stoppedAt = { loops: status.loop_count, target: status.target_loops };
    }
    // The device says it is not running, which is the confirmation any
    // pending stop was waiting for.
    forgetStopRequest();
  }

  renderPanel();
}

// -----
// Run controls
// -----

bindEvent("run-start-btn", "click", async () => {
  const errBox = document.getElementById("run-error");
  errBox.textContent = "";
  const scriptId = document.getElementById("run-script-select").value;
  const timesVal = document.getElementById("run-times").value;
  const times = timesVal ? parseInt(timesVal, 10) : null;
  if (!scriptId) {
    errBox.textContent = "Pick a script first.";
    return;
  }

  // The previous run's ending is not this run's news: drop its loop count
  // and its failure now rather than leaving them up until the first poll.
  panel.stoppedAt = null;
  if (panel.lastStatus !== null) {
    panel.lastStatus = Object.assign({}, panel.lastStatus, {
      last_error: null,
      last_fault: null,
    });
  }
  panel.starting = true;
  renderPanel();

  try {
    await api.runScript(scriptId, times);
    lastRunScriptId = scriptId;
    localStorage.setItem("lastRunScriptId", scriptId);
    addToRecentScripts(scriptId);
  } catch (e) {
    errBox.textContent = e.message;
  } finally {
    // Whether it started or failed, the button goes back to the renderer.
    // Leaving it stuck on "Starting..." is what jammed it before.
    panel.starting = false;
    renderPanel();
  }

  await pollStatus();
});

bindEvent("run-stop-btn", "click", async () => {
  const errBox = document.getElementById("run-error");
  errBox.textContent = "";

  // A second press is only possible after the first one timed out, and
  // means "send it again". The server treats the resend as the same stop.
  panel.stopRequestedAt = Date.now();
  panel.stopUnconfirmed = false;
  if (panel.stopTimeoutTimer !== null) clearTimeout(panel.stopTimeoutTimer);
  panel.stopTimeoutTimer = setTimeout(() => {
    panel.stopTimeoutTimer = null;
    panel.stopUnconfirmed = true;
    renderPanel();
  }, STOP_CONFIRM_TIMEOUT_MS);
  renderPanel();

  try {
    await api.deviceStop();
  } catch (e) {
    errBox.textContent = e.message;
  }
  await pollStatus();
});

bindEvent("device-url-save", "click", async () => {
  const url = document.getElementById("device-url").value.trim();
  if (!url) return;
  await api.setSettings({ device_url: url });
  pollStatus();
});

async function loadSettings() {
  const s = await api.getSettings();
  const box = elementOrWarn("device-url");
  if (box) box.value = s.device_url;
}

// -----
// Firmware deploy
// -----

const deployBtn = document.getElementById("deploy-btn");
const deployStatusBox = document.getElementById("deploy-status");
let deployPollTimer = null;

bindEvent("deploy-btn", "click", async () => {
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
});

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
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  if (m === 0) return `${s}s`;
  return `${m}m ${s % 60}s`;
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

bindEvent("stale-page-reload", "click", () => location.reload(true));

(async function init() {
  checkPageVersion();
  setInterval(checkPageVersion, 60000);
  // The panel is live from the moment the page opens to the moment it
  // closes, whether or not this tab is the one that started the run. A
  // page opened at 3am on a run that started at 10pm shows that run.
  // This is set up before the script list loads so the panel says what it
  // is doing straight away.
  renderPanel();
  pollStatus();
  setInterval(pollStatus, POLL_INTERVAL);
  // Between polls the panel counts the device's estimate down itself, so
  // the time left moves every second instead of jumping every five.
  setInterval(renderPanel, 1000);

  initSidebarSections();
  await loadLivePressSupport();
  await loadKeycodes();
  await renderList();
  await loadSettings();

  // Add keyboard shortcut hints
  const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform);
  const cmdKey = isMac ? "⌘" : "Ctrl";
  // No Cmd+R hint: that binding was removed because it swallowed the
  // browser's refresh. Advertising a shortcut that does not exist costs
  // more trust than the shortcut was worth.
  // A plain lookup: if this button is missing, wiring it up above has
  // already said so, and saying it twice helps nobody.
  const startBtn = document.getElementById("run-start-btn");
  if (startBtn) startBtn.title = `${cmdKey}+Enter: Run script`;

  // Display keyboard hints in sidebar if desired
  const sidebar = elementOrWarn("sidebar");
  if (!sidebar) return;
  const shortcutsHint = document.createElement("div");
  shortcutsHint.style.cssText = "font-size: 11px; color: var(--muted); padding: 10px; border-top: 1px solid var(--border); margin-top: auto; text-align: center;";
  shortcutsHint.textContent = `Shortcuts: ${cmdKey}+⏎ run • ${cmdKey}+S save`;
  sidebar.appendChild(shortcutsHint);
})();
