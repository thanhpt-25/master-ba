// Tiny DOM helpers. Text is only ever inserted as text nodes, never as HTML.

const DATE_TIME = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

export function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

export function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  if (tag === "code") el.translate = false; // ids and tokens must not be machine-translated
  for (const [key, value] of Object.entries(attrs ?? {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key.startsWith("on") && typeof value === "function") {
      el.addEventListener(key.slice(2).toLowerCase(), value);
    } else if (key === "class") {
      el.className = value;
    } else if (key === "style") {
      // CSSOM calls are allowed by the Content-Security-Policy; a style attribute is not.
      for (const part of String(value).split(";")) {
        const [name, setting] = part.split(":");
        if (name && setting) el.style.setProperty(name.trim(), setting.trim());
      }
    } else if (value === true) {
      el.setAttribute(key, "");
    } else {
      el.setAttribute(key, String(value));
    }
  }
  return append(el, children);
}

export function clear(el) {
  el.replaceChildren();
  return el;
}

export function cellText(value) {
  if (value === null || value === undefined) return "";
  if (Array.isArray(value)) return value.map(cellText).join("\n");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function fmtTime(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : DATE_TIME.format(date);
}

const STATUS = {
  not_started: { icon: "○", label: "Not started", cls: "idle" },
  queued: { icon: "◔", label: "Queued", cls: "run" },
  running: { icon: "◐", label: "Running", cls: "run" },
  done: { icon: "✓", label: "Done", cls: "ok" },
  escalated: { icon: "▲", label: "Escalated", cls: "warn" },
  failed: { icon: "✕", label: "Failed", cls: "bad" },
  draft: { icon: "✎", label: "Draft", cls: "idle" },
  proposed: { icon: "○", label: "Proposed", cls: "idle" },
  approved: { icon: "✓", label: "Approved", cls: "run" },
  propagated: { icon: "✓", label: "Propagated", cls: "ok" },
  closed: { icon: "■", label: "Closed", cls: "idle" },
  planned: { icon: "·", label: "Planned", cls: "idle" },
  open: { icon: "○", label: "Open", cls: "warn" },
  answered: { icon: "✓", label: "Answered", cls: "ok" },
  in_review: { icon: "◔", label: "In review", cls: "warn" },
  ready: { icon: "▶", label: "Ready", cls: "run" },
  locked: { icon: "■", label: "Locked", cls: "idle" },
  withdrawn: { icon: "■", label: "Withdrawn", cls: "idle" },
  indexed: { icon: "✓", label: "Indexed", cls: "ok" },
  stale: { icon: "▲", label: "Stale", cls: "warn" },
  missing: { icon: "✕", label: "Missing", cls: "bad" },
};

// Status is shown as icon plus word; colour is never the only signal.
export function badge(status) {
  const info = STATUS[status] ?? { icon: "·", label: String(status), cls: "idle" };
  return h("span", { class: `badge ${info.cls}` }, h("span", { "aria-hidden": "true" }, info.icon), " ", info.label);
}

// opts: { dense } tightens padding for wide audit-style tables;
// { stickyFirst } pins the first column while the rest scrolls horizontally.
export function table(headers, rows, caption = "", opts = {}) {
  const cls = ["table-wrap", opts.dense ? "dense" : "", opts.stickyFirst ? "sticky-first" : ""].filter(Boolean).join(" ");
  return h(
    "div",
    { class: cls, tabindex: "0", role: "region", "aria-label": caption || "table" },
    h(
      "table",
      {},
      caption ? h("caption", { class: "sr-only" }, caption) : null,
      h("thead", {}, h("tr", {}, headers.map((text) => h("th", { scope: "col" }, text)))),
      h("tbody", {}, rows.map((row) => h("tr", {}, row.map((cell) => h("td", {}, cell))))),
    ),
  );
}

export function field(label, control, hint = "") {
  const id = control.id || `f${Math.random().toString(36).slice(2, 9)}`;
  control.id = id;
  return h("div", { class: "field" }, h("label", { for: id }, label), control, hint ? h("p", { class: "hint" }, hint) : null);
}

// `action` is an optional element (usually a link or button) offering the next step.
export function empty(text, action = null) {
  return h("div", { class: "empty" }, h("p", {}, text), action);
}

export function chip(id, extra = "") {
  return h("span", { class: `chip ${extra}` }, h("code", {}, id));
}

// A small inline spinner; label is read by assistive tech, hidden visually.
export function spinner(label = "Loading…") {
  return h("span", { class: "spinner", role: "status" }, h("span", { class: "spinner-mark", "aria-hidden": "true" }), h("span", { class: "sr-only" }, label));
}

// Skeleton placeholder bars that approximate a view while it loads.
export function skeleton(rows = 4) {
  const bars = [];
  for (let i = 0; i < rows; i++) bars.push(h("div", { class: "sk-bar", style: `--w:${55 + ((i * 37) % 40)}%` }));
  return h("div", { class: "skeleton", "aria-hidden": "true" }, h("div", { class: "sk-bar sk-title", style: "--w:38%" }), ...bars);
}

// Wraps a split-view <nav> with a disclosure toggle that only appears on narrow
// screens (CSS-driven). `label` names what the list contains, e.g. "Documents".
export function splitNav(label, children) {
  const nav = h("nav", { "aria-label": label, "data-collapsed": "false" });
  const toggle = h(
    "button",
    { class: "button nav-toggle", type: "button", "aria-expanded": "true" },
    h("span", {}, label),
    h("span", { class: "nav-toggle-mark", "aria-hidden": "true" }, "▾"),
  );
  toggle.addEventListener("click", () => {
    const open = nav.getAttribute("data-collapsed") === "true";
    nav.setAttribute("data-collapsed", open ? "false" : "true");
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  });
  append(nav, [toggle, children]);
  return nav;
}

// A live-status pulse paired with a word; colour is never the only signal.
export function liveDot(active, label) {
  return h("span", { class: `live ${active ? "on" : "off"}` }, h("span", { class: "live-mark", "aria-hidden": "true" }), label);
}

// An error block with an optional Retry button. onRetry receives no arguments.
export function errorBox(message, onRetry = null) {
  return h(
    "div",
    { class: "load-error", role: "alert" },
    h("span", { class: "load-error-mark", "aria-hidden": "true" }, "✕"),
    h("p", {}, message || "Something went wrong."),
    onRetry ? h("button", { type: "button", onClick: onRetry }, "Try again") : null,
  );
}

let openDialog = null;

// A focus-trapped confirmation dialog that replaces window.confirm.
// Resolves to true on confirm, false on cancel/escape. Only one is open at a time.
export function confirmDialog({ title = "Please confirm", message = "", confirmLabel = "Confirm", cancelLabel = "Cancel", danger = false } = {}) {
  return new Promise((resolve) => {
    if (openDialog) {
      openDialog.close(false);
      openDialog = null;
    }
    const lastFocus = document.activeElement;
    let settled = false;
    const finish = (value) => {
      if (settled) return;
      settled = true;
      document.removeEventListener("keydown", onKey, true);
      overlay.remove();
      openDialog = null;
      if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus({ preventScroll: true });
      resolve(value);
    };
    const confirmBtn = h("button", { type: "button", class: danger ? "primary danger" : "primary", onClick: () => finish(true) }, confirmLabel);
    const cancelBtn = h("button", { type: "button", onClick: () => finish(false) }, cancelLabel);
    const card = h(
      "div",
      { class: "dialog", role: "alertdialog", "aria-modal": "true", "aria-labelledby": "dlg-title", "aria-describedby": message ? "dlg-msg" : null },
      h("h2", { id: "dlg-title" }, title),
      message ? h("p", { id: "dlg-msg", class: "prose" }, message) : null,
      h("div", { class: "dialog-actions" }, cancelBtn, confirmBtn),
    );
    const overlay = h("div", { class: "dialog-overlay", onClick: (e) => { if (e.target === overlay) finish(false); } }, card);
    const focusable = () => card.querySelectorAll("button");
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        finish(false);
      } else if (event.key === "Tab") {
        const items = focusable();
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey, true);
    document.body.append(overlay);
    openDialog = { close: finish };
    confirmBtn.focus({ preventScroll: true });
  });
}

// Runs an async loader into `host`, showing a skeleton first, then either the
// rendered content or an error with a Retry button. Returns a function that
// re-runs the load. `render` receives the resolved data and the host element.
export function asyncView(host, load, render, { rows = 5 } = {}) {
  let token = 0;
  const run = async () => {
    const mine = ++token;
    clear(host).append(skeleton(rows));
    try {
      const data = await load();
      if (mine !== token) return;
      clear(host);
      render(data, host);
    } catch (error) {
      if (mine !== token) return;
      clear(host).append(loadError(error, run));
    }
  };
  run();
  return run;
}

// An errorBox for a failed load; a 401 instead tells app.js to show the login page.
export function loadError(error, onRetry) {
  if (error?.status === 401) window.dispatchEvent(new Event("masterba:unauthorized"));
  return errorBox(error?.message, onRetry);
}
