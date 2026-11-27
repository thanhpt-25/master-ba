import { badge, clear, empty, field, h, icon, modal, monogram } from "../dom.js";
import { t } from "../i18n.js";
import { phaseTitle, workflowSteps } from "./journey.js";

// Where a project stands, from its overview: one status word, the current phase and a progress share.
export function projectSummary(overview) {
  if (!overview) return null;
  const flow = workflowSteps(overview.stages, overview.project.review_gates);
  const states = flow.steps.map((step) => step.state);
  const finished = states.filter((s) => s === "approved" || s === "done").length;
  const halfway = states.filter((s) => ["in_review", "running", "escalated", "waiting_for_input"].includes(s)).length;
  let status = "in_progress";
  if (states.includes("running")) status = "running";
  else if (states.includes("in_review")) status = "in_review";
  else if (states.includes("waiting_for_input")) status = "waiting_for_input";
  else if (states.includes("escalated")) status = "escalated";
  else if (finished === states.length) status = "done";
  else if (finished === 0) status = "not_started";
  return {
    status,
    stage: flow.current ? phaseTitle(flow.current) : t("All phases complete"),
    progress: Math.round(((finished + halfway / 2) / states.length) * 100),
    documents: overview.stages.reduce((sum, stage) => sum + stage.documents.length, 0),
    reviews: states.filter((s) => s === "in_review").length,
    questions: overview.counts?.open_questions ?? 0,
  };
}

function projectMark(project) {
  return project.company_id && project.company_id !== "default"
    ? monogram(project.company_id)
    : String(project.project_id).replace(/\D/g, "").slice(-2) || monogram(project.project_id);
}

function projectCard(project, summary) {
  return h("li", {}, h("a", { class: "project-card", href: `#/p/${project.project_id}/overview` },
    h("span", { class: "project-card-top" },
      h("span", { class: "monogram", "aria-hidden": "true" }, projectMark(project)),
      summary ? badge(summary.status) : null,
      h("span", { class: "project-card-open" }, icon("open", 16)),
    ),
    h("span", { class: "project-card-title" },
      h("code", { class: "project-id" }, project.project_id),
      h("strong", {}, project.company_id === "default" ? t("Standard templates") : project.company_id),
    ),
    summary
      ? [
          h("span", { class: "project-stage" }, h("span", {}, t("Current stage")), h("span", { class: "project-stage-name" }, summary.stage, icon("next", 13))),
          h("progress", { class: "meter", value: String(summary.progress), max: "100", "aria-label": t("{n}% complete", { n: summary.progress }) }),
        ]
      : h("span", { class: "project-stage muted" }, t("Status not available")),
    h("span", { class: "project-card-bottom" },
      h("span", {}, icon("documents", 14), summary ? t("{n} documents", { n: summary.documents }) : "–"),
      h("span", {}, icon("language", 14), project.document_language === "ja" ? t("Documents in Japanese") : t("Documents in English")),
      project.owner ? h("span", { class: "project-owner" }, icon("users", 14), project.my_role === "admin" ? t("Owner: {name}", { name: project.owner }) : t("Shared by {name}", { name: project.owner })) : null,
    ),
  ));
}

function metric(iconName, tone, label, value, note) {
  return h("div", { class: "metric" },
    h("span", { class: `metric-icon ${tone}` }, icon(iconName, 17)),
    h("span", { class: "metric-body" }, h("span", { class: "metric-label" }, label), h("strong", {}, String(value).padStart(2, "0"))),
    h("span", { class: "metric-note" }, note),
  );
}

export async function render({ main, api, me, go, toast }) {
  // The route shell shows a skeleton until this resolves.
  const projects = await api.get("/projects");
  const settled = await Promise.allSettled(projects.map((p) => api.get(`/projects/${p.project_id}`)));
  const summaries = new Map(projects.map((p, i) => [p.project_id, settled[i].status === "fulfilled" ? projectSummary(settled[i].value) : null]));
  const known = [...summaries.values()].filter(Boolean);
  let search = "";
  let languageFilter = "all";
  const listHost = h("div", {});
  const count = h("span", { class: "project-count", role: "status" });
  const searchBox = h("label", { class: "project-search" },
    h("span", { class: "sr-only" }, t("Find a project by ID or company")),
    icon("search", 17),
    h("input", { type: "search", placeholder: t("Find a project by ID or company"), onInput: (event) => { search = event.target.value; drawList(); } }),
  );
  const filters = h("div", { class: "project-filters", role: "group", "aria-label": t("Filter projects by document language") },
    ...[["all", t("All languages")], ["en", t("English")], ["ja", t("Japanese")]].map(([value, label]) =>
      h("button", { type: "button", "aria-pressed": value === languageFilter ? "true" : "false", onClick: () => { languageFilter = value; for (const button of filters.children) button.setAttribute("aria-pressed", button.textContent === label ? "true" : "false"); drawList(); } }, label),
    ),
  );
  // Approvers and admins create projects and own them (spec 23 section 2).
  const canCreate = me.role !== "viewer";
  const openCreate = () => createDialog({ api, go, toast });
  function drawList() {
    const term = search.trim().toLocaleLowerCase();
    const visible = projects.filter((project) =>
      (!term || `${project.project_id} ${project.company_id}`.toLocaleLowerCase().includes(term)) &&
      (languageFilter === "all" || project.document_language === languageFilter),
    );
    count.textContent = t("{shown} of {total} projects", { shown: visible.length, total: projects.length });
    if (!projects.length) {
      clear(listHost).append(empty(canCreate ? t("No projects yet.") : t("No project is shared with you yet. Ask its owner to add you."), canCreate
        ? h("button", { class: "primary", type: "button", onClick: openCreate }, icon("plus", 16), t("Create the first project"))
        : null));
      return;
    }
    if (!visible.length) {
      clear(listHost).append(empty(t("No projects match your search. Try another ID, company, or language.")));
      return;
    }
    clear(listHost).append(h("ul", { class: "project-grid" }, visible.map((project) => projectCard(project, summaries.get(project.project_id)))));
  }

  const active = known.filter((s) => !["done", "not_started"].includes(s.status)).length;
  const reviews = known.reduce((sum, s) => sum + s.reviews, 0);
  const questions = known.reduce((sum, s) => sum + s.questions, 0);
  clear(main).append(
    h("div", { class: "page-heading" },
      h("div", {}, h("p", { class: "eyebrow" }, t("Control room")), h("h1", {}, t("Projects")), h("p", { class: "muted" }, t("Your requirements, documents, and decisions."))),
      canCreate ? h("button", { class: "primary", type: "button", onClick: openCreate }, icon("plus", 17), t("New project")) : null,
    ),
    h("section", { class: "metrics", "aria-label": t("Workspace summary") },
      metric("projects", "accent", t("Total projects"), projects.length, t("in this workspace")),
      metric("workflow", "run", t("In progress"), active, t("active workflows")),
      metric("shield", "warn", t("Reviews waiting"), reviews, t("{n} open customer question(s)", { n: questions })),
    ),
    h("section", { class: "panel project-browser", "aria-labelledby": "all-projects" },
      h("div", { class: "browser-heading" }, h("h2", { id: "all-projects" }, t("All projects")), count),
      projects.length ? h("div", { class: "project-tools" }, searchBox, filters) : null,
      listHost,
    ),
  );
  drawList();
}

