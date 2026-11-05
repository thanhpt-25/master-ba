// A tiny, zero-dependency DOM shim — just enough of the browser API for the
// MasterBA frontend's `dom.js` primitives and critical-flow tests to run under
// plain Node (no jsdom, no browser). It is NOT a spec-compliant DOM; it covers
// exactly the surface the code under test touches. Install it with install().

class ClassList {
  constructor(el) {
    this.el = el;
    this.set = new Set();
  }
  add(...names) { for (const n of names) if (n) this.set.add(n); this._sync(); }
  remove(...names) { for (const n of names) this.set.delete(n); this._sync(); }
  toggle(name, force) {
    const on = force === undefined ? !this.set.has(name) : force;
    if (on) this.set.add(name); else this.set.delete(name);
    this._sync();
    return on;
  }
  contains(name) { return this.set.has(name); }
  _sync() { this.el._attrs.class = [...this.set].join(" "); }
  _load(value) { this.set = new Set(String(value || "").split(/\s+/).filter(Boolean)); }
}

class Style {
  constructor() { this._props = {}; }
  setProperty(name, value) { this._props[name] = value; }
  getPropertyValue(name) { return this._props[name] ?? ""; }
}

let activeElement = null;

class El {
  constructor(tag) {
    this.tagName = String(tag).toUpperCase();
    this.childNodes = [];
    this._attrs = {};
    this._listeners = {};
    this.style = new Style();
    this.classList = new ClassList(this);
    this.parentNode = null;
    this.translate = true;
    this._text = null; // text-node content when tagName is "#text"
    this.isContentEditable = false;
  }

  // ---- attributes ----
  setAttribute(name, value) {
    this._attrs[name] = String(value);
    if (name === "class") this.classList._load(value);
    if (name === "id") this.id = String(value);
  }
  getAttribute(name) { return name in this._attrs ? this._attrs[name] : null; }
  removeAttribute(name) { delete this._attrs[name]; }
  hasAttribute(name) { return name in this._attrs; }
  get className() { return this._attrs.class || ""; }
  set className(v) { this.setAttribute("class", v); }

  // ---- text ----
  get textContent() {
    if (this._text !== null) return this._text;
    return this.childNodes.map((c) => c.textContent).join("");
  }
  set textContent(v) {
    this.childNodes = [];
    this._text = null;
    if (v !== "") this.append(String(v));
  }

  // ---- tree ----
  append(...nodes) {
    for (const node of nodes) {
      const n = node instanceof El ? node : El.text(String(node));
      n.parentNode = this;
      this.childNodes.push(n);
    }
  }
  replaceChildren(...nodes) {
    for (const c of this.childNodes) c.parentNode = null;
    this.childNodes = [];
    this.append(...nodes);
  }
  remove() {
    if (this.parentNode) {
      const i = this.parentNode.childNodes.indexOf(this);
      if (i >= 0) this.parentNode.childNodes.splice(i, 1);
      this.parentNode = null;
    }
  }
  get firstChild() { return this.childNodes[0] || null; }

  // ---- queries (descendant, by simple selector) ----
  querySelector(sel) { return this._query(sel, true)[0] || null; }
  querySelectorAll(sel) { return this._query(sel, false); }
  _query(selector, first) {
    const out = [];
    const matchers = selector.split(",").map((s) => parseSelector(s.trim()));
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (child instanceof El && child.tagName !== "#TEXT") {
          if (matchers.some((m) => m(child))) {
            out.push(child);
            if (first) return true;
          }
          if (walk(child)) return true;
        }
      }
      return false;
    };
    walk(this);
    return out;
  }

  // ---- events ----
  addEventListener(type, fn) {
    (this._listeners[type] ||= []).push(fn);
  }
  removeEventListener(type, fn) {
    this._listeners[type] = (this._listeners[type] || []).filter((f) => f !== fn);
  }
  dispatchEvent(event) {
    event.target ||= this;
    for (const fn of this._listeners[event.type] || []) fn.call(this, event);
    return true;
  }
  click() { this.dispatchEvent({ type: "click", target: this, preventDefault() {} }); }
  focus() { activeElement = this; }

  static text(value) {
    const n = new El("#text");
    n.tagName = "#TEXT";
    n._text = value;
    return n;
  }
}

