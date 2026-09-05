// A very small stand-in for a browser, enough to run webapp/app/static/app.js
// and drive the script editor from node.
//
// The key picker is DOM code: it can only be tested by building a real step
// row and sending it real events. There is no browser here and no jsdom to
// install, so this is the smallest thing that can hold that code honestly --
// elements, classes, values, and events that bubble. It is not a browser and
// does not try to be: layout, styling and focus rules are all absent.

class ClassList {
  constructor(el) { this.el = el; this.set = new Set(); }
  add(...names) { names.forEach(n => this.set.add(n)); }
  remove(...names) { names.forEach(n => this.set.delete(n)); }
  contains(name) { return this.set.has(name); }
  toggle(name, on) { if (on === undefined) on = !this.set.has(name); on ? this.set.add(name) : this.set.delete(name); }
  toString() { return [...this.set].join(" "); }
}

class FakeEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.bubbles = Boolean(init.bubbles);
    Object.assign(this, init);
    this.defaultPrevented = false;
    this.propagationStopped = false;
  }
  preventDefault() { this.defaultPrevented = true; }
  stopPropagation() { this.propagationStopped = true; }
}

function escapeText(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

class FakeElement {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.children = [];
    this.parentNode = null;
    this.attributes = {};
    this.dataset = {};
    this.classList = new ClassList(this);
    this.style = {};
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this._text = "";
    this._listeners = { capture: {}, bubble: {} };
  }

  get className() { return this.classList.toString(); }
  set className(v) { this.classList.set = new Set(String(v).split(/\s+/).filter(Boolean)); }

  setAttribute(name, value) {
    this.attributes[name] = value;
    if (name === "class") this.className = value;
    if (name === "id") this.id = value;
    if (name === "value") this.value = value;
    if (name === "type") this.type = value;
    if (name === "hidden") this.hidden = true;
    if (name.startsWith("data-")) {
      const key = name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase());
      this.dataset[key] = value;
    }
  }
  getAttribute(name) { return this.attributes[name]; }

  get textContent() {
    if (this.children.length === 0) return this._text;
    return this.children.map(c => c.textContent).join("");
  }
  set textContent(v) { this.children = []; this._text = v === null || v === undefined ? "" : String(v); }

  // app.js escapes text by round-tripping it through an element, so this
  // has to escape the way a browser does or the editor's own markup breaks.
  get innerHTML() {
    if (this.children.length === 0) return escapeText(this._text);
    return this.children.map(c => c.outerHTML).join("");
  }

  get outerHTML() {
    const attrs = Object.entries(this.attributes)
      .map(([name, value]) => ` ${name}="${value}"`).join("");
    const tag = this.tagName.toLowerCase();
    if (VOID_TAGS.has(tag)) return `<${tag}${attrs}>`;
    return `<${tag}${attrs}>${this.innerHTML}</${tag}>`;
  }
  set innerHTML(html) {
    this.children = [];
    this._text = "";
    if (String(html).trim()) parseInto(this, String(html));
  }

  get isConnected() {
    let node = this;
    while (node.parentNode) node = node.parentNode;
    return node === document.body || node.isDocument === true;
  }

  appendChild(child) {
    child.parentNode = this;
    this.children.push(child);
    return child;
  }
  insertBefore(child, before) {
    const at = this.children.indexOf(before);
    child.parentNode = this;
    this.children.splice(at < 0 ? this.children.length : at, 0, child);
    return child;
  }
  remove() {
    if (!this.parentNode) return;
    const at = this.parentNode.children.indexOf(this);
    if (at >= 0) this.parentNode.children.splice(at, 1);
    this.parentNode = null;
  }
  replaceWith(other) {
    if (!this.parentNode) return;
    const at = this.parentNode.children.indexOf(this);
    other.parentNode = this.parentNode;
    this.parentNode.children.splice(at, 1, other);
    this.parentNode = null;
  }
  get previousElementSibling() {
    if (!this.parentNode) return null;
    return this.parentNode.children[this.parentNode.children.indexOf(this) - 1] || null;
  }
  get nextElementSibling() {
    if (!this.parentNode) return null;
    return this.parentNode.children[this.parentNode.children.indexOf(this) + 1] || null;
  }

  // Selectors: ".class", "#id", "tag". Enough for what app.js asks for.
  matches(selector) {
    if (selector.startsWith(".")) return this.classList.contains(selector.slice(1));
    if (selector.startsWith("#")) return this.id === selector.slice(1);
    return this.tagName === selector.toUpperCase();
  }
  querySelectorAll(selector) {
    const found = [];
    for (const child of this.children) {
      if (child.matches(selector)) found.push(child);
      found.push(...child.querySelectorAll(selector));
    }
    return found;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }

  addEventListener(type, fn, capture) {
    const where = capture ? this._listeners.capture : this._listeners.bubble;
    (where[type] = where[type] || []).push(fn);
  }
  removeEventListener(type, fn, capture) {
    const where = capture ? this._listeners.capture : this._listeners.bubble;
    where[type] = (where[type] || []).filter(f => f !== fn);
  }
  dispatchEvent(event) {
    event.target = event.target || this;
    // Capture listeners on document first, the way a browser runs them.
    for (const fn of (document._listeners.capture[event.type] || []).slice()) {
      fn.call(document, event);
      if (event.propagationStopped) return !event.defaultPrevented;
    }
    let node = this;
    while (node) {
      const handler = node["on" + event.type];
      if (typeof handler === "function") handler.call(node, event);
      for (const fn of (node._listeners.bubble[event.type] || []).slice()) fn.call(node, event);
      if (event.propagationStopped || !event.bubbles) break;
      node = node.parentNode;
    }
    return !event.defaultPrevented;
  }

  // Conveniences the tests use to act like a person.
  focus() { this.dispatchEvent(new FakeEvent("focus")); }
  blur() { this.dispatchEvent(new FakeEvent("blur")); }
  click() { this.dispatchEvent(new FakeEvent("click", { bubbles: true })); }
  // Named typeText, not type: an <input> already has a "type" property.
  typeText(text) {
    this.value = text;
    this.dispatchEvent(new FakeEvent("input", { bubbles: true }));
  }
}

