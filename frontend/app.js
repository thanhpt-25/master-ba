// Shell and hash router. Views live in ./views and are loaded on demand.

import { api, ApiError } from "./api.js";
import { clear, errorBox, h, shortcutsDialog, skeleton } from "./dom.js";
import { lang, loadLang, N_, setLang, t } from "./i18n.js";

// Shortcuts shown by the "?" help overlay. Views that add their own entries
// (e.g. Overview's "P") describe them here so the list stays in one place.
const SHORTCUTS = [
  { keys: "?", description: N_("Show this keyboard shortcut help") },
  { keys: "P", description: N_("Pause or resume live polling (Overview, Decision Records)") },
  { keys: "Esc", description: N_("Close an open dialog") },
];

const app = document.getElementById("app");
const state = { me: null, cleanup: null, seq: 0 };
const THEMES = ["system", "light", "dark"];
let theme = "system";
try {
  const savedTheme = localStorage.getItem("masterba-theme");
  if (THEMES.includes(savedTheme)) theme = savedTheme;
} catch { /* Storage can be disabled; keep the system theme for this session. */ }

function applyTheme() {
  if (theme === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.dataset.theme = theme;
  try { localStorage.setItem("masterba-theme", theme); } catch { /* Theme still applies for this session. */ }
}

const THEME_NAMES = { system: N_("System"), light: N_("Light"), dark: N_("Dark") };

function themeLabel() {
  return t("Theme: {name}", { name: t(THEME_NAMES[theme]) });
}

function cycleTheme() {
  theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  applyTheme();
  const button = document.getElementById("theme-toggle");
  if (button) {
    button.textContent = themeLabel();
    button.setAttribute("aria-label", t("Color theme: {name}. Activate to change theme.", { name: t(THEME_NAMES[theme]) }));
  }
}

// The other language, named in its own language so a reader of either can find it.
function switchLanguage() {
  setLang(lang() === "ja" ? "en" : "ja", state.me?.name);
  route();
}
applyTheme();
loadLang();

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
  ["overview", N_("Overview")],
  ["documents", N_("Documents")],
  ["questions", N_("Questions")],
  ["drs", N_("Decision Records")],
  ["trace", N_("Traceability")],
  ["activity", N_("Activity")],
  ["knowledge", N_("Knowledge")],
];

const PAGE_META = {
  login: [N_("Sign in"), N_("Sign in to your MasterBA project workspace.")],
  projects: [N_("Projects"), N_("Manage MasterBA projects, requirements, documents, and decisions.")],
  overview: [N_("Project overview"), N_("Follow requirements, document stages, reviews, and decisions in the MasterBA V-model.")],
  documents: [N_("Documents"), N_("Browse versioned project documents and compare changes.")],
  trace: [N_("Traceability"), N_("Explore requirement, design, and test trace links.")],
  activity: [N_("Activity"), N_("Review project tasks, team activity, and audit history.")],
  questions: [N_("Customer questions"), N_("Track open questions and confirmed customer answers.")],
  knowledge: [N_("Knowledge base"), N_("Manage reference sources used by MasterBA writers.")],
  drs: [N_("Decision records"), N_("Review project decisions, impacts, and change propagation.")],
  templates: [N_("Templates"), N_("Manage company document template mappings.")],
};
const ROLES = { viewer: N_("Viewer"), approver: N_("Approver"), admin: N_("Admin") };

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
        { class: "tabs", "aria-label": t("Project sections") },
        TABS.map(([key, label]) =>
          h("a", { href: `#/p/${params.pid}/${key}`, "aria-current": params.name === key ? "page" : null }, t(label)),
        ),
      )
    : null;
  return [
    h("div", { class: "app-shell" },
      h("aside", { class: "sidebar" },
        h("a", { class: "brand", href: "#/projects" }, h("span", { class: "seal", "aria-hidden": "true" }, "要"), "MasterBA", h("span", { class: "brand-dot", "aria-hidden": "true" }, ".")),
        h("p", { class: "sidebar-label" }, t("Workspace")),
        h("nav", { class: "workspace-nav", "aria-label": t("Workspace") },
          h("a", { href: "#/projects", "aria-current": params.pid ? null : params.name === "projects" ? "page" : null }, h("span", { "aria-hidden": "true" }, "▦"), t("Projects")),
          state.me.role === "admin" ? h("a", { href: "#/templates", "aria-current": params.name === "templates" ? "page" : null }, h("span", { "aria-hidden": "true" }, "▤"), t("Templates")) : null,
        ),
        h("div", { class: "sidebar-foot" }, h("span", { class: "sidebar-live", "aria-hidden": "true" }), t("V-model workspace")),
      ),
      h("div", { class: "workspace" },
        h("header", { class: "top" },
          h("span", { class: "crumb" }, params.pid ? [h("a", { href: "#/projects" }, t("Projects")), h("span", { "aria-hidden": "true" }, "/"), h("code", {}, params.pid)] : `${t("Workspace")} / ${t("Projects")}`),
          h("div", { class: "who" },
            h("span", { class: "avatar", "aria-hidden": "true" }, state.me.name.slice(0, 1).toUpperCase()),
            h("span", { class: "user-name" }, state.me.name, h("span", { class: "role" }, t(ROLES[state.me.role] ?? state.me.role))),
            h("button", { id: "lang-toggle", class: "link lang-toggle", type: "button", lang: lang() === "ja" ? "en" : "ja", onClick: switchLanguage }, lang() === "ja" ? "English" : "日本語"),
            h("button", { id: "theme-toggle", class: "link theme-toggle", type: "button", onClick: cycleTheme, "aria-label": t("Color theme: {name}. Activate to change theme.", { name: t(THEME_NAMES[theme]) }) }, themeLabel()),
            h("button", { class: "link", onClick: logout }, t("Sign out")),
          ),
        ),
        nav,
        h("main", { id: "main", tabindex: "-1" }, content),
      ),
    ),
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
      loadLang(state.me.name);
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
  const [pageTitle, description] = (PAGE_META[params.name] ?? PAGE_META.projects).map((text) => t(text));
  document.title = `${params.pid ? `${pageTitle} · ${params.pid}` : pageTitle} | MasterBA`;
  const metaDescription = document.querySelector('meta[name="description"]');
  if (metaDescription) metaDescription.content = description;
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
      h("h1", {}, t("Something went wrong")),
      h("p", {}, t("The screen hit an unexpected error. Your work on the server is unaffected; reloading usually clears it.")),
      error?.message ? h("p", { class: "fatal-detail" }, error.message) : null,
      h("div", { class: "fatal-actions" },
        h("button", { class: "primary", type: "button", onClick: () => location.reload() }, t("Reload")),
        h("button", { type: "button", onClick: () => { boundaryShown = false; panel.remove(); route(); } }, t("Try to continue")),
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
  shortcutsDialog(SHORTCUTS.map((s) => ({ keys: s.keys, description: t(s.description) })));
});

route();
