// Documents: each version shown as the workbook prints it (spec 19 section 14), with the
// review of its phase in place and the version comparison below.

import { asyncView, badge, cellText, clear, empty, h, spinner, splitNav, table } from "../dom.js";
import { N_, t } from "../i18n.js";
import { phaseOfDocument, phaseTitle } from "./journey.js";
import { reviewBox } from "./review.js";

const TYPE_NAMES = {
  BRD: N_("BRD"),
  SRS: N_("SRS"),
  BASIC_DESIGN: N_("Basic Design"),
  DETAIL_DESIGN: N_("Detail Design"),
  TEST_IT: N_("Integration tests (IT)"),
  TEST_ST: N_("System tests (ST)"),
  TEST_UT: N_("Unit tests (UT)"),
  TEST_UAT: N_("UAT"),
};
// V-model order: requirements and design down the left side, then the tests that verify them.
const ORDER = ["BRD", "SRS", "BASIC_DESIGN", "DETAIL_DESIGN", "TEST_UAT", "TEST_ST", "TEST_IT", "TEST_UT"];
const CHANGES = { added: N_("Added"), removed: N_("Removed"), field_changed: N_("Changed") };
const KINDS = { structural_change: N_("Structural"), reworded_only: N_("Rewording") };

function multiline(text) {
  return h("span", { class: "cell-text" }, text);
}

function coverSheet(sheet) {
  return h(
    "div",
    { class: "sheet-cover" },
    h("p", { class: "cover-title" }, sheet.title),
    h("dl", { class: "cover-rows" }, sheet.rows.flatMap(([label, value]) => [h("dt", {}, label), h("dd", {}, value || "—")])),
    h("div", { class: "stamp-box", "aria-label": t("Seal boxes") }, ["承認", "確認", "作成"].map((name) => h("div", {}, h("span", {}, name), h("span", { class: "stamp" })))),
  );
}

function tableSheet(sheet) {
  const body = sheet.rows.length
    ? table(sheet.columns, sheet.rows.map((row) => row.map(multiline)), sheet.name, { dense: true, stickyFirst: true })
    : empty(t("This sheet has no rows in this version."));
  return h("div", {}, sheet.note ? h("p", { class: "hint" }, sheet.note) : null, body);
}

function sectionSheet(sheet) {
  if (!sheet.body) return h("p", { class: "muted sheet-empty" }, sheet.empty_text);
  return h(
    "div",
    { class: "sheet-section" },
    h("h3", {}, "記載内容"),
    h("p", { class: "prose cell-text" }, sheet.body),
    h("h3", {}, "出典"),
    h("ul", { class: "chips" }, sheet.sources.map((s) => h("li", {}, h("code", { class: "chip" }, s)))),
  );
}

function sheetBody(sheet) {
  if (sheet.kind === "cover") return coverSheet(sheet);
  if (sheet.kind === "section") return sectionSheet(sheet);
  if (sheet.kind === "note") return h("p", { class: "muted sheet-empty" }, sheet.note);
  return tableSheet(sheet);
}

function sheetCount(sheet) {
  return sheet.kind === "table" ? sheet.rows.length : null;
}

// Sheets as tabs in workbook order; arrow keys move between tabs (WAI-ARIA tabs pattern).
export function sheetTabs(sheets, { selected = 0 } = {}) {
  const panel = h("div", { class: "sheet-panel", role: "tabpanel", tabindex: "0" });
  const tabs = sheets.map((sheet, i) => {
    const count = sheetCount(sheet);
    return h(
      "button",
      { type: "button", role: "tab", id: `sheet-tab-${sheet.key}`, class: "sheet-tab", "aria-selected": "false", tabindex: "-1" },
      sheet.name,
      count === null ? null : h("span", { class: "count" }, String(count)),
    );
  });
  const pick = (i, focus = false) => {
    tabs.forEach((tab, j) => {
      tab.setAttribute("aria-selected", i === j ? "true" : "false");
      tab.setAttribute("tabindex", i === j ? "0" : "-1");
    });
    panel.setAttribute("aria-labelledby", tabs[i].id);
    clear(panel).append(sheetBody(sheets[i]));
    if (focus) tabs[i].focus();
  };
  tabs.forEach((tab, i) => {
    tab.addEventListener("click", () => pick(i));
    tab.addEventListener("keydown", (event) => {
      const move = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
      if (move) {
        event.preventDefault();
        pick((i + move + tabs.length) % tabs.length, true);
      }
    });
  });
  if (sheets.length) pick(Math.min(selected, sheets.length - 1));
  return h("div", { class: "sheets" }, h("div", { class: "sheet-tabs", role: "tablist", "aria-label": t("Workbook sheets") }, tabs), panel);
}

