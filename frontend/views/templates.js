import { append, badge, clear, empty, field, h, loadError, pageHeader, spinner, table } from "../dom.js";
import { t } from "../i18n.js";
import { setLabel, VISIBILITY } from "./library.js";

const DOC_TYPES = ["BRD", "SRS", "BASIC_DESIGN", "DETAIL_DESIGN", "TEST_IT", "TEST_ST", "TEST_UT"];
const STATE_BADGE = { confirmed: "approved", draft: "proposed" };

function mappingTables(data, onSet) {
  const sections = data.mapping.tables.map((tbl) =>
    h(
      "section",
      { class: "panel" },
      h("h4", {}, `${tbl.sheet} · ${t("header row {n}", { n: tbl.header_row })}`, tbl.where && Object.keys(tbl.where).length ? ` · ${JSON.stringify(tbl.where)}` : ""),
      table(
        [t("Column"), t("Sample header"), t("Field")],
        tbl.columns.map((c) => {
          const input = h("input", { type: "text", value: c.field ?? "", "aria-label": t("Field of column {col} on {sheet}", { col: c.col, sheet: tbl.sheet }), maxlength: "40" });
          const save = h("button", { onClick: () => onSet(tbl.sheet, c.col, input.value.trim() || null) }, t("Set"));
          return [h("code", {}, c.col), c.header, h("span", { class: "row" }, input, save)];
        }),
        t("Columns of {sheet}", { sheet: tbl.sheet }),
        { dense: true, stickyFirst: true },
      ),
    ),
  );
  return h("div", {}, sections);
}

// The set register (spec 29 section 6.3): every set the user sees, sharing for its owner.
function setRegister({ api, toast, me }, onChange) {
  const host = h("section", { class: "panel" }, spinner(t("Loading templates…")));
  const mayClone = me?.role === "approver" || me?.role === "admin";

  const share = (set) => {
    const mode = h("select", { "aria-label": t("Who may use {set}", { set: set.id }) },
      Object.entries(VISIBILITY).map(([value, label]) => h("option", { value, selected: value === set.visibility }, t(label))));
    const names = h("input", { type: "text", value: (set.shared_with ?? []).join(", "), placeholder: t("user names, comma separated"), "aria-label": t("Users {set} is shared with", { set: set.id }) });
    const save = h("button", { type: "button", onClick: async () => {
      try {
        const body = { visibility: mode.value, shared_with: names.value.split(",").map((n) => n.trim()).filter(Boolean) };
        await api.post(`/template-sets/${set.id}/visibility`, body);
        toast(mode.value === "public" ? t("Public: everyone can use it. Check that no sample text is left in the workbook.") : t("Sharing saved."), "info");
        await load();
      } catch (error) { toast(error.message, "error"); }
    } }, t("Save"));
    return h("span", { class: "row" }, mode, names, save);
  };

  // Copy a set: the button turns into an id field and a confirm button in place.
  const cloneCell = (set) => {
    const cell = h("span", { class: "row" });
    const ask = h("button", { type: "button", class: "link", onClick: () => {
      const target = h("input", { type: "text", value: `${set.id}-copy`, maxlength: "40", spellcheck: "false", "aria-label": t("Id of the copy of {set}", { set: set.id }) });
      const ok = h("button", { type: "button", onClick: async () => {
        try {
          await api.post(`/template-sets/${set.id}/clone`, { target: target.value.trim() });
          toast(t("Copied to {id}; it is private to you.", { id: target.value.trim() }), "info");
          await load();
          onChange();
        } catch (error) { toast(error.message, "error"); }
      } }, t("Copy"));
      clear(cell).append(target, ok);
      target.focus();
    } }, t("Copy"));
    cell.append(ask);
    return cell;
  };

  const load = async () => {
    let sets;
    try {
      sets = await api.get("/template-sets");
    } catch (error) {
      clear(host).append(loadError(error, load));
      return;
    }
    clear(host).append(
      h("h2", {}, t("Template sets")),
      h("p", { class: "muted" }, t("A project uses one set. Uploaded sets are private until their owner shares them.")),
      table(
        [t("Name"), t("Owner"), t("Who may use it"), t("Document types"), ""],
        sets.map((s) => [
          setLabel(s),
          s.owner ?? "—",
          s.can_manage ? share(s) : t(VISIBILITY[s.visibility] ?? s.visibility),
          Object.keys(s.types).join(", "),
          mayClone && !s.builtin ? cloneCell(s) : "",
        ]),
        t("Template sets"),
        { dense: true, stickyFirst: true },
      ),
    );
  };
  load();
  return host;
}

