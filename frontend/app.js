// Shell and hash router. Views live in ./views and are loaded on demand.

import { api, ApiError } from "./api.js";
import { append, clear, errorBox, h, icon, shortcutsDialog, skeleton, usageNotice } from "./dom.js";
import { lang, loadLang, N_, setLang, t } from "./i18n.js";
import { openPalette, railLabel } from "./palette.js";

// Shortcuts shown by the "?" help overlay. Views that add their own entries
// (e.g. Overview's "P") describe them here so the list stays in one place.
const SHORTCUTS = [
  { keys: "?", description: N_("Show this keyboard shortcut help") },
  { keys: "⌘K / Ctrl+K", description: N_("Search projects, pages and actions") },
  { keys: "P", description: N_("Pause or resume live polling (Overview, Decision Records)") },
  { keys: "Esc", description: N_("Close an open dialog") },
];

const app = document.getElementById("app");
const state = { me: null, cleanup: null, seq: 0, projects: null, params: null };
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
    button.querySelector("span").textContent = themeLabel();
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
  usage: () => import("./views/usage.js"),
  users: () => import("./views/users.js"),
  admin: () => import("./views/admin.js"),
  "admin-projects": () => import("./views/admin-projects.js"),
  audit: () => import("./views/audit.js"),
  members: () => import("./views/members.js"),
};

const TABS = [
  ["overview", N_("Overview")],
  ["documents", N_("Documents")],
  ["questions", N_("Questions")],
  ["drs", N_("Decision Records")],
  ["trace", N_("Traceability")],
  ["activity", N_("Activity")],
  ["knowledge", N_("Knowledge")],
  ["members", N_("Members")],
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
  usage: [N_("Usage"), N_("See how many model tokens you used and when your limits reset.")],
  users: [N_("Users"), N_("Manage accounts, roles and token limits.")],
  members: [N_("Members"), N_("Choose who can open this project.")],
  admin: [N_("Admin dashboard"), N_("Usage, cost, delivery and security across every user and project.")],
  "admin-projects": [N_("All projects"), N_("Every project on this server with its owner, members, phases and model use.")],
  audit: [N_("Audit log"), N_("Sign-ins and every change to accounts, limits, prices and sharing.")],
};
const WORKSPACE_PAGES = { projects: N_("Projects"), templates: N_("Templates"), usage: N_("Usage"), users: N_("Users"), admin: N_("Admin dashboard"), "admin-projects": N_("All projects"), audit: N_("Audit log") };
const ADMIN_PAGES = ["admin", "users", "admin-projects", "audit", "templates"];
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

const TAB_ICONS = { overview: "overview", documents: "documents", questions: "questions", drs: "drs", trace: "trace", activity: "activity", knowledge: "knowledge", members: "users" };

function navLink(href, iconName, label, current) {
  return h("a", { href, "aria-current": current ? "page" : null }, icon(iconName), h("span", {}, label));
}

// The account menu (name, role, language, theme, sign out) behind one chip, as in the refresh design.
function accountMenu() {
  const menu = h("details", { class: "account" },
    h("summary", { "aria-label": t("Account and display settings") },
      h("span", { class: "avatar", "aria-hidden": "true" }, state.me.name.slice(0, 1).toUpperCase()),
      h("span", { class: "user-name" }, state.me.name, h("span", { class: "role" }, t(ROLES[state.me.role] ?? state.me.role))),
      icon("chevron", 14),
    ),
    h("div", { class: "account-menu" },
      h("a", { class: "menu-item", href: "#/usage" }, icon("gauge", 16), t("Usage")),
      state.me.role === "admin" ? h("a", { class: "menu-item", href: "#/admin" }, icon("dashboard", 16), t("Admin dashboard")) : null,
      state.me.role === "admin" ? h("a", { class: "menu-item", href: "#/users" }, icon("users", 16), t("Users")) : null,
      h("button", { id: "lang-toggle", class: "menu-item lang-toggle", type: "button", lang: lang() === "ja" ? "en" : "ja", onClick: switchLanguage }, icon("language", 16), lang() === "ja" ? "English" : "日本語"),
      h("button", { id: "theme-toggle", class: "menu-item theme-toggle", type: "button", onClick: cycleTheme, "aria-label": t("Color theme: {name}. Activate to change theme.", { name: t(THEME_NAMES[theme]) }) }, icon("theme", 16), h("span", {}, themeLabel())),
      h("div", { class: "menu-sep", role: "separator" }),
      h("button", { class: "menu-item", type: "button", onClick: logout }, icon("signout", 16), t("Sign out")),
    ),
  );
  // Close on outside click and Escape, like a native menu.
  const onDoc = (event) => { if (menu.open && !menu.contains(event.target)) menu.open = false; };
  document.addEventListener("click", onDoc);
  menu.addEventListener("keydown", (event) => { if (event.key === "Escape" && menu.open) { menu.open = false; menu.querySelector("summary").focus(); } });
  shellCleanup = () => document.removeEventListener("click", onDoc);
  return menu;
}
let shellCleanup = null;