function reviewPanel(pid, docId, overview, context) {
  const key = phaseOfDocument(docId);
  const info = overview?.stages.find((s) => s.stage === key);
  if (!info || info.review !== "in_review" || info.status === "running") return null;
  const stage = { key, title: phaseTitle(key) };
  if (!["approver", "admin"].includes(context.me?.role)) {
    return h("section", { class: "panel review-panel" }, h("h3", {}, t("Review {phase}", { phase: stage.title })), h("p", { class: "hint" }, t("Waiting for an approver's review.")));
  }
  const ctx = {
    toast: context.toast,
    openQuestions: info.open_questions,
    approve: async (stageKey) => {
      const done = await context.api.post(`/projects/${pid}/stages/${stageKey}/approve`);
      context.toast(t("Approved {phase} ({id})", { phase: stage.title, id: done.review.id }));
      context.go(`#/p/${pid}/overview`);
    },
    reject: async (stageKey, comments) => {
      await context.api.post(`/projects/${pid}/stages/${stageKey}/reject`, { comments });
      context.toast(t("Rejected {phase}; revising", { phase: stage.title }));
      context.go(`#/p/${pid}/overview`);
    },
  };
  const others = info.documents.filter((d) => d.id !== docId);
  return h(
    "section",
    { class: "panel review-panel", "aria-labelledby": "review-title" },
    h("h3", { id: "review-title" }, t("Review {phase}", { phase: stage.title })),
    others.length
      ? h("p", { class: "muted" }, t("The review covers every document of the phase:"), " ", others.map((d) => h("a", { class: "chip-link", href: `#/p/${pid}/documents/${d.id}` }, h("code", {}, d.id))))
      : null,
    reviewBox(stage, ctx, { placeholderRef: `${docId}#item.1` }),
  );
}

