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

export function table(headers, rows, caption = "") {
  return h(
    "div",
    { class: "table-wrap", tabindex: "0", role: "region", "aria-label": caption || "table" },
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

export function empty(text) {
  return h("p", { class: "empty" }, text);
}

export function chip(id, extra = "") {
  return h("span", { class: `chip ${extra}` }, h("code", {}, id));
}
