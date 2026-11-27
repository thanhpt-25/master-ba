// Audit log (spec 24 section 2): who changed accounts, limits, prices and sharing, and sign-ins.
import { clear, empty, field, fmtTime, h, icon, loadError, skeleton, table } from "../dom.js";
import { N_, t } from "../i18n.js";

export const STAGE_LABELS = { brd: N_("BRD"), srs: N_("SRS"), basic: N_("Basic Design"), detail: N_("Detail Design") };

const ACTIONS = {
  "auth.login": N_("Signed in"),
  "auth.login_failed": N_("Sign-in failed"),
  "auth.logout": N_("Signed out"),
  "user.create": N_("User added"),
  "user.role": N_("Role changed"),
  "user.password": N_("Password reset"),
  "user.limits": N_("Limits changed"),
  "user.usage_reset": N_("Usage reset"),
  "user.disable": N_("User disabled"),
  "user.enable": N_("User enabled"),
  "user.signout": N_("Signed out everywhere"),
  "user.remove": N_("User removed"),
  "limits.default": N_("Default limits changed"),
  "prices.set": N_("Model prices changed"),
  "project.create": N_("Project created"),
  "project.owner": N_("Owner changed"),
  "project.member_set": N_("Member added or changed"),
  "project.member_remove": N_("Member removed"),
  "job.start": N_("Job started"),
};
const GROUPS = [
  ["", N_("All actions")],
  ["auth", N_("Sign-in")],
  ["user", N_("Users")],
  ["project", N_("Projects")],
  ["job", N_("Jobs")],
  ["limits", N_("Default limits")],
  ["prices", N_("Model prices")],
];
const PERIODS = [["", N_("Any time")], ["1", N_("Last 24 hours")], ["7", N_("Last 7 days")], ["30", N_("Last 30 days")], ["90", N_("Last 90 days")]];
const KINDS = { "stage:brd": N_("BRD run"), "stage:srs": N_("SRS run"), "stage:basic": N_("Basic Design run"), "stage:detail": N_("Detail Design run"), propagate: N_("Change propagation") };

export function actionLabel(action) {
  return ACTIONS[action] ? t(ACTIONS[action]) : String(action);
}

// stage:brd → "BRD run"; propagate:DR-0003 → "Change propagation DR-0003"; review:srs → "SRS rejection".
export function kindLabel(kind) {
  if (!kind) return t("Other");
  if (KINDS[kind]) return t(KINDS[kind]);
  const [head, rest] = String(kind).split(":");
  if (head === "propagate") return `${t(KINDS.propagate)} ${rest ?? ""}`.trim();
  if (head === "review") return t("{stage} rejection", { stage: t(STAGE_LABELS[rest] ?? rest ?? "") });
  return String(kind);
}

// The filter of the page as query parameters (shared by the table and the CSV link).
export function auditQuery(filter) {
  const params = new URLSearchParams();
  for (const key of ["actor", "action", "target", "days"]) if (filter[key]) params.set(key, filter[key]);
  return params;
}

function detailText(e) {
  const d = e.detail ?? {};
  const parts = [];
  if (d.old !== undefined && d.new !== undefined) parts.push(`${d.old} → ${d.new}`);
  if (d.role) parts.push(String(d.role));
  if (d.kind) parts.push(kindLabel(d.kind));
  if (d.previous) parts.push(t("from {name}", { name: d.previous }));
  if (d.projects_to) parts.push(t("projects to {name}", { name: d.projects_to }));
  if (d.reason === "locked") parts.push(t("locked after repeated failures"));
  if (d.limits && typeof d.limits === "object") parts.push(t("5 h: {session} · week: {weekly}", { session: d.limits.session ?? "∞", weekly: d.limits.weekly ?? "∞" }));
  if (d.limits === "default") parts.push(t("back to the defaults"));
  if (d.currency) parts.push(t("{n} priced model(s), {currency}", { n: Object.keys(d.models ?? {}).length, currency: d.currency }));
  return parts.join(" · ");
}

export async function render({ main, api, params }) {
  const filter = { actor: "", action: "", target: params.rest?.[0] ?? "", days: "30" };
  const actor = h("input", { type: "search", spellcheck: "false", maxlength: "40", placeholder: t("Any user") });
  const target = h("input", { type: "search", spellcheck: "false", maxlength: "40", value: filter.target, placeholder: t("User or project id") });
  const action = h("select", {}, GROUPS.map(([value, label]) => h("option", { value }, t(label))));
  const days = h("select", {}, PERIODS.map(([value, label]) => h("option", { value, selected: value === filter.days }, t(label))));
  const list = h("div", {});
  const csv = h("a", { class: "button", download: "masterba-audit.csv" }, icon("documents", 16), t("Download CSV"));
  let rows = [];
  let cursor = null;
  let token = 0;

  const more = h("button", { type: "button", hidden: true, onClick: () => load(false) }, t("Load more"));

  function paint() {
    clear(list).append(rows.length
      ? table(
          [t("Time"), t("Actor"), t("Action"), t("Target"), t("Project"), t("Details"), t("Client")],
          rows.map((e) => [
            fmtTime(e.at),
            e.actor === "anonymous" ? h("span", { class: "muted" }, t("not signed in")) : h("strong", {}, e.actor),
            h("span", { class: `audit-action ${String(e.action).split(".")[0]}${e.action === "auth.login_failed" ? " bad" : ""}` }, actionLabel(e.action)),
            e.target ?? "–",
            e.project_id ? h("a", { href: `#/p/${e.project_id}/overview` }, h("code", {}, e.project_id)) : "–",
            detailText(e),
            h("span", { class: "muted" }, e.source ?? ""),
          ]),
          t("Audit log"),
          { dense: true, stickyFirst: true },
        )
      : empty(t("No events match this filter.")));
    more.hidden = cursor === null;
  }

  async function load(reset = true) {
    const mine = ++token;
    if (reset) { rows = []; cursor = null; clear(list).append(skeleton(6)); }
    const query = auditQuery(filter);
    csv.href = api.url(`/admin/audit.csv?${query}`);
    query.set("limit", "50");
    if (!reset && cursor) query.set("before", String(cursor));
    try {
      const page = await api.get(`/admin/audit?${query}`);
      if (mine !== token) return;
      rows = rows.concat(page.events);
      cursor = page.next;
      paint();
    } catch (error) {
      if (mine !== token) return;
      clear(list).append(loadError(error, () => load(reset)));
    }
  }

  let timer = null;
  const changed = () => {
    filter.actor = actor.value.trim();
    filter.target = target.value.trim();
    filter.action = action.value;
    filter.days = days.value;
    clearTimeout(timer);
    timer = setTimeout(() => load(true), 250);
  };
  for (const control of [actor, target]) control.addEventListener("input", changed);
  for (const control of [action, days]) control.addEventListener("change", changed);

  clear(main).append(
    h("div", { class: "page-heading" },
      h("div", {}, h("h1", {}, t("Audit log")),
        h("p", { class: "muted" }, t("Sign-ins and every change to accounts, limits, prices and sharing, newest first. The log cannot be edited.")),
      ),
      csv,
    ),
    h("section", { class: "panel" },
      h("div", { class: "filter-row" },
        field(t("Actor"), actor),
        field(t("Action"), action),
        field(t("Target"), target),
        field(t("Period"), days),
      ),
      list,
      h("div", { class: "row" }, more),
    ),
  );
  await load(true);
  return () => { token++; clearTimeout(timer); };
}