// The projects this user can open, read once per session for the rail and the palette.
async function loadProjects(force = false) {
  if (state.projects && !force) return state.projects;
  try {
    state.projects = await api.get("/projects");
  } catch {
    state.projects = state.projects ?? [];
  }
  return state.projects;
}

function fillRail(rail, current) {
  const host = rail.querySelector(".rail-projects");
  if (!host) return;
  clear(host);
  append(host, (state.projects ?? []).map((project) => {
    const pid = project.project_id;
    return h("a", {
      class: "rail-project",
      href: `#/p/${encodeURIComponent(pid)}/overview`,
      title: pid,
      "aria-label": pid,
      "aria-current": pid === current ? "page" : null,
    }, railLabel(pid));
  }));
}

// Open customer questions beside 顧客確認事項, filled after the first paint.
async function fillCounts(sidebar, pid) {
  try {
    const overview = await api.get(`/projects/${encodeURIComponent(pid)}`);
    const link = sidebar.querySelector('a[data-tab="questions"]');
    const n = overview?.counts?.open_questions ?? 0;
    if (link && n > 0 && !link.querySelector(".nav-count")) {
      link.append(h("span", { class: "nav-count", "aria-label": t("{n} open customer question(s)", { n }) }, String(n)));
    }
    const company = sidebar.querySelector(".project-switch-sub");
    if (company && overview?.project?.company_id) company.textContent = overview.project.company_id;
  } catch { /* The count is a convenience; the page itself reports errors. */ }
}

// Everything the palette can jump to or do, for this user on this page.
function paletteCommands() {
  const params = state.params ?? { name: "projects", pid: null };
  const commands = [];
  const page = t("Pages");
  if (params.pid) {
    for (const [key, label] of TABS) {
      commands.push({ id: `tab:${key}`, group: params.pid, label: t(label), keywords: [params.pid], icon: TAB_ICONS[key], run: () => go(`#/p/${params.pid}/${key}`) });
    }
  }
  for (const project of state.projects ?? []) {
    const pid = project.project_id;
    commands.push({ id: `project:${pid}`, group: t("Projects"), label: pid, hint: project.company_id, keywords: [project.owner ?? ""], icon: "projects", run: () => go(`#/p/${encodeURIComponent(pid)}/overview`) });
  }
  commands.push(
    { id: "page:projects", group: page, label: t("Projects"), icon: "projects", run: () => go("#/projects") },
    { id: "page:usage", group: page, label: t("Usage"), icon: "gauge", run: () => go("#/usage") },
  );
  if (state.me?.role === "admin") {
    commands.push(
      { id: "page:admin", group: t("Administration"), label: t("Admin dashboard"), icon: "dashboard", run: () => go("#/admin") },
      { id: "page:users", group: t("Administration"), label: t("Users"), icon: "users", run: () => go("#/users") },
      { id: "page:admin-projects", group: t("Administration"), label: t("All projects"), icon: "projects", run: () => go("#/admin-projects") },
      { id: "page:audit", group: t("Administration"), label: t("Audit log"), icon: "audit", run: () => go("#/audit") },
      { id: "page:templates", group: t("Administration"), label: t("Templates"), icon: "templates", run: () => go("#/templates") },
    );
  }
  const actions = t("Actions");
  commands.push(
    { id: "action:theme", group: actions, label: t("Change colour theme"), hint: themeLabel(), icon: "theme", run: cycleTheme },
    { id: "action:lang", group: actions, label: lang() === "ja" ? "English" : "日本語", keywords: ["language", "言語"], icon: "language", run: switchLanguage },
    { id: "action:shortcuts", group: actions, label: t("Keyboard shortcuts"), icon: "more", run: showShortcuts },
    { id: "action:signout", group: actions, label: t("Sign out"), icon: "signout", run: logout },
  );
  return commands;
}