// --- the smallest HTML parser that can build what app.js writes ----------
const VOID_TAGS = new Set(["input", "br", "hr", "img", "meta", "link"]);

function parseInto(root, html) {
  const stack = [root];
  const tokens = html.match(/<[^>]+>|[^<]+/g) || [];
  for (const token of tokens) {
    const top = stack[stack.length - 1];
    if (!token.startsWith("<")) {
      const text = token.trim();
      if (text) top._text = (top._text || "") + text;
      continue;
    }
    if (token.startsWith("<!--")) continue;
    if (token.startsWith("</")) {
      if (stack.length > 1) stack.pop();
      continue;
    }
    const tag = token.slice(1).split(/[\s>/]/)[0];
    const el = new FakeElement(tag);
    for (const [, name, , value] of token.matchAll(/([a-zA-Z-]+)(=["']([^"']*)["'])?/g)) {
      if (name === tag) continue;
      el.setAttribute(name, value === undefined ? "" : value);
    }
    top.appendChild(el);
    if (!VOID_TAGS.has(tag.toLowerCase()) && !token.endsWith("/>")) stack.push(el);
  }
  return root;
}

function parseFragment(html) {
  return parseInto(new FakeElement("div"), html);
}

// --- document -----------------------------------------------------------
const elementsById = new Map();

const document = {
  isDocument: true,
  _listeners: { capture: {}, bubble: {} },
  body: new FakeElement("body"),
  createElement: (tag) => new FakeElement(tag),
  getElementById(id) {
    if (!elementsById.has(id)) {
      const el = new FakeElement("div");
      el.id = id;
      this.body.appendChild(el);
      elementsById.set(id, el);
    }
    return elementsById.get(id);
  },
  querySelectorAll(selector) { return this.body.querySelectorAll(selector); },
  querySelector(selector) { return this.body.querySelector(selector); },
  addEventListener: FakeElement.prototype.addEventListener,
  removeEventListener: FakeElement.prototype.removeEventListener,
  dispatchEvent: FakeElement.prototype.dispatchEvent,
};

module.exports = { FakeElement, FakeEvent, ClassList, document, parseFragment, elementsById };
