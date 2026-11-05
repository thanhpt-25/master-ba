// Shell and hash router. Views live in ./views and are loaded on demand.

import { api, ApiError } from "./api.js";
import { clear, errorBox, h, shortcutsDialog, skeleton } from "./dom.js";

// Shortcuts shown by the "?" help overlay. Views that add their own entries
// (e.g. Overview's "P") describe them here so the list stays in one place.
const SHORTCUTS = [
  { keys: "?", description: "Show this keyboard shortcut help" },
  { keys: "P", description: "Pause or resume live polling (Overview, Decision Records)" },
  { keys: "Esc", description: "Close an open dialog" },
];

const app = document.getElementById("app");
const state = { me: null, cleanup: null, seq: 0 };

const VIEWS = {
  login: () => import("./views/login.js"),
  projects: () => import("./views/projects.js"),
  overview: () => import("./views/overview.js"),
  documents: () => import("./views/documents.js"),
  trace: () => import("./views/trace.js"),
  activity: () => import("./views/activity.js"),
  drs: () => import("./views/drs.js"),
  questions: () => import("./views/questions.js"),
  knowledge: () => import("./views/knowledge.js"),
  templates: () => import("./views/templates.js"),
};

const TABS = [
  ["overview", "Overview"],
  ["documents", "Documents"],
  ["trace", "Traceability"],
  ["activity", "Activity"],
  ["questions", "Questions"],
  ["knowledge", "Knowledge"],
  ["drs", "Decision Records"],
];

export function go(hash) {
  if (location.hash === hash) route();
  else location.hash = hash;
}

export function toast(message, kind = "info") {
  const region = document.getElementById("toasts");
  const note = h("p", { class: `toast ${kind}`, role: kind === "error" ? "alert" : "status" }, message);
  region.append(note);
  setTimeout(() => note.remove(), kind === "error" ? 9000 : 4000);
}

// Exported and hash-parameterised so it can be unit-tested without booting the
// router. route() calls parseHash(location.hash).
export function parseHash(hash) {
  const parts = String(hash).replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "p" && parts[1]) {
    return { name: parts[2] ?? "overview", pid: parts[1], rest: parts.slice(3) };
  }
  return { name: parts[0] ?? "projects", pid: null, rest: [] };
}

function parse() {
  return parseHash(location.hash);
}

function shell(params, content) {
  const nav = params.pid
    ? h(
        "nav",
        { class: "tabs", "aria-label": "Project sections" },
        TABS.map(([key, label]) =>
          h("a", { href: `#/p/${params.pid}/${key}`, "aria-current": params.name === key ? "page" : null }, label),
        ),
      )
    : null;
  return [
    h(
      "header",
      { class: "top" },
      h("a", { class: "brand", href: "#/projects" }, h("span", { class: "seal", "aria-hidden": "true" }, "要"), "MasterBA"),
      state.me.role === "admin" ? h("a", { class: "toplink", href: "#/templates" }, "Templates") : null,
      params.pid ? h("span", { class: "crumb" }, h("a", { href: "#/projects" }, "Projects"), " / ", h("code", {}, params.pid)) : null,
      h(
        "div",
        { class: "who" },
        h("span", {}, state.me.name, " ", h("span", { class: "role" }, state.me.role)),
        h("button", { class: "link", onClick: logout }, "Sign out"),
      ),
    ),
    nav,
    h("main", { id: "main", tabindex: "-1" }, content),
  ];
}

async function logout() {
  try {
    await api.post("/logout");
  } catch (error) {
    toast(error.message, "error");
    return;
  }
  state.me = null;
  go("#/login");
}

async function route() {
  if (state.cleanup) {
    state.cleanup();
    state.cleanup = null;
  }
  const params = parse();
  if (!state.me) {
    try {
      state.me = await api.get("/me");
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
    }
  }
  if (!state.me && params.name !== "login") return go("#/login");
  if (state.me && params.name === "login") return go("#/projects");
  const main = h("div", { class: "view" });
  clear(app);
  if (params.name === "login") {
    app.append(main);
  } else {
    app.append(...shell(params, main).filter(Boolean));
  }
  document.title = `MasterBA — ${params.name}`;
  document.getElementById("main")?.focus({ preventScroll: true });

  // Show a skeleton while the view module loads and runs its first fetch, so the
  // main area is never blank on a slow call. The view replaces it on first draw.
  if (params.name !== "login") main.append(skeleton(5));

  const run = async () => {
    const seq = ++state.seq;
    try {
      const module = await (VIEWS[params.name] ?? VIEWS.projects)();
      if (seq !== state.seq) return; // navigated away while loading
      const context = { main, params, me: state.me, api, go, toast };
      const cleanup = await module.render(context);
      if (typeof cleanup !== "function") return;
      if (seq !== state.seq) cleanup(); // a newer view owns state.cleanup now
      else state.cleanup = cleanup;
    } catch (error) {
      if (seq !== state.seq) return;
      if (error instanceof ApiError && error.status === 401) {
        state.me = null;
        return go("#/login");
      }
      clear(main).append(errorBox(error.message, run));
    }
  };
  await run();
}

window.addEventListener("hashchange", route);
window.addEventListener("masterba:unauthorized", () => {
  if (!state.me) return;
  state.me = null;
  go("#/login");
});

// Last-resort boundary for errors that escape route()'s own try/catch — an
// uncaught throw in a timer, an event callback, or a rejected promise with no
// handler. It shows a recoverable panel instead of leaving a blank or frozen
// screen. Routine 401s are handled elsewhere and never reach here.
let boundaryShown = false;
function fatalBoundary(error) {
  if (error instanceof ApiError && error.status === 401) {
    state.me = null;
    go("#/login");
    return;
  }
  if (boundaryShown) return;
  boundaryShown = true;
  const panel = h(
    "div",
    { class: "fatal", role: "alert" },
    h("div", { class: "fatal-card" },
      h("h1", {}, "Something went wrong"),
      h("p", {}, "The screen hit an unexpected error. Your work on the server is unaffected — reloading usually clears it."),
      error?.message ? h("p", { class: "fatal-detail" }, error.message) : null,
      h("div", { class: "fatal-actions" },
        h("button", { class: "primary", type: "button", onClick: () => location.reload() }, "Reload"),
        h("button", { type: "button", onClick: () => { boundaryShown = false; panel.remove(); route(); } }, "Try to continue"),
      ),
    ),
  );
  document.body.append(panel);
}
window.addEventListener("error", (event) => { if (event.error) fatalBoundary(event.error); });
window.addEventListener("unhandledrejection", (event) => fatalBoundary(event.reason));

// "?" opens the keyboard shortcut help. Skip while typing in a field or with a
// modifier held; skip on the login page where no shortcuts apply.
window.addEventListener("keydown", (event) => {
  if (event.key !== "?") return;
  if (event.ctrlKey || event.metaKey || event.altKey) return;
  const el = document.activeElement;
  if (el && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName))) return;
  if (!state.me) return;
  event.preventDefault();
  shortcutsDialog(SHORTCUTS);
});

route();
