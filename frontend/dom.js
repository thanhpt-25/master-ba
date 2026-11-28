// Tiny DOM helpers. Text is only ever inserted as text nodes, never as HTML.

import { locale, N_, t } from "./i18n.js";

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
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat(locale(), { dateStyle: "medium", timeStyle: "short" }).format(date);
}

const STATUS = {
  not_started: { icon: "○", label: N_("Not started"), cls: "idle" },
  queued: { icon: "◔", label: N_("Queued"), cls: "run" },
  running: { icon: "◐", label: N_("Running"), cls: "run" },
  done: { icon: "✓", label: N_("Done"), cls: "ok" },
  escalated: { icon: "▲", label: N_("Escalated"), cls: "warn" },
  waiting_for_input: { icon: "●", label: N_("Waiting for input"), cls: "warn" },
  failed: { icon: "✕", label: N_("Failed"), cls: "bad" },
  draft: { icon: "✎", label: N_("Draft"), cls: "idle" },
  proposed: { icon: "○", label: N_("Proposed"), cls: "idle" },
  approved: { icon: "✓", label: N_("Approved"), cls: "seal" },
  propagated: { icon: "✓", label: N_("Propagated"), cls: "ok" },
  closed: { icon: "■", label: N_("Closed"), cls: "idle" },
  planned: { icon: "·", label: N_("Planned"), cls: "idle" },
  open: { icon: "○", label: N_("Open"), cls: "warn" },
  answered: { icon: "✓", label: N_("Answered"), cls: "ok" },
  in_review: { icon: "◔", label: N_("In review"), cls: "warn" },
  ready: { icon: "▶", label: N_("Ready"), cls: "run" },
  in_progress: { icon: "◑", label: N_("In progress"), cls: "run" },
  locked: { icon: "■", label: N_("Locked"), cls: "idle" },
  withdrawn: { icon: "■", label: N_("Withdrawn"), cls: "idle" },
  indexed: { icon: "✓", label: N_("Indexed"), cls: "ok" },
  stale: { icon: "▲", label: N_("Stale"), cls: "warn" },
  missing: { icon: "✕", label: N_("Missing"), cls: "bad" },
  superseded: { icon: "■", label: N_("Superseded"), cls: "idle" },
  interrupted: { icon: "▲", label: N_("Interrupted"), cls: "warn" },
  active: { icon: "●", label: N_("Active"), cls: "ok" },
  disabled: { icon: "■", label: N_("Disabled"), cls: "bad" },
};

export function statusLabel(status) {
  return STATUS[status] ? t(STATUS[status].label) : String(status);
}

// Status is shown as icon plus word; colour is never the only signal.
export function badge(status) {
  const info = STATUS[status] ?? { icon: "·", label: String(status), cls: "idle" };
  return h("span", { class: `badge ${info.cls}` }, h("span", { "aria-hidden": "true" }, info.icon), " ", t(info.label));
}

// opts: { dense } tightens padding for wide audit-style tables;
// { stickyFirst } pins the first column while the rest scrolls horizontally.
export function table(headers, rows, caption = "", opts = {}) {
  const cls = ["table-wrap", opts.dense ? "dense" : "", opts.stickyFirst ? "sticky-first" : ""].filter(Boolean).join(" ");
  return h(
    "div",
    { class: cls, tabindex: "0", role: "region", "aria-label": caption || t("Table") },
    h(
      "table",
      {},
      caption ? h("caption", { class: "sr-only" }, caption) : null,
      h("thead", {}, h("tr", {}, headers.map((text) => h("th", { scope: "col" }, text)))),
      h("tbody", {}, rows.map((row) => h("tr", {}, row.map((cell) => h("td", {}, cell))))),
    ),
  );
}