async function showPalette() {
  if (!state.me) return;
  await loadProjects();
  openPalette(paletteCommands());
}

function showShortcuts() {
  shortcutsDialog(SHORTCUTS.map((s) => ({ keys: s.keys, description: t(s.description) })));
}

function shell(params, content) {
  if (shellCleanup) { shellCleanup(); shellCleanup = null; }
  state.params = params;
  const section = params.pid ? TABS.find(([key]) => key === params.name) : null;
  const crumbs = [];
  if (params.pid) {
    crumbs.push(h("a", { href: "#/projects" }, t("Projects")), h("span", { class: "crumb-slash", "aria-hidden": "true" }, "/"));
    if (section && section[0] !== "overview") {
      crumbs.push(h("a", { href: `#/p/${params.pid}/overview` }, params.pid), h("span", { class: "crumb-slash", "aria-hidden": "true" }, "/"), h("span", { class: "crumb-current", "aria-current": "page" }, t(section[1])));
    } else {
      crumbs.push(h("span", { class: "crumb-current", "aria-current": "page" }, params.pid));
    }
  } else {
    if (ADMIN_PAGES.includes(params.name)) crumbs.push(h("span", {}, t("Administration")), h("span", { class: "crumb-slash", "aria-hidden": "true" }, "/"));
    crumbs.push(h("span", { class: "crumb-current", "aria-current": "page" }, t(WORKSPACE_PAGES[params.name] ?? WORKSPACE_PAGES.projects)));
  }
  const nav = params.pid
    ? h(
        "nav",
        { class: "tabs", "aria-label": t("Project sections") },
        TABS.map(([key, label]) =>
          h("a", { href: `#/p/${params.pid}/${key}`, "aria-current": params.name === key ? "page" : null }, t(label)),
        ),
      )
    : null;
  const isAdmin = state.me.role === "admin";
  const inAdmin = !params.pid && ADMIN_PAGES.includes(params.name);
  // The rail: brand, one square per project, and the way to the project list (spec 26 section 2).
  const rail = h("nav", { class: "rail", "aria-label": t("Switch project") },
    h("a", { class: "rail-brand", href: "#/projects", "aria-label": t("MasterBA, go to projects") }, h("span", { class: "seal", "aria-hidden": "true" }, "要")),
    h("div", { class: "rail-projects" }),
    h("a", { class: "rail-add", href: "#/projects", title: t("All projects"), "aria-label": t("All projects") }, icon("plus", 16)),
  );
  const sidebar = h("aside", { class: "sidebar" },
    h("a", { class: "brand", href: "#/projects", "aria-label": t("MasterBA, go to projects") }, h("span", { class: "seal", "aria-hidden": "true" }, "要"), h("span", {}, "MasterBA")),
    // Inside a project its sections come first, so they are never below the fold.
    params.pid
      ? [
          h("a", { class: "project-switch", href: "#/projects", title: t("Switch project") },
            h("span", { class: "project-mark", "aria-hidden": "true" }, railLabel(params.pid)),
            h("span", { class: "project-switch-text" }, h("span", { class: "project-switch-id" }, params.pid), h("span", { class: "project-switch-sub" }, t("Switch project"))),
            icon("chevron", 14),
          ),
          h("nav", { class: "workspace-nav project-nav", "aria-label": t("Project navigation") },
            TABS.map(([key, label]) => {
              const link = navLink(`#/p/${params.pid}/${key}`, TAB_ICONS[key], t(label), params.name === key);
              link.dataset.tab = key;
              return link;
            }),
          ),
        ]
      : null,
    h("p", { class: "sidebar-label" }, t("Workspace")),
    h("nav", { class: "workspace-nav", "aria-label": t("Workspace") },
      navLink("#/projects", "projects", t("Projects"), !params.pid && params.name === "projects"),
      navLink("#/usage", "gauge", t("Usage"), params.name === "usage"),
    ),
    isAdmin
      ? h("details", { class: "admin-group", open: inAdmin || !params.pid },
          h("summary", {}, h("span", {}, t("Administration")), icon("chevron", 14)),
          h("nav", { class: "workspace-nav admin-nav", "aria-label": t("Administration") },
            navLink("#/admin", "dashboard", t("Admin dashboard"), !params.pid && params.name === "admin"),
            navLink("#/users", "users", t("Users"), params.name === "users"),
            navLink("#/admin-projects", "projects", t("All projects"), params.name === "admin-projects"),
            navLink("#/audit", "audit", t("Audit log"), params.name === "audit"),
            navLink("#/templates", "templates", t("Templates"), params.name === "templates"),
          ),
        )
      : null,
  );
  loadProjects(params.name === "projects").then(() => fillRail(rail, params.pid));
  if (params.pid) fillCounts(sidebar, params.pid);
  const search = h("button", { class: "top-search", type: "button", onClick: showPalette, "aria-keyshortcuts": "Meta+K Control+K" },
    icon("search", 15), h("span", {}, t("Search or run a command…")), h("kbd", {}, isMac() ? "⌘K" : "Ctrl K"));
  return [
    h("div", { class: "app-shell" },
      rail,
      sidebar,
      h("div", { class: "workspace" },
        h("header", { class: "top" },
          h("nav", { class: "crumb", "aria-label": t("Breadcrumb") }, crumbs),
          search,
          h("div", { class: "who" }, accountMenu()),
        ),
        nav,
        usageBanner(),
        h("main", { id: "main", tabindex: "-1" }, content),
      ),
    ),
  ];
}