function parseSelector(sel) {
  // Supports: tag, .class, #id, [attr], [attr="v"], tag.class, and descendant
  // combinators (space). The candidate matches the rightmost compound, then
  // each earlier compound must match some ancestor in order.
  const parts = sel.split(/\s+/).filter(Boolean);
  const compile = (part) => {
    const checks = [];
    let rest = part;
    const tagMatch = rest.match(/^[a-zA-Z#][\w-]*/);
    if (tagMatch && !["#", "."].includes(tagMatch[0][0])) {
      const tag = tagMatch[0].toUpperCase();
      checks.push((el) => el.tagName === tag);
      rest = rest.slice(tagMatch[0].length);
    }
    for (const m of rest.matchAll(/([.#])([\w-]+)|\[([\w-]+)(?:=["']?([^"'\]]*)["']?)?\]/g)) {
      if (m[1] === ".") checks.push((el) => el.classList.contains(m[2]));
      else if (m[1] === "#") checks.push((el) => el.id === m[2]);
      else if (m[3]) {
        const name = m[3], val = m[4];
        checks.push((el) => (val === undefined ? el.hasAttribute(name) : el.getAttribute(name) === val));
      }
    }
    return (el) => checks.every((c) => c(el));
  };
  const compounds = parts.map(compile);
  const last = compounds[compounds.length - 1];
  const ancestors = compounds.slice(0, -1);
  return (el) => {
    if (!last(el)) return false;
    // Each remaining compound (right to left) must match an ancestor, in order.
    let node = el.parentNode;
    for (let i = ancestors.length - 1; i >= 0; i--) {
      let found = false;
      while (node) {
        if (ancestors[i](node)) { found = true; node = node.parentNode; break; }
        node = node.parentNode;
      }
      if (!found) return false;
    }
    return true;
  };
}

class Doc {
  constructor() {
    this.body = new El("body");
    this.documentElement = new El("html");
    this._listeners = {};
    this.hidden = false;
  }
  createElement(tag) { return new El(tag); }
  createTextNode(value) { return El.text(value); }
  getElementById(id) { return this.body.querySelector(`#${id}`); }
  get activeElement() { return activeElement; }
  addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this._listeners[type] = (this._listeners[type] || []).filter((f) => f !== fn); }
  dispatchEvent(event) {
    event.target ||= this;
    for (const fn of this._listeners[event.type] || []) fn.call(this, event);
    return true;
  }
  querySelector(sel) { return this.body.querySelector(sel); }
  querySelectorAll(sel) { return this.body.querySelectorAll(sel); }
}

class Win {
  constructor() { this._listeners = {}; }
  addEventListener(type, fn) { (this._listeners[type] ||= []).push(fn); }
  removeEventListener(type, fn) { this._listeners[type] = (this._listeners[type] || []).filter((f) => f !== fn); }
  dispatchEvent(event) {
    event.target ||= this;
    for (const fn of this._listeners[event.type] || []) fn.call(this, event);
    return true;
  }
}

// Installs the shim onto globalThis. Returns a reset() to clear state between tests.
export function install() {
  const document = new Doc();
  const window = new Win();
  globalThis.document = document;
  globalThis.window = window;
  globalThis.Node = El;
  globalThis.Event = class { constructor(type) { this.type = type; } };
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; Object.assign(this, init); } };
  activeElement = null;
  return {
    document,
    window,
    reset() {
      document.body.childNodes = [];
      document._listeners = {};
      window._listeners = {};
      activeElement = null;
    },
    fireKey(type, key, opts = {}) {
      const event = { type, key, preventDefault() { this.defaultPrevented = true; }, defaultPrevented: false, ...opts };
      document.dispatchEvent(event);
      return event;
    },
  };
}

export { El };