function renderDetail(pid, selected, loaded, overview, context) {
  const { api, toast } = context;
  const latest = loaded.versions[loaded.versions.length - 1];
  const versionSelect = h(
    "select",
    { id: "version", "aria-label": t("Version") },
    loaded.versions.map((v) => h("option", { value: v, selected: v === loaded.document.version }, `v${v}`)),
  );
  const body = h("div", {});
  const download = h("a", { class: "button", href: "#", download: "" }, t("Download Excel"));
  const statusHost = h("span", {}, badge(loaded.document.status));

  async function show(version) {
    body.setAttribute("aria-busy", "true");
    const prev = body.firstChild ? [...body.childNodes] : null;
    clear(body).append(spinner(t("Loading version…")));
    try {
      const data = await api.get(`/projects/${pid}/documents/${selected}/preview?version=${version}`);
      clear(statusHost).append(badge(data.document.status));
      clear(body).append(sheetTabs(data.sheets));
      download.href = api.url(`/projects/${pid}/documents/${selected}/xlsx?version=${version}`);
    } catch (error) {
      clear(body);
      if (prev) body.append(...prev);
      toast(error.message, "error");
    } finally {
      body.removeAttribute("aria-busy");
    }
  }
  versionSelect.addEventListener("change", () => show(versionSelect.value));

  const diffBox = h("div", {});
  const fromSelect = h("select", { id: "from", "aria-label": t("Compare from") }, loaded.versions.map((v) => h("option", { value: v }, `v${v}`)));
  const toSelect = h("select", { id: "to", "aria-label": t("Compare to") }, loaded.versions.map((v) => h("option", { value: v, selected: v === latest }, `v${v}`)));
  if (loaded.versions.length > 1) fromSelect.value = String(loaded.versions[loaded.versions.length - 2]);
  const hide = h("input", { type: "checkbox", id: "hide" });
  const diffBtn = h("button", {}, t("Show differences"));
  async function diff() {
    diffBtn.disabled = true;
    clear(diffBox).append(spinner(t("Comparing…")));
    try {
      const query = `from=${fromSelect.value}&to=${toSelect.value}&structural_only=${hide.checked}`;
      const data = await api.get(`/projects/${pid}/documents/${selected}/diff?${query}`);
      clear(diffBox).append(
        data.rows.length
          ? table(
              [t("Item"), t("Change"), t("Field"), t("Old"), t("New"), t("Kind")],
              data.rows.map((r) => [h("code", {}, r.item_id.split("#")[1] ?? r.item_id), t(CHANGES[r.change] ?? r.change), r.field ?? "", cellText(r.old), cellText(r.new), t(KINDS[r.classification] ?? r.classification)]),
              t("Differences"),
              { dense: true, stickyFirst: true },
            )
          : empty(t("No differences between these versions.")),
      );
    } catch (error) {
      clear(diffBox);
      toast(error.message, "error");
    } finally {
      diffBtn.disabled = false;
    }
  }
  diffBtn.addEventListener("click", diff);

  const type = loaded.document.type;
  const review = reviewPanel(pid, selected, overview, context);
  const parts = [
    h("div", { class: "vcard-head" }, h("div", {}, h("p", { class: "eyebrow" }, t(TYPE_NAMES[type] ?? type)), h("h2", {}, h("code", {}, selected))), statusHost),
    h("div", { class: "toolbar" }, h("label", { for: "version" }, t("Version")), versionSelect, download, h("span", { class: "hint" }, t("The preview shows the standard layout; the Excel file follows the project's template."))),
    review ? h("p", { class: "review-note" }, h("span", { "aria-hidden": "true" }, "◔ "), t("This phase is waiting for your review. Read the sheets, then approve or reject at the end of the page."), " ", h("a", { href: "#review-title", onClick: (event) => { event.preventDefault(); review.scrollIntoView({ behavior: "smooth" }); review.querySelector("button")?.focus({ preventScroll: true }); } }, t("Go to the review"))) : null,
    body,
    review,
    loaded.versions.length > 1
      ? h(
          "section",
          { class: "panel" },
          h("h3", {}, t("Compare versions")),
          h(
            "div",
            { class: "toolbar" },
            h("label", { for: "from" }, t("From")),
            fromSelect,
            h("label", { for: "to" }, t("To")),
            toSelect,
            h("label", { class: "inline", for: "hide" }, hide, ` ${t("hide rewordings")}`),
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
  const docs = (await api.get(`/projects/${pid}/documents`)).sort(
    (a, b) => ORDER.indexOf(a.document.type) - ORDER.indexOf(b.document.type) || a.document.id.localeCompare(b.document.id),
  );
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
          h("span", {}, `${t(TYPE_NAMES[d.type] ?? d.type)} · v${d.version}${versions.length > 1 ? ` / ${versions.length}` : ""}`),
          badge(d.status),
        ),
      ),
    ),
  );
  const detail = h("div", { class: "doc-detail" });
  const navBody = docs.length
    ? list
    : empty(t("No documents yet."), h("a", { class: "button primary", href: `#/p/${pid}/overview` }, t("Go to the Overview to run a stage")));
  clear(main).append(h("h1", {}, t("Documents")), h("div", { class: "split" }, splitNav(t("Documents"), navBody), detail));
  if (!selected) return;

  asyncView(
    detail,
    () => Promise.all([api.get(`/projects/${pid}/documents/${selected}`), api.get(`/projects/${pid}`)]),
    ([loaded, overview], host) => host.append(...renderDetail(pid, selected, loaded, overview, context)),
  );
}
