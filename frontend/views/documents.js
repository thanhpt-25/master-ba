import { asyncView, badge, cellText, clear, empty, h, spinner, splitNav, table } from "../dom.js";

const SKIP = new Set(["status"]);

function itemTable(content) {
  const items = content.items ?? [];
  if (!items.length) return empty("This document has no items.");
  const keys = [...new Set(items.flatMap((i) => Object.keys(i)))].filter((k) => !SKIP.has(k));
  keys.sort((a, b) => (a === "item_id" ? -1 : b === "item_id" ? 1 : 0));
  const rows = items.map((item) =>
    keys.map((k) => {
      const text = cellText(item[k]);
      const cell = h("span", { class: k === "item_id" || k.endsWith("_id") ? "mono" : "" }, text);
      return item.status === "removed" ? h("s", {}, cell) : cell;
    }),
  );
  return table(keys, rows, "Document items");
}

function exclusions(content) {
  if (!content.exclusions?.length) return null;
  return h(
    "section",
    {},
    h("h3", {}, "Items left without a test case"),
    table(["Item", "Reason"], content.exclusions.map((e) => [h("code", {}, e.item_ref), e.reason]), "Exclusions"),
  );
}

function renderDetail(pid, selected, loaded, { api, toast }) {
  const latest = loaded.versions[loaded.versions.length - 1];
  const versionSelect = h(
    "select",
    { id: "version", "aria-label": "Version" },
    loaded.versions.map((v) => h("option", { value: v, selected: v === loaded.document.version }, `v${v}`)),
  );
  const body = h("div", {});
  const diffBox = h("div", {});

  async function show(version) {
    body.setAttribute("aria-busy", "true");
    const prev = body.firstChild ? [...body.childNodes] : null;
    clear(body).append(spinner("Loading version…"));
    try {
      const data = await api.get(`/projects/${pid}/documents/${selected}?version=${version}`);
      clear(body).append(
        h("p", { class: "muted" }, `Template ${data.document.template_id} · ${data.content.items.length} item(s)`),
        itemTable(data.content),
        exclusions(data.content),
      );
      download.href = api.url(`/projects/${pid}/documents/${selected}/xlsx?version=${version}`);
    } catch (error) {
      clear(body);
      if (prev) body.append(...prev);
      toast(error.message, "error");
    } finally {
      body.removeAttribute("aria-busy");
    }
  }
  const download = h("a", { class: "button", href: "#", download: "" }, "Download Excel");
  versionSelect.addEventListener("change", () => show(versionSelect.value));

  const fromSelect = h("select", { id: "from", "aria-label": "Compare from" }, loaded.versions.map((v) => h("option", { value: v }, `v${v}`)));
  const toSelect = h("select", { id: "to", "aria-label": "Compare to" }, loaded.versions.map((v) => h("option", { value: v, selected: v === latest }, `v${v}`)));
  if (loaded.versions.length > 1) fromSelect.value = String(loaded.versions[loaded.versions.length - 2]);
  const hide = h("input", { type: "checkbox", id: "hide" });
  const diffBtn = h("button", {}, "Show differences");
  async function diff() {
    diffBtn.disabled = true;
    clear(diffBox).append(spinner("Comparing…"));
    try {
      const query = `from=${fromSelect.value}&to=${toSelect.value}&structural_only=${hide.checked}`;
      const data = await api.get(`/projects/${pid}/documents/${selected}/diff?${query}`);
      clear(diffBox).append(
        data.rows.length
          ? table(
              ["Item", "Change", "Field", "Old", "New", "Kind"],
              data.rows.map((r) => [h("code", {}, r.item_id.split("#")[1] ?? r.item_id), r.change, r.field ?? "", cellText(r.old), cellText(r.new), r.classification.replace("_", " ")]),
              "Differences",
              { dense: true, stickyFirst: true },
            )
          : empty("No differences between these versions."),
      );
    } catch (error) {
      clear(diffBox);
      toast(error.message, "error");
    } finally {
      diffBtn.disabled = false;
    }
  }
  diffBtn.addEventListener("click", diff);

  const parts = [
    h("div", { class: "vcard-head" }, h("h2", {}, h("code", {}, selected)), badge(loaded.document.status)),
    h("div", { class: "toolbar" }, h("label", { for: "version" }, "Version"), versionSelect, download),
    body,
    loaded.versions.length > 1
      ? h(
          "section",
          { class: "panel" },
          h("h3", {}, "Compare versions"),
          h(
            "div",
            { class: "toolbar" },
            h("label", { for: "from" }, "From"),
            fromSelect,
            h("label", { for: "to" }, "To"),
            toSelect,
            h("label", { class: "inline", for: "hide" }, hide, " hide rewordings"),
            diffBtn,
          ),
          diffBox,
        )
      : null,
  ];
  show(loaded.document.version);
  return parts.filter(Boolean);
}

export async function render(context) {
  const { main, api, params } = context;
  const pid = params.pid;
  const docs = await api.get(`/projects/${pid}/documents`);
  const selected = params.rest[0] ?? docs[0]?.document.id;
  const list = h(
    "ul",
    { class: "doc-list" },
    docs.map(({ document: d, versions }) =>
      h(
        "li",
        {},
        h(
          "a",
          { href: `#/p/${pid}/documents/${d.id}`, "aria-current": d.id === selected ? "page" : null },
          h("code", {}, d.id),
          h("span", {}, `${d.type.replace("_", " ")} · v${d.version}${versions.length > 1 ? ` of ${versions.length}` : ""}`),
        ),
      ),
    ),
  );
  const detail = h("div", { class: "doc-detail" });
  const navBody = docs.length
    ? list
    : empty("No documents yet.", h("a", { class: "button primary", href: `#/p/${pid}/overview` }, "Go to the Overview to run a stage"));
  clear(main).append(h("h1", {}, "Documents"), h("div", { class: "split" }, splitNav("Documents", navBody), detail));
  if (!selected) return;

  asyncView(
    detail,
    () => api.get(`/projects/${pid}/documents/${selected}`),
    (loaded, host) => host.append(...renderDetail(pid, selected, loaded, context)),
  );
}