// The New project form, in a focus-trapped dialog (refresh design) instead of below the list.
function createDialog({ api, go, toast }) {
  const id = h("input", { type: "text", id: "project_id", name: "project_id", autocomplete: "off", spellcheck: "false", placeholder: "PRJ-001…", pattern: "PRJ-[0-9]{3}", required: true });
  const company = h("input", { type: "text", name: "company_id", value: "default", required: true });
  const language = h("select", { name: "document_language" }, h("option", { value: "ja" }, t("Japanese")), h("option", { value: "en" }, t("English")));
  const rounds = h("input", { type: "number", name: "team_max_rounds", min: "1", max: "20", value: "3" });
  const budget = h("input", { type: "number", name: "team_token_budget", min: "1", value: "100000" });
  const mode = h("select", { name: "propagation_mode" }, h("option", { value: "manual_gate" }, t("Manual: press Propagate")), h("option", { value: "auto" }, t("Automatic: update documents when a decision is made")));
  const idField = field(t("Project id"), id, t("Format PRJ-001"));
  const setIdError = (msg) => {
    idField.classList.toggle("invalid", Boolean(msg));
    idField.querySelector(".field-error")?.remove();
    if (msg) {
      id.setAttribute("aria-invalid", "true");
      idField.append(h("p", { class: "field-error", role: "alert" }, msg));
    } else {
      id.removeAttribute("aria-invalid");
    }
  };
  id.addEventListener("input", () => { if (/^PRJ-[0-9]{3}$/.test(id.value.trim())) setIdError(null); });
  modal((close) => h(
    "form",
    {
      class: "dialog create-dialog",
      novalidate: true,
      onSubmit: async (event) => {
        event.preventDefault();
        if (!/^PRJ-[0-9]{3}$/.test(id.value.trim())) {
          setIdError(t("Use the format PRJ-001 (PRJ- followed by three digits)."));
          id.focus();
          return;
        }
        setIdError(null);
        try {
          const created = await api.post("/projects", {
            project_id: id.value.trim(),
            company_id: company.value,
            document_language: language.value,
            team_max_rounds: Number(rounds.value),
            team_token_budget: budget.value ? Number(budget.value) : null,
            propagation_mode: mode.value,
          });
          close();
          toast(t("Created {id}", { id: created.project_id }));
          go(`#/p/${created.project_id}/overview`);
        } catch (error) {
          toast(error.message, "error");
        }
      },
    },
    h("div", { class: "dialog-top" },
      h("span", { class: "dialog-icon", "aria-hidden": "true" }, icon("plus", 18)),
      h("h2", { id: "create-title" }, t("New project")),
      h("button", { type: "button", class: "icon-button", "aria-label": t("Close"), onClick: close }, icon("close", 18)),
    ),
    h("p", { class: "muted" }, t("Set up a workspace for a new document workflow.")),
    idField,
    field(t("Company"), company, t("Selects the template set; “default” uses the baseline.")),
    h("div", { class: "field-pair" },
      field(t("Document language"), language, t("The language of everything the agents write.")),
      field(t("Max team rounds"), rounds, t("How many drafts a team may make before it escalates.")),
    ),
    field(t("Token budget per run"), budget, t("100,000 tokens by default; leave blank for no cap.")),
    field(t("Document updates after a decision"), mode, t("Applies when a Decision Record is approved or a customer question is answered.")),
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", onClick: close }, t("Cancel")),
      h("button", { type: "submit", class: "primary" }, icon("plus", 16), t("Create project")),
    ),
  ), { labelledBy: "create-title" });
  queueMicrotask(() => id.focus({ preventScroll: true }));
}
