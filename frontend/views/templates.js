import { badge, clear, empty, field, h, table } from "../dom.js";

const DOC_TYPES = ["BRD", "SRS", "BASIC_DESIGN", "DETAIL_DESIGN", "TEST_IT", "TEST_ST", "TEST_UT"];
const STATE_BADGE = { confirmed: "approved", draft: "proposed" };

function mappingTables(data, onSet) {
  const sections = data.mapping.tables.map((t) =>
    h(
      "section",
      { class: "panel" },
      h("h4", {}, `${t.sheet} · header row ${t.header_row}`, t.where && Object.keys(t.where).length ? ` · ${JSON.stringify(t.where)}` : ""),
      table(
        ["Column", "Sample header", "Field"],
        t.columns.map((c) => {
          const input = h("input", { type: "text", value: c.field ?? "", "aria-label": `Field of column ${c.col} on ${t.sheet}`, maxlength: "40" });
          const save = h("button", { onClick: () => onSet(t.sheet, c.col, input.value.trim() || null) }, "Set");
          return [h("code", {}, c.col), c.header, h("span", { class: "row" }, input, save)];
        }),
        `Columns of ${t.sheet}`,
      ),
    ),
  );
  return h("div", {}, sections);
}

export async function render({ main, api, toast }) {
  const company = h("input", { type: "text", name: "company", maxlength: "40", autocomplete: "off", spellcheck: "false", placeholder: "sample-sier…" });
  const docType = h("select", {}, DOC_TYPES.map((d) => h("option", { value: d }, d)));
  const sample = h("input", { type: "file", accept: ".xlsx" });
  const list = h("div", {});
  const detail = h("div", {});

  const refresh = async () => {
    const rows = await api.get("/templates");
    clear(list).append(
      rows.length
        ? table(
            ["Company", "Type", "State", ""],
            rows.map((r) => [r.company, r.doc_type, badge(STATE_BADGE[r.state] ?? r.state), h("button", { class: "link", onClick: () => open(r.company, r.doc_type) }, "Open")]),
            "Company templates",
          )
        : empty("No company template yet. Upload a sample workbook to start."),
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
      const next = await run(() => api.put(`${path}/mapping`, { sheet, col, field: name }), "Mapping updated; confirm again.");
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
            const result = await run(() => api.post(`${path}/preview`), "Preview rendered.");
            if (result) {
              toast(result.differences.length ? `${result.differences.length} layout differences` : "Layout matches the sample", "info");
              detail.append(h("p", {}, h("a", { href: api.url(`${path}/preview.xlsx`) }, "Download the preview"), result.differences.length ? h("ul", {}, result.differences.map((d) => h("li", {}, d))) : " · no layout differences"));
            }
          } }, "Render preview"),
          confirmed
            ? h("button", { onClick: async () => { const next = await run(() => api.post(`${path}/unconfirm`), "Confirmation removed."); if (next) { show(next); refresh(); } } }, "Remove confirmation")
            : h("button", { class: "primary", disabled: data.problems.length > 0, onClick: async () => { const next = await run(() => api.post(`${path}/confirm`), "Template confirmed."); if (next) { show(next); refresh(); } } }, "Confirm template"),
        ),
      ),
    );
  };

  const open = async (c, t) => {
    try {
      show(await api.get(`/templates/${c}/${t}`));
    } catch (error) {
      toast(error.message, "error");
    }
  };

  const upload = async () => {
    const file = sample.files[0];
    if (!company.value.trim() || !file) return toast("Enter a company id and choose an .xlsx sample.", "error");
    try {
      const data = await api.upload(`/templates/${encodeURIComponent(company.value.trim())}/${docType.value}/calibrate`, file);
      toast("Draft written. Review it, then confirm.", "info");
      show(data);
      refresh();
    } catch (error) {
      toast(error.message, "error");
    }
  };

  clear(main).append(
    h("h2", {}, "Company templates"),
    h("p", { class: "hint" }, "A calibrated template is used for rendering only after an administrator confirms it."),
    h("section", { class: "panel" }, field("Company", company), field("Document type", docType), field("Sample workbook (.xlsx, up to 5 MB)", sample), h("button", { class: "primary", onClick: upload }, "Calibrate from sample")),
    list,
    detail,
  );
  await refresh();
}