const isMac = () => /Mac|iPhone|iPad/.test(globalThis.navigator?.platform ?? "");

// From 80 % of a usage window, and stronger once a limit is reached (spec 23 section 8).
function usageBanner() {
  const notice = usageNotice(state.me?.usage);
  if (!notice) return null;
  return h("div", { class: `usage-banner ${notice.level}`, role: notice.level === "bad" ? "alert" : "status" },
    icon("gauge", 16), h("span", {}, notice.text), h("a", { href: "#/usage" }, t("See usage")),
  );
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
  const known = Boolean(state.me);
  if (params.name !== "login" || !known) {
    // Read again on every route so the role and the usage banner stay current.
    try {
      state.me = await api.get("/me");
      if (!known) { loadLang(state.me.name); state.projects = null; }
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
      state.me = null;
    }
  }
  if (!state.me && params.name !== "login") return go("#/login");
  if (state.me && params.name === "login") return go("#/projects");
  const main = h("div", { class: "view" });
  clear(app);
  if (params.name === "login") {
    app.append(main);
  } else {
    append(app, shell(params, main));
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
      // Inside a project the project role counts (spec 23 section 2), not the global role.
      let me = state.me;
      if (params.pid) {
        try {
          const access = await api.get(`/projects/${encodeURIComponent(params.pid)}/access`);
          me = { ...state.me, role: access.my_role, globalRole: state.me.role };
        } catch (error) {
          if (!(error instanceof ApiError) || error.status !== 404) throw error;
          if (seq !== state.seq) return;
          clear(main).append(errorBox(t("This project does not exist or is not shared with you. Ask its owner to add you.")));
          return;
        }
        if (seq !== state.seq) return;
      }
      const context = { main, params, me, api, go, toast };
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
  showShortcuts();
});

// ⌘K / Ctrl+K opens the command palette from anywhere, even while typing in a field.
window.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() !== "k" || !(event.metaKey || event.ctrlKey) || event.altKey || event.shiftKey) return;
  if (!state.me) return;
  event.preventDefault();
  showPalette();
});

route();