// The page header every screen opens with: title, one line on what the page is for, actions right.
export function pageHeader(title, description = "", ...actions) {
  actions = actions.filter(Boolean);
  return h("div", { class: "page-heading" },
    h("div", {}, h("h1", {}, title), description ? h("p", { class: "muted" }, description) : null),
    actions.length ? h("div", { class: "page-actions" }, actions) : null,
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
export function spinner(label = t("Loading…")) {
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
    h("p", {}, message || t("Something went wrong.")),
    onRetry ? h("button", { type: "button", onClick: onRetry }, t("Try again")) : null,
  );
}

let openDialog = null;

// A focus-trapped confirmation dialog that replaces window.confirm.
// Resolves to true on confirm, false on cancel/escape. Only one is open at a time.
export function confirmDialog({ title = t("Please confirm"), message = "", confirmLabel = t("Confirm"), cancelLabel = t("Cancel"), danger = false } = {}) {
  return new Promise((resolve) => {
    // answer is true only if the confirm button was pressed; Escape and the
    // backdrop leave it false. onClose fires exactly once, after teardown.
    let answer = false;
    modal(
      (close) => {
        const confirmBtn = h("button", { type: "button", class: danger ? "primary danger" : "primary", onClick: () => { answer = true; close(); } }, confirmLabel);
        const cancelBtn = h("button", { type: "button", onClick: () => { answer = false; close(); } }, cancelLabel);
        const card = h(
          "div",
          { class: "dialog" },
          h("h2", { id: "dlg-title" }, title),
          message ? h("p", { id: "dlg-msg", class: "prose" }, message) : null,
          h("div", { class: "dialog-actions" }, cancelBtn, confirmBtn),
        );
        // Prefer focusing the confirm button over the first focusable (cancel).
        queueMicrotask(() => confirmBtn.focus({ preventScroll: true }));
        return card;
      },
      { role: "alertdialog", labelledBy: "dlg-title", describedBy: message ? "dlg-msg" : undefined, onClose: () => resolve(answer) },
    );
  });
}

// A focus-trapped modal overlay used by confirmDialog and shortcutsDialog. `build`
// receives a `close` function and returns the card element to mount. Only one
// dialog is open at a time; Escape and the backdrop close it.
export function modal(build, { labelledBy, describedBy, role = "dialog", onClose = null } = {}) {
  if (openDialog) {
    openDialog.close();
    openDialog = null;
  }
  const lastFocus = document.activeElement;
  let settled = false;
  let overlay;
  const close = () => {
    if (settled) return;
    settled = true;
    document.removeEventListener("keydown", onKey, true);
    overlay.remove();
    openDialog = null;
    if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus({ preventScroll: true });
    if (onClose) onClose();
  };
  const card = build(close);
  card.setAttribute("role", role);
  card.setAttribute("aria-modal", "true");
  if (labelledBy) card.setAttribute("aria-labelledby", labelledBy);
  if (describedBy) card.setAttribute("aria-describedby", describedBy);
  overlay = h("div", { class: "dialog-overlay", onClick: (e) => { if (e.target === overlay) close(); } }, card);
  const focusable = () =>
    card.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
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
  openDialog = { close };
  (focusable()[0] || card).focus({ preventScroll: true });
  return close;
}

// A focus-trapped list of keyboard shortcuts. `shortcuts` is an array of
// { keys, description }. Opened by the global "?" handler in app.js.
export function shortcutsDialog(shortcuts) {
  return modal(
    (close) =>
      h(
        "div",
        { class: "dialog shortcuts" },
        h("h2", { id: "sc-title" }, t("Keyboard shortcuts")),
        h(
          "dl",
          { class: "shortcut-list" },
          shortcuts.flatMap((s) => [
            h("dt", {}, h("kbd", {}, s.keys)),
            h("dd", {}, s.description),
          ]),
        ),
        h("div", { class: "dialog-actions" }, h("button", { type: "button", class: "primary", onClick: close }, t("Close"))),
      ),
    { labelledBy: "sc-title" },
  );
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

// Line icons (shapes from Lucide, ISC licence), built with DOM calls so the
// Content-Security-Policy needs no inline markup. Always decorative: pair each with a word.
const ICONS = {
  projects: '<path d="M4 20h16a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.93a2 2 0 0 1-1.66-.9l-.82-1.2A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13c0 1.1.9 2 2 2Z"/><path d="M8 10v4"/><path d="M12 10v2"/><path d="M16 10v6"/>',
  templates: '<rect width="18" height="7" x="3" y="3" rx="1"/><rect width="9" height="7" x="3" y="14" rx="1"/><rect width="5" height="7" x="16" y="14" rx="1"/>',
  overview: '<path d="m12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83Z"/><path d="m22 17.65-9.17 4.16a2 2 0 0 1-1.66 0L2 17.65"/><path d="m22 12.65-9.17 4.16a2 2 0 0 1-1.66 0L2 12.65"/>',
  documents: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 9H8"/><path d="M16 13H8"/><path d="M16 17H8"/>',
  trace: '<path d="M6 3v12"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  questions: '<circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><path d="M12 17h.01"/>',
  knowledge: '<path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/>',
  drs: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="m9 15 2 2 4-4"/>',
  plus: '<path d="M5 12h14"/><path d="M12 5v14"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/>',
  open: '<path d="M7 7h10v10"/><path d="M7 17 17 7"/>',
  next: '<path d="M5 12h14"/><path d="m12 5 7 7-7 7"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/><path d="m9 12 2 2 4-4"/>',
  chevron: '<path d="m6 9 6 6 6-6"/>',
  workflow: '<rect width="8" height="8" x="3" y="3" rx="2"/><path d="M7 11v4a2 2 0 0 0 2 2h4"/><rect width="8" height="8" x="13" y="13" rx="2"/>',
  requirements: '<path d="m3 17 2 2 4-4"/><path d="m3 7 2 2 4-4"/><path d="M13 6h8"/><path d="M13 12h8"/><path d="M13 18h8"/>',
  close: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  signout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
  language: '<path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>',
  theme: '<circle cx="12" cy="12" r="10"/><path d="M12 18a6 6 0 0 0 0-12v12z"/>',
  users: '<path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
  gauge: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
  dashboard: '<rect width="7" height="9" x="3" y="3" rx="1"/><rect width="7" height="5" x="14" y="3" rx="1"/><rect width="7" height="9" x="14" y="12" rx="1"/><rect width="7" height="5" x="3" y="16" rx="1"/>',
  more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
  folder: '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
  file: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M10 13H8"/><path d="M16 17H8"/>',
  sheet: '<path d="M15 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V7Z"/><path d="M14 2v4a2 2 0 0 0 2 2h4"/><path d="M8 13h8"/><path d="M8 17h8"/><path d="M12 11v8"/>',
  dot: '<circle cx="12" cy="12" r="3"/>',
  back: '<path d="m15 18-6-6 6-6"/>',
  diff: '<path d="M12 3v14"/><path d="M5 10h14"/><path d="M5 21h14"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
  audit: '<path d="M12 8v4l3 3"/><path d="M3.05 11a9 9 0 1 1 .5 4m-.5 5v-5h5"/>',
};
const SVG = "http://www.w3.org/2000/svg";
const SHAPE = /<(\w+)([^>]*)\/>/g;
const ATTR = /([\w-]+)="([^"]*)"/g;

