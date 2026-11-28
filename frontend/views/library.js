// Template sets (spec 29): labels, the coverage report and the project's template picker.
import { append, clear, h, loadError, spinner, table } from "../dom.js";
import { N_, t } from "../i18n.js";

const KIND_LABELS = {
  "header:$document.id": N_("Document number"),
  "header:$document.title": N_("Document name"),
  "header:$document.version": N_("Version"),
  "header:$document.status": N_("Status"),
  "header:$document.author": N_("Author"),
  "header:$document.created_on": N_("Created on"),
  "header:$document.updated_on": N_("Updated on"),
  "header:$document.approver": N_("Approver"),
  "header:$document.approved_on": N_("Approved on"),
  "header:$document.classification": N_("Classification"),
  "header:$document.publisher": N_("Publisher"),
  "header:$document.type": N_("Document type"),
  "header:$project.id": N_("Project"),
  "header:$project.company": N_("Customer"),
  "list:$revisions": N_("Revision history"),
  "list:$trace": N_("Traceability"),
  "list:$exclusions": N_("Excluded items"),
  "list:$questions": N_("Open issues"),
  "field:$code": N_("Display code"),
  "field:$verifies_name": N_("Name of the item under test"),
  "section:background": N_("Background and purpose"),
  "section:constraints": N_("Constraints"),
  "section:system_overview": N_("System overview"),
  "section:it_viewpoints": N_("Integration test viewpoints"),
};

export const VISIBILITY = {
  private: N_("Private"),
  shared: N_("Shared with named users"),
  public: N_("Public"),
};

// What one data kind of the coverage report is called on screen.
export function kindLabel(kind) {
  if (KIND_LABELS[kind]) return t(KIND_LABELS[kind]);
  const [group, name] = kind.split(":");
  if (group === "section") return t("Section {name}", { name });
  if (group === "field") return t("Column {name}", { name });
  return kind;
}

export function setLabel(set) {
  if (set.builtin) return t("MasterBA standard");
  return set.title ? `${set.title} (${set.id})` : set.id;
}

// The apply button: a set that drops data needs the tick; the set in use needs no apply.
export function canApply(report, accepted, current) {
  if (!report || report.set === current) return false;
  return report.gaps === 0 || accepted;
}

export function coverageTable(report) {
  return table(
    [t("Document type"), t("Template"), t("Not printed")],
    report.types.map((type) => [
      type.doc_type,
      type.state === "fallback" ? t("Standard (this set has none)") : t("This set"),
      type.dropped.length
        ? h("ul", { class: "kind-list", "aria-label": t("Not printed") }, type.dropped.map((k) => h("li", { class: "kind-dropped" }, kindLabel(k))))
        : h("span", { class: "kind-ok" }, t("Everything is printed")),
    ]),
    t("What the template prints"),
    { dense: true },
  );
}

// The template row of the project settings (spec 29 section 6.3).
export function templateSettings(pid, { api, toast, refresh }) {
  const host = h("div", { class: "setting-row template-setting" }, spinner(t("Loading templates…")));
  let data = null;
  let report = null;

  const load = async () => {
    try {
      data = await api.get(`/projects/${pid}/template`);
    } catch (error) {
      clear(host).append(loadError(error, load));
      return;
    }
    draw(data.current);
  };

  const draw = (chosen) => {
    const select = h("select", { "aria-label": t("Template set"), disabled: !data.can_change },
      data.sets.map((s) => h("option", { value: s.id, selected: s.id === chosen }, s.hidden ? `${s.id} (${t("no longer shared")})` : setLabel(s))));
    const accept = h("input", { type: "checkbox" });
    const details = h("div", { class: "template-coverage" });
    const apply = h("button", { class: "primary", type: "button", disabled: true }, t("Apply template"));
    const update = () => { apply.disabled = !canApply(report, accept.checked, data.current); };
    accept.addEventListener("change", update);

    const showReport = async () => {
      report = null;
      update();
      clear(details).append(spinner(t("Checking what the template prints…")));
      try {
        report = await api.get(`/projects/${pid}/template/coverage?set=${encodeURIComponent(select.value)}`);
      } catch (error) {
        clear(details).append(loadError(error, showReport));
        return;
      }
      const set = encodeURIComponent(select.value);
      const docs = data.documents.filter((d) => !d.kept);
      const kept = data.documents.filter((d) => d.kept);
      append(clear(details), [
        coverageTable(report),
        docs.length
          ? h("p", { class: "muted" }, t("Preview with your documents:"), " ",
              ...docs.flatMap((d, i) => [i ? " · " : "", h("a", { href: api.url(`/projects/${pid}/template/preview/${d.id}.xlsx?set=${set}`) }, d.id)]))
          : null,
        kept.length
          ? h("div", {},
              h("p", { class: "muted" }, t("Approved documents keep the file that was issued. Re-issue one to print it with the current template.")),
              h("ul", { class: "kept-list" }, kept.map((d) => h("li", {}, h("code", {}, `${d.id} v${d.version}`), " ",
                h("button", { type: "button", class: "link", onClick: () => reissue(d) }, t("Re-issue"))))))
          : null,
        report.gaps && data.can_change && report.set !== data.current
          ? h("label", { class: "check" }, accept, " ", t("I have checked the items this template does not print"))
          : null,
      ]);
      update();
    };

    const reissue = async (doc) => {
      try {
        await api.post(`/projects/${pid}/documents/${doc.id}/reissue`);
        toast(t("{id} re-issued with the current template", { id: doc.id }));
      } catch (error) {
        toast(error.message, "error");
      }
    };

    apply.addEventListener("click", async () => {
      try {
        const done = await api.put(`/projects/${pid}/template`, { set: select.value, accept_gaps: accept.checked });
        toast(t("Template changed; {n} document(s) printed again", { n: done.rendered.length }));
        await load();
        await refresh?.();
      } catch (error) {
        toast(error.message, "error");
      }
    });
    select.addEventListener("change", showReport);

    append(clear(host), [
      h("div", {},
        h("h3", {}, t("Document template")),
        h("p", { class: "muted" }, t("Changing it prints the documents again. No AI run, no new version, no change record.")),
      ),
      h("div", { class: "template-picker" }, select, data.can_change ? apply : null),
      details,
    ]);
    showReport();
  };

  load();
  return host;
}
