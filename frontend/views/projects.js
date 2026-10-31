import { empty, field, h } from "../dom.js";

export async function render({ main, api, me, go, toast }) {
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
            ),
          ),
        ),
      )
    : empty("No projects yet.");

  main.append(h("h1", {}, "Projects"), list);
  if (me.role !== "admin") return;

  const id = h("input", { type: "text", name: "project_id", placeholder: "PRJ-001", pattern: "PRJ-[0-9]{3}", required: true });
  const company = h("input", { type: "text", name: "company_id", value: "default", required: true });
  const language = h("select", { name: "document_language" }, h("option", { value: "ja" }, "Japanese"), h("option", { value: "en" }, "English"));
  const rounds = h("input", { type: "number", name: "team_max_rounds", min: "1", max: "20", value: "3" });
  main.append(
    h(
      "form",
      {
        class: "panel form-grid",
        onSubmit: async (event) => {
          event.preventDefault();
          try {
            const created = await api.post("/projects", {
              project_id: id.value,
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
      field("Project id", id, "Format PRJ-001"),
      field("Company", company, "Selects the template set; “default” uses the baseline."),
      field("Document language", language, "The language of everything the agents write."),
      field("Max team rounds", rounds, "How many drafts a team may make before it escalates."),
      h("button", { type: "submit", class: "primary" }, "Create project"),
    ),
  );
}