export function icon(name, size = 17) {
  const markup = ICONS[name];
  if (!markup || typeof document.createElementNS !== "function") return null;
  const svg = document.createElementNS(SVG, "svg");
  const attrs = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", "stroke-width": "1.8", "stroke-linecap": "round", "stroke-linejoin": "round", "aria-hidden": "true", focusable: "false", class: "icon" };
  for (const [key, value] of Object.entries(attrs)) svg.setAttribute(key, String(value));
  for (const [, tag, rest] of markup.matchAll(SHAPE)) {
    const shape = document.createElementNS(SVG, tag);
    for (const [, key, value] of rest.matchAll(ATTR)) shape.setAttribute(key, value);
    svg.append(shape);
  }
  return svg;
}

// Secondary row actions behind one "more" button, so a table row shows one primary action
// (spec 25 section 4). items: [{ label, onClick, danger }]; null items are skipped.
let menuWatch = false;
export function rowMenu(label, items) {
  const menu = h("details", { class: "row-menu" },
    h("summary", { class: "icon-button", "aria-label": label, title: label }, icon("more", 16)),
    h("div", { class: "account-menu", role: "menu" },
      items.filter(Boolean).map((item) => h("button", {
        type: "button",
        role: "menuitem",
        class: `menu-item${item.danger ? " danger" : ""}`,
        onClick: () => { menu.open = false; item.onClick(); },
      }, item.label)),
    ),
  );
  // Tables scroll, so the list is placed against the viewport instead of inside the table.
  menu.addEventListener("toggle", () => {
    if (!menu.open) return;
    const list = menu.querySelector(".account-menu");
    const box = menu.querySelector("summary").getBoundingClientRect();
    list.style.setProperty("top", `${Math.round(box.bottom + 4)}px`);
    list.style.setProperty("right", `${Math.round(window.innerWidth - box.right)}px`);
  });
  const closeOnScroll = () => { menu.open = false; };
  menu.addEventListener("toggle", () => {
    if (menu.open) window.addEventListener("scroll", closeOnScroll, { capture: true, once: true });
  });
  menu.addEventListener("keydown", (event) => { if (event.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus(); } });
  if (!menuWatch && typeof document.addEventListener === "function") {
    menuWatch = true;
    document.addEventListener("click", (event) => {
      for (const open of document.querySelectorAll("details.row-menu[open]")) if (!open.contains(event.target)) open.open = false;
    });
  }
  return menu;
}

