// Shell and hash router. Views live in ./views and are loaded on demand.

import { api, ApiError } from "./api.js";
import { clear, errorBox, h, skeleton } from "./dom.js";

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

function parse() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "p" && parts[1]) {
    return { name: parts[2] ?? "overview", pid: parts[1], rest: parts.slice(3) };
  }
  return { name: parts[0] ?? "projects", pid: null, rest: [] };
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
  await api.post("/logout");
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
route();