export async function render({ main, api, toast, me }) {
  const company = h("input", { type: "text", name: "company", maxlength: "40", autocomplete: "off", spellcheck: "false", placeholder: "sample-sier…" });
  const docType = h("select", {}, DOC_TYPES.map((d) => h("option", { value: d }, d)));
  const sample = h("input", { type: "file", accept: ".xlsx" });
  const list = h("div", {});
  const detail = h("div", {});

  const refresh = async () => {
    clear(list).append(spinner(t("Loading templates…")));
    let rows;
    try {
      rows = await api.get("/templates");
    } catch (error) {
      clear(list).append(loadError(error, refresh));
      return;
    }
    clear(list).append(
      rows.length
        ? table(
            [t("Company"), t("Type"), t("State"), ""],
            rows.map((r) => [r.company, r.doc_type, badge(STATE_BADGE[r.state] ?? r.state), h("button", { class: "link", onClick: () => open(r.company, r.doc_type), "aria-label": t("Open template {company} {type}", { company: r.company, type: r.doc_type }) }, t("View"))]),
            t("Company templates"),
            { dense: true, stickyFirst: true },
          )
        : empty(t("No company template yet. Upload a sample workbook to start.")),
    );
  };

  const show = (data) => {
    const path = `/templates/${data.company}/${data.doc_type}`;
    const run = async (action, label) => {
      try {
        const result = await action();
        toast(label, "info");
        return result;
      } catch (error) {
        toast(error.message, "error");
        return null;
      }
    };
    const onSet = async (sheet, col, name) => {
      const next = await run(() => api.put(`${path}/mapping`, { sheet, col, field: name }), t("Mapping updated; confirm again."));
      if (next) {
        show(next);
        refresh();
      }
    };
    const confirmed = data.state === "confirmed";
    clear(detail).append(
      h(
        "section",
        { class: "panel" },
        h("h3", {}, `${data.company} · ${data.doc_type} `, badge(STATE_BADGE[data.state] ?? data.state)),
        data.mapping.warnings.length ? h("ul", {}, data.mapping.warnings.map((w) => h("li", {}, w))) : null,
        data.problems.length ? h("ul", { class: "error", role: "alert" }, data.problems.map((p) => h("li", {}, p))) : null,
        mappingTables(data, onSet),
        h(
          "div",
          { class: "row" },
          h("button", { onClick: async () => {
            const result = await run(() => api.post(`${path}/preview`), t("Preview rendered."));
            if (result) {
              toast(result.differences.length ? t("{n} layout differences", { n: result.differences.length }) : t("Layout matches the sample"), "info");
              detail.append(h("p", {}, h("a", { href: api.url(`${path}/preview.xlsx`) }, t("Download the preview")), result.differences.length ? h("ul", {}, result.differences.map((d) => h("li", {}, d))) : ` · ${t("no layout differences")}`));
            }
          } }, t("Render preview")),
          confirmed
            ? h("button", { onClick: async () => { const next = await run(() => api.post(`${path}/unconfirm`), t("Confirmation removed.")); if (next) { show(next); refresh(); } } }, t("Remove confirmation"))
            : h("button", { class: "primary", disabled: data.problems.length > 0, onClick: async () => { const next = await run(() => api.post(`${path}/confirm`), t("Template confirmed.")); if (next) { show(next); refresh(); } } }, t("Confirm template")),
        ),
      ),
    );
  };

  const open = async (c, type) => {
    clear(detail).append(spinner(t("Opening template…")));
    try {
      const data = await api.get(`/templates/${c}/${type}`);
      clear(detail);
      show(data);
    } catch (error) {
      clear(detail).append(loadError(error, () => open(c, type)));
    }
  };

  const upload = async () => {
    const file = sample.files[0];
    if (!company.value.trim() || !file) return toast(t("Enter a company id and choose an .xlsx sample."), "error");
    try {
      const data = await api.upload(`/templates/${encodeURIComponent(company.value.trim())}/${docType.value}/calibrate`, file);
      toast(t("Draft written. Review it, then confirm."), "info");
      show(data);
      refresh();
    } catch (error) {
      toast(error.message, "error");
    }
  };

  const uploads = me?.role === "approver" || me?.role === "admin";
  append(clear(main), [
    pageHeader(t("Templates"), t("A calibrated template is used for rendering only after its owner confirms it.")),
    setRegister({ api, toast, me }, () => refresh()),
    uploads
      ? h("section", { class: "panel" }, h("h2", {}, t("Calibrate from a sample")), field(t("Company"), company), field(t("Document type"), docType), field(t("Sample workbook (.xlsx, up to 5 MB)"), sample), h("button", { class: "primary", onClick: upload }, t("Calibrate from sample")))
      : null,
    list,
    detail,
  ]);
  await refresh();
}