// Up to two letters that stand for a project or a person.
export function monogram(text) {
  const words = String(text ?? "").replace(/[^\p{L}\p{N}]+/gu, " ").trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

// Usage windows (spec 23): the 5-hour session and the weekly window, as in a Claude plan.
const WINDOW_NAMES = { session: N_("5-hour limit"), weekly: N_("Weekly limit") };

export function windowName(window) {
  return t(WINDOW_NAMES[window] ?? window);
}

export function tokens(n) {
  return new Intl.NumberFormat(locale()).format(Number(n ?? 0));
}

// The sentence shown when a limit stops an action (a 429 detail or a reached window).
export function usageLimitText(w) {
  if (!w.resets_at) {
    return t("Your {window} is {limit} tokens. Ask an administrator to raise it.", { window: windowName(w.window), limit: tokens(w.limit) });
  }
  return t("You have reached your {window} ({used} of {limit} tokens). It resets at {time}.", {
    window: windowName(w.window), used: tokens(w.used), limit: tokens(w.limit), time: fmtTime(w.resets_at),
  });
}

// Which banner the shell shows: the first reached window, else the fullest from 80 %.
export function usageNotice(windows) {
  const list = Array.isArray(windows) ? windows : [];
  const reached = list.find((w) => w.reached);
  if (reached) return { level: "bad", text: usageLimitText(reached) };
  const near = list.filter((w) => w.percent !== null && w.percent >= 80).sort((a, b) => b.percent - a.percent)[0];
  if (!near) return null;
  return {
    level: "warn",
    text: t("You have used {percent}% of your {window}. It resets at {time}.", { percent: near.percent, window: windowName(near.window), time: fmtTime(near.resets_at) }),
  };
}

// One bar per window: used against the limit, with the reset time.
export function usageMeter(w, { compact = false } = {}) {
  const limited = w.limit !== null && w.limit !== undefined;
  const percent = limited ? (w.percent ?? 0) : 0;
  const tone = w.reached ? "bad" : percent >= 80 ? "warn" : "ok";
  const amount = limited
    ? t("{used} of {limit} tokens", { used: tokens(w.used), limit: tokens(w.limit) })
    : t("{used} tokens · no limit", { used: tokens(w.used) });
  const reset = w.resets_at ? t("Resets {time}", { time: fmtTime(w.resets_at) }) : t("Starts with your next model call");
  return h("div", { class: `usage-window ${tone}${compact ? " compact" : ""}` },
    h("div", { class: "usage-head" }, h("strong", {}, windowName(w.window)), h("span", { class: "usage-amount" }, amount)),
    h("progress", { class: `meter usage-bar ${tone}`, value: String(percent), max: "100", "aria-label": t("{window}: {percent}% used", { window: windowName(w.window), percent }) }),
    compact ? null : h("p", { class: "hint" }, limited ? t("{percent}% used", { percent }) + " · " + reset : reset),
  );
}
