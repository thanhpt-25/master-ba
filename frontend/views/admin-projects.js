// Every project on the server (spec 24 section 6): owner, members, phases, tokens, activity.
// Ownership and members change through the routes of spec 23; a global admin may use them anywhere.
import { compact, number } from "../charts.js";
import { badge, clear, empty, field, fmtTime, h, icon, loadError, modal, skeleton, statusLabel, table } from "../dom.js";
import { t } from "../i18n.js";
import { STAGE_LABELS } from "./audit.js";

// The project rows a search matches: id, owner, member, company.
export function matchProjects(projects, query) {
  const q = String(query ?? "").trim().toLowerCase();
  if (!q) return projects;
  return projects.filter((p) => [p.project_id, p.owner, p.company_id, ...p.members.map((m) => m.name)]
    .some((v) => String(v ?? "").toLowerCase().includes(q)));
}

function phases(project) {
  return h("ol", { class: "phase-dots", "aria-label": t("Phases") },
    project.stages.map((s) => {
      const state = s.review === "in_review" ? "in_review" : s.review === "approved" ? "approved" : s.status;
      return h("li", { class: `phase-dot ${state}`, title: `${t(STAGE_LABELS[s.stage] ?? s.stage)}: ${statusLabel(state)}` },
        h("span", { class: "phase-name" }, t(STAGE_LABELS[s.stage] ?? s.stage)), badge(state));
    }),
  );
}

export async function render({ main, api, toast }) {
  const search = h("input", { type: "search", placeholder: t("Search by project, owner or member"), "aria-label": t("Search projects") });
  const host = h("div", {});
  let data = null;

  function handOver(project) {
    const select = h("select", {}, data.users.filter((u) => u.name !== project.owner && !u.disabled).map((u) => h("option", { value: u.name }, u.name)));
    if (!select.options.length) {
      toast(t("There is no other active user to hand the project to."), "error");
      return;
    }
    modal((close) => h("form", {
      class: "dialog create-dialog",
      onSubmit: async (event) => {
        event.preventDefault();
        const name = select.value;
        try {
          await api.post(`/projects/${encodeURIComponent(project.project_id)}/owner`, { name });
          close();
          toast(t("{name} now owns {pid}", { name, pid: project.project_id }));
          await refresh();
        } catch (error) {
          toast(error.message, "error");
        }
      },
    },
    h("div", { class: "dialog-top" },
      h("span", { class: "dialog-icon", "aria-hidden": "true" }, icon("projects", 18)),
      h("h2", { id: "handover-title" }, t("Hand {pid} to another user", { pid: project.project_id })),
      h("button", { type: "button", class: "icon-button", "aria-label": t("Close"), onClick: close }, icon("close", 18)),
    ),
    h("p", { class: "hint" }, t("The current owner {name} stays as an approver member.", { name: project.owner ?? "–" })),
    field(t("New owner"), select),
    h("div", { class: "dialog-actions" },
      h("button", { type: "button", onClick: close }, t("Cancel")),
      h("button", { type: "submit", class: "primary" }, t("Hand over")),
    ),
    ), { labelledBy: "handover-title" });
  }

  function paint() {
    const rows = matchProjects(data.projects, search.value);
    clear(host).append(rows.length
      ? table(
          [t("Project"), t("Project owner"), t("Members"), t("Phases"), t("Open items"), t("Tokens, 30 days"), t("Last activity"), ""],
          rows.map((p) => [
            h("span", { class: "project-cell" },
              h("a", { href: `#/p/${p.project_id}/overview` }, h("code", {}, p.project_id)),
              h("span", { class: "muted" }, `${p.company_id} · ${p.document_language.toUpperCase()}`),
              p.job ? badge("running") : null,
            ),
            p.owner ?? "–",
            p.members.length
              ? h("span", { class: "member-names" }, p.members.map((m) => h("span", { class: "chip" }, `${m.name} · ${t(m.role === "approver" ? "Approver" : "Viewer")}`)))
              : h("span", { class: "muted" }, t("Owner only")),
            phases(p),
            h("span", {}, t("{q} question(s) · {d} DR(s)", { q: p.open_questions, d: p.open_drs })),
            h("span", { title: t("{n} calls", { n: number(p.calls_30d) }) }, compact(p.tokens_30d)),
            p.last_activity ? fmtTime(p.last_activity) : h("span", { class: "muted" }, t("No activity yet")),
            h("span", { class: "row" },
              h("a", { class: "text-action", href: `#/p/${p.project_id}/members` }, t("Members")),
              h("button", { type: "button", class: "link", onClick: () => handOver(p) }, t("Hand over")),
            ),
          ]),
          t("All projects"),
          { dense: true, stickyFirst: true },
        )
      : empty(t("No project matches this search.")));
  }

  async function refresh() {
    clear(host).append(skeleton(5));
    try {
      data = await api.get("/admin/projects");
      count.textContent = t("{n} project(s)", { n: data.projects.length });
      paint();
    } catch (error) {
      clear(host).append(loadError(error, refresh));
    }
  }

  const count = h("span", { class: "muted" });
  search.addEventListener("input", () => data && paint());
  clear(main).append(
    h("div", { class: "page-heading" },
      h("div", {}, h("p", { class: "eyebrow" }, t("Administration")), h("h1", {}, t("All projects")),
        h("p", { class: "muted" }, t("Every project on this server with its owner, members, phases and model use.")),
      ),
    ),
    h("section", { class: "panel" },
      h("div", { class: "panel-heading" },
        h("label", { class: "project-search" }, icon("search", 16), search),
        count,
      ),
      host,
    ),
  );
  await refresh();
}
