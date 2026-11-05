import { clear, empty, field, h } from "../dom.js";

export async function render({ main, api, me, go, toast }) {
  // The route shell shows a skeleton until this resolves.
  const projects = await api.get("/projects");
  const list = projects.length
    ? h(
        "ul",
        { class: "project-list" },
        projects.map((p) =>
          h(
            "li",
            {},
            h(
              "a",
              { href: `#/p/${p.project_id}/overview` },
              h("strong", {}, p.project_id),
              h("span", {}, `company ${p.company_id} · documents in ${p.document_language === "ja" ? "Japanese" : "English"}`),
              h("span", {}, `team limit ${p.team_max_rounds} rounds`),
              ...Object.entries(p.team_max_rounds_by_stage || {}).map(([stage, n]) => h("span", {}, `${stage} ${n} rounds`)),
            ),
          ),
        ),
      )
    : empty(
        "No projects yet.",
        me.role === "admin"
          ? h("a", { class: "button", href: "#new-project", onClick: (event) => { event.preventDefault(); document.getElementById("project_id")?.focus(); } }, "Create the first project")
          : null,
      );

  clear(main).append(h("h1", {}, "Projects"), list);
  if (me.role !== "admin") return;

  const id = h("input", { type: "text", id: "project_id", name: "project_id", autocomplete: "off", spellcheck: "false", placeholder: "PRJ-001…", pattern: "PRJ-[0-9]{3}", required: true });
  const company = h("input", { type: "text", name: "company_id", value: "default", required: true });
  const language = h("select", { name: "document_language" }, h("option", { value: "ja" }, "Japanese"), h("option", { value: "en" }, "English"));
  const rounds = h("input", { type: "number", name: "team_max_rounds", min: "1", max: "20", value: "3" });
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
      h("button", { type: "submit", class: "primary" }, "Create project"),
    ),
  );
}
