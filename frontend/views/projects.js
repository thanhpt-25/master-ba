import { clear, empty, field, h } from "../dom.js";

export async function render({ main, api, me, go, toast }) {
  // The route shell shows a skeleton until this resolves.
  const projects = await api.get("/projects");
  let search = "";
  let languageFilter = "all";
  const listHost = h("div", {});
  const count = h("span", { class: "project-count", role: "status" });
  const searchBox = h("label", { class: "project-search" },
    h("span", { class: "sr-only" }, "Find a project by ID or company"),
    h("span", { class: "search-icon", "aria-hidden": "true" }, "⌕"),
    h("input", { type: "search", placeholder: "Find a project by ID or company", onInput: (event) => { search = event.target.value; drawList(); } }),
  );
  const filters = h("div", { class: "project-filters", role: "group", "aria-label": "Filter projects by document language" },
    ...[["all", "All languages"], ["en", "English"], ["ja", "Japanese"]].map(([value, label]) =>
      h("button", { type: "button", "aria-pressed": value === languageFilter ? "true" : "false", onClick: () => { languageFilter = value; for (const button of filters.children) button.setAttribute("aria-pressed", button.textContent === label ? "true" : "false"); drawList(); } }, label),
    ),
  );
  function drawList() {
    const term = search.trim().toLocaleLowerCase();
    const visible = projects.filter((project) =>
      (!term || `${project.project_id} ${project.company_id}`.toLocaleLowerCase().includes(term)) &&
      (languageFilter === "all" || project.document_language === languageFilter),
    );
    count.textContent = `${visible.length} of ${projects.length} project${projects.length === 1 ? "" : "s"}`;
    if (!projects.length) {
      clear(listHost).append(empty("No projects yet.", me.role === "admin"
        ? h("a", { class: "button", href: "#new-project", onClick: (event) => { event.preventDefault(); document.getElementById("project_id")?.focus(); } }, "Create the first project")
        : null));
      return;
    }
    if (!visible.length) {
      clear(listHost).append(empty("No projects match your search. Try another ID, company, or language."));
      return;
    }
    clear(listHost).append(h("ul", { class: "project-list" }, visible.map((project) =>
      h("li", {}, h("a", { href: `#/p/${project.project_id}/overview` },
        h("span", { class: "project-card-kicker" }, "Project", h("span", { "aria-hidden": "true" }, "↗")),
        h("strong", {}, project.project_id),
        h("span", { class: "project-company" }, `Company · ${project.company_id}`),
        h("span", {}, `Documents in ${project.document_language === "ja" ? "Japanese" : "English"}`),
        h("span", {}, `Team limit · ${project.team_max_rounds} rounds`),
        ...Object.entries(project.team_max_rounds_by_stage || {}).map(([stage, rounds]) => h("span", {}, `${stage} · ${rounds} rounds`)),
        h("span", { class: "project-open" }, "Open workspace", h("span", { "aria-hidden": "true" }, "↗")),
      )),
    )));
  }

  clear(main).append(
    h("div", { class: "page-heading" }, h("div", {}, h("p", { class: "eyebrow" }, "Workspace"), h("h1", {}, "Projects"), h("p", { class: "muted" }, "Your requirements, documents, and decisions.")), count),
    projects.length ? h("div", { class: "project-tools" }, searchBox, filters) : null,
    listHost,
  );
  drawList();
  if (me.role !== "admin") return;

  const id = h("input", { type: "text", id: "project_id", name: "project_id", autocomplete: "off", spellcheck: "false", placeholder: "PRJ-001…", pattern: "PRJ-[0-9]{3}", required: true });
  const company = h("input", { type: "text", name: "company_id", value: "default", required: true });
  const language = h("select", { name: "document_language" }, h("option", { value: "ja" }, "Japanese"), h("option", { value: "en" }, "English"));
  const rounds = h("input", { type: "number", name: "team_max_rounds", min: "1", max: "20", value: "3" });
  const budget = h("input", { type: "number", name: "team_token_budget", min: "1", value: "100000" });
  const idField = field("Project id", id, "Format PRJ-001");
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
  main.append(
    h(
      "form",
      {
        class: "panel form-grid",
        onSubmit: async (event) => {
          event.preventDefault();
          if (!/^PRJ-[0-9]{3}$/.test(id.value.trim())) {
            setIdError("Use the format PRJ-001 (PRJ- followed by three digits).");
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
            });
            toast(`Created ${created.project_id}`);
            go(`#/p/${created.project_id}/overview`);
          } catch (error) {
            toast(error.message, "error");
          }
        },
      },
      h("h2", {}, "New project"),
      idField,
      field("Company", company, "Selects the template set; “default” uses the baseline."),
      field("Document language", language, "The language of everything the agents write."),
      field("Max team rounds", rounds, "How many drafts a team may make before it escalates."),
      field("Token budget per run", budget, "100,000 tokens by default; leave blank for no cap."),
      h("button", { type: "submit", class: "primary" }, "Create project"),
    ),
  );
}
