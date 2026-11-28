// Documents as a file manager (spec 26 section 6): a folder tree on the left, the selected
// file, version, folder or intake file on the right. A document shows its workbook as the
// preview prints it (spec 19 section 14), with the review band of its phase above it.

import { badge, cellText, clear, empty, h, icon, loadError, modal, pageHeader, spinner, table } from "../dom.js";
import { N_, t } from "../i18n.js";
import { recordsFor, shownStatus } from "./drs.js";
import { ancestorsOf, buildTree, filterTree, findNode, treeView } from "./explorer.js";
import { phaseOfDocument, phaseTitle } from "./journey.js";
import { reviewBox } from "./review.js";

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
  // The tabs sit along the bottom edge, as in Excel.
  return h("div", { class: "sheets" }, panel, h("div", { class: "sheet-tabs", role: "tablist", "aria-label": t("Workbook sheets") }, tabs));
}


// Per-browser settings: grouping, open folders, tree width. Storage may be blocked.
const STORE = "masterba-explorer";
function loadPrefs(pid) {
  try {
    const all = JSON.parse(localStorage.getItem(STORE) ?? "{}");
    return { mode: all.mode === "kind" ? "kind" : "phase", width: Number(all.width) || 300, expanded: all.expanded?.[pid] ?? null };
  } catch {
    return { mode: "phase", width: 300, expanded: null };
  }
}
function savePrefs(pid, prefs) {
  try {
    const all = JSON.parse(localStorage.getItem(STORE) ?? "{}");
    all.mode = prefs.mode;
    all.width = prefs.width;
    all.expanded = { ...(all.expanded ?? {}), [pid]: [...prefs.expanded] };
    localStorage.setItem(STORE, JSON.stringify(all));
  } catch { /* The tree still works; it just forgets on reload. */ }
}

// The selection a URL names: rest is what follows #/p/<pid>/documents/.
export function selectionFromRest(rest) {
  const [first, second] = rest ?? [];
  if (!first) return null;
  if (first === "folder" && second) return second;
  if (first === "intake" && second) return `intake:${second}`;
  if (second && /^v\d+$/.test(second)) return `${first}/${second}`;
  return first;
}
export function hashFor(pid, node) {
  const base = `#/p/${pid}/documents`;
  if (!node) return base;
  if (node.kind === "folder") return `${base}/folder/${encodeURIComponent(node.key)}`;
  if (node.kind === "intake") return `${base}/intake/${encodeURIComponent(node.name)}`;
  if (node.kind === "version") return `${base}/${node.id}/v${node.version}`;
  return `${base}/${node.id}`;
}

function crumbs(pid, trail) {
  return h(
    "nav",
    { class: "crumbs", "aria-label": t("Path") },
    h("ol", {}, [h("li", {}, pid), ...trail.map((part, i) => h("li", { "aria-current": i === trail.length - 1 ? "location" : null }, part))]),
  );
}

function diffDialog(pid, doc, versions, version, context) {
  const { api, toast } = context;
  modal((close) => {
    const fromSelect = h("select", { id: "diff-from" }, versions.map((v) => h("option", { value: v }, `v${v}`)));
    const toSelect = h("select", { id: "diff-to" }, versions.map((v) => h("option", { value: v }, `v${v}`)));
    const index = versions.indexOf(version);
    toSelect.value = String(version);
    fromSelect.value = String(versions[Math.max(0, index - 1)]);
    const hide = h("input", { type: "checkbox", id: "diff-hide" });
    const box = h("div", { class: "diff-result", "aria-live": "polite" });
    const run = async () => {
      clear(box).append(spinner(t("Comparing…")));
      try {
        const query = `from=${fromSelect.value}&to=${toSelect.value}&structural_only=${hide.checked}`;
        const data = await api.get(`/projects/${pid}/documents/${doc}/diff?${query}`);
        clear(box).append(
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
        clear(box);
        toast(error.message, "error");
      }
    };
    for (const control of [fromSelect, toSelect, hide]) control.addEventListener("change", run);
    run();
    return h(
      "div",
      { class: "dialog diff-dialog" },
      h("div", { class: "dialog-top" }, h("h2", { id: "diff-title" }, t("Compare versions"), " ", h("code", {}, doc)), h("button", { type: "button", class: "icon-button", "aria-label": t("Close"), onClick: close }, icon("close", 16))),
      h(
        "div",
        { class: "toolbar" },
        h("label", { for: "diff-from" }, t("Compare from")),
        fromSelect,
        h("label", { for: "diff-to" }, t("Compare to")),
        toSelect,
        h("label", { class: "inline", for: "diff-hide" }, hide, ` ${t("hide rewordings")}`),
      ),
      box,
    );
  }, { labelledBy: "diff-title" });
}

// The review band above the preview while the document's phase waits for review.
function reviewBand(pid, docId, overview, context) {
  const key = phaseOfDocument(docId);
  const info = overview?.stages.find((s) => s.stage === key);
  if (!info || info.review !== "in_review" || info.status === "running") return null;
  const stage = { key, title: phaseTitle(key) };
  const canReview = ["approver", "admin"].includes(context.me?.role);
  const others = info.documents.filter((d) => d.id !== docId);
  const band = h("section", { class: "review-band", "aria-labelledby": "review-title", "data-open": "false" });
  const lead = h(
    "div",
    { class: "review-band-lead" },
    h("span", { class: "review-band-mark", "aria-hidden": "true" }, icon("clock", 20)),
    h(
      "div",
      {},
      h("h3", { id: "review-title" }, t("Review {phase}", { phase: stage.title })),
      h(
        "p",
        { class: "muted" },
        canReview ? t("Read the sheets, then approve or reject.") : t("Waiting for an approver's review."),
        others.length ? [" ", t("The review covers every document of the phase:"), " ", others.map((d) => h("a", { class: "chip-link", href: `#/p/${pid}/documents/${d.id}` }, h("code", {}, d.id)))] : null,
      ),
    ),
  );
  band.append(lead);
  if (!canReview) return band;
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
  const box = reviewBox(stage, ctx, { placeholderRef: `${docId}#item.1` });
  const approve = h("button", { type: "button", class: "primary", onClick: () => box.querySelector("button.primary")?.click() }, t("Approve"));
  const reject = h("button", {
    type: "button",
    "aria-expanded": "false",
    onClick: () => {
      const open = band.dataset.open !== "true";
      band.dataset.open = String(open);
      reject.setAttribute("aria-expanded", String(open));
      if (open) box.querySelector("textarea")?.focus();
    },
  }, t("Reject with comments…"));
  lead.append(h("div", { class: "review-band-actions" }, approve, reject));
  band.append(h("div", { class: "review-band-form" }, box));
  return band;
}

// "変更管理票 N件": the Decision Records that name this document, each a link to 変更管理.
function relatedRecords(pid, docId, drs) {
  const related = recordsFor(drs, docId);
  if (!related.length) return null;
  return h(
    "p",
    { class: "related-records" },
    h("span", { "aria-hidden": "true" }, icon("drs", 15)),
    h("span", {}, t("Change requests: {n}", { n: related.length })),
    related.map((d) => h("a", { class: "chip-link", href: `#/p/${pid}/drs/${d.id}` }, h("code", {}, d.id), " ", badge(shownStatus(d)))),
  );
}

function docPreview(pid, node, file, folderLabel, overview, context) {
  const { api, toast } = context;
  const versions = file.children.map((v) => v.version).sort((a, b) => a - b);
  const version = node.kind === "version" ? node.version : file.version;
  const status = h("span", {}, badge(file.status));
  const body = h("div", { class: "workbook" }, spinner(t("Loading version…")));
  const versionSelect = h("select", { id: "doc-version", "aria-label": t("Version") }, [...versions].reverse().map((v) => h("option", { value: v, selected: v === version }, `v${v}`)));
  versionSelect.addEventListener("change", () => context.openKey(`${file.id}/v${versionSelect.value}`));
  const download = h("a", { class: "button", href: api.url(`/projects/${pid}/documents/${file.id}/xlsx?version=${version}`), download: "" }, icon("download", 15), t("Excel"));
  const compare = versions.length > 1
    ? h("button", { type: "button", onClick: () => diffDialog(pid, file.id, versions, version, context) }, icon("diff", 15), t("Compare"))
    : null;
  api.get(`/projects/${pid}/documents/${file.id}/preview?version=${version}`).then(
    (data) => {
      clear(status).append(badge(data.document.status));
      clear(body).append(data.sheets.length ? sheetTabs(data.sheets) : empty(t("This sheet has no rows in this version.")));
    },
    (error) => {
      clear(body).append(loadError(error, () => context.openKey(node.key)));
      toast(error.message, "error");
    },
  );
  return [
    crumbs(pid, [folderLabel, file.label, `v${version}`]),
    h(
      "header",
      { class: "preview-head" },
      h("span", { class: "preview-icon", "aria-hidden": "true" }, icon("sheet", 22)),
      h("div", { class: "preview-title" }, h("h2", {}, file.label), h("p", { class: "muted" }, h("code", {}, file.id), ` · v${version}`, version !== file.version ? ` · ${t("Latest")} v${file.version}` : "")),
      status,
      h("div", { class: "preview-actions" }, h("label", { class: "sr-only", for: "doc-version" }, t("Version")), versionSelect, compare, download),
    ),
    relatedRecords(pid, file.id, context.drs ?? []),
    reviewBand(pid, file.id, overview, context),
    body,
    h("p", { class: "hint" }, t("The preview shows the standard layout; the Excel file follows the project's template.")),
  ];
}

function folderPreview(pid, node, context) {
  const files = node.children;
  const intake = node.key === "intake";
  const rows = files.map((f) => {
    const open = h("button", { type: "button", class: "link file-link", onClick: () => context.openKey(f.key) }, h("span", { "aria-hidden": "true" }, icon(intake ? "file" : "sheet", 15)), f.label);
    return intake
      ? [open, t("{n} lines", { n: f.lines }), t("{n} KB", { n: Math.max(1, Math.round(f.size / 1024)) })]
      : [open, h("code", {}, f.id), `v${f.version}`, badge(f.status), f.items ?? "—"];
  });
  const headers = intake ? [t("Name"), t("Lines"), t("Size")] : [t("Name"), t("Document"), t("Version"), t("Status"), t("Items")];
  return [
    crumbs(pid, [node.label]),
    h("header", { class: "preview-head" }, h("span", { class: "preview-icon folder", "aria-hidden": "true" }, icon("folder", 22)), h("div", { class: "preview-title" }, h("h2", {}, node.label), h("p", { class: "muted" }, t("{n} files", { n: files.length })))),
    files.length ? table(headers, rows, node.label, { dense: true }) : empty(intake ? t("No intake files yet.") : t("No documents in this folder yet.")),
  ];
}

function intakePreview(pid, node, folderLabel, context) {
  const body = h("div", { class: "intake-text" }, spinner());
  context.api.get(`/projects/${pid}/intake/${encodeURIComponent(node.name)}`).then(
    (data) => {
      const lines = data.text.split("\n");
      if (lines.length && lines[lines.length - 1] === "") lines.pop();
      clear(body).append(h("ol", { class: "numbered-lines", "aria-label": node.name }, lines.map((line, i) => h("li", { id: `L${i + 1}` }, h("span", { class: "line-no", "aria-hidden": "true" }, `L${i + 1}`), h("span", { class: "line-text" }, line || " ")))));
    },
    (error) => clear(body).append(loadError(error, () => context.openKey(node.key))),
  );
  return [
    crumbs(pid, [folderLabel, node.name]),
    h("header", { class: "preview-head" }, h("span", { class: "preview-icon", "aria-hidden": "true" }, icon("file", 22)), h("div", { class: "preview-title" }, h("h2", {}, node.name), h("p", { class: "muted" }, t("{n} lines", { n: node.lines }), " · ", t("The BRD cites these line numbers.")))),
    body,
  ];
}

export async function render(context) {
  const { main, api, params } = context;
  const pid = params.pid;
  const [docs, intakes, overview, drs] = await Promise.all([
    api.get(`/projects/${pid}/documents`),
    api.get(`/projects/${pid}/intake`).catch(() => []),
    api.get(`/projects/${pid}`).catch(() => null),
    api.get(`/projects/${pid}/drs`).catch(() => []),
  ]);
  const prefs = loadPrefs(pid);
  let tree = buildTree(docs, intakes, prefs.mode);
  const wanted = selectionFromRest(params.rest);
  const first = tree.find((f) => f.children.length);
  const state = {
    nodes: tree,
    expanded: new Set(prefs.expanded ?? tree.filter((f) => f.children.length && f.key !== "intake").map((f) => f.key)),
    selected: (wanted && findNode(tree, wanted) ? wanted : null) ?? first?.children[0]?.key ?? tree[0]?.key ?? null,
    focused: null,
  };
  for (const key of ancestorsOf(tree, state.selected)) state.expanded.add(key);
  prefs.expanded = state.expanded;

  const explorer = h("div", { class: "explorer", "data-view": wanted ? "preview" : "tree" });
  explorer.style.setProperty("--tree-w", `${prefs.width}px`);
  const treeHost = h("div", { class: "tree-host" });
  const preview = h("section", { class: "explorer-preview", "aria-label": t("Preview"), tabindex: "-1" });

  const folderOf = (key) => {
    const chain = ancestorsOf(tree, key);
    return chain.length ? findNode(tree, chain[0]) : null;
  };
  const show = (key) => {
    const node = findNode(tree, key);
    if (!node) {
      clear(preview).append(empty(t("No documents yet."), h("a", { class: "button primary", href: `#/p/${pid}/overview` }, t("Go to the Overview to run a stage"))));
      return;
    }
    const back = h("button", { type: "button", class: "explorer-back", onClick: () => { explorer.dataset.view = "tree"; treeHost.querySelector('[tabindex="0"]')?.focus(); } }, icon("back", 15), t("Files"));
    let parts;
    if (node.kind === "folder") parts = folderPreview(pid, node, local);
    else if (node.kind === "intake") parts = intakePreview(pid, node, folderOf(key)?.label ?? "", local);
    else {
      const file = node.kind === "doc" ? node : findNode(tree, node.id);
      parts = docPreview(pid, node, file, folderOf(file.key)?.label ?? "", overview, local);
    }
    clear(preview).append(back, ...parts.filter(Boolean));
    history.replaceState(null, "", hashFor(pid, node));
  };
  const local = { ...context, drs };
  let redraw = () => {};
  local.openKey = (key) => {
    for (const k of ancestorsOf(tree, key)) state.expanded.add(k);
    state.selected = key;
    state.focused = key;
    savePrefs(pid, prefs);
    redraw();
    show(key);
    explorer.dataset.view = "preview";
  };

  const filter = h("input", { type: "search", id: "tree-filter", placeholder: t("Filter by name or id"), "aria-label": t("Filter by name or id"), autocomplete: "off" });
  const modeButtons = [["phase", t("By phase")], ["kind", t("By kind")]].map(([mode, label]) =>
    h("button", { type: "button", "aria-pressed": String(prefs.mode === mode), "data-mode": mode }, label));
  const refresh = () => {
    state.nodes = filterTree(tree, filter.value);
    if (filter.value.trim()) for (const f of state.nodes) state.expanded.add(f.key);
    redraw();
  };
  for (const button of modeButtons) {
    button.addEventListener("click", () => {
      prefs.mode = button.dataset.mode;
      for (const b of modeButtons) b.setAttribute("aria-pressed", String(b === button));
      tree = buildTree(docs, intakes, prefs.mode);
      for (const f of tree) if (f.children.length && f.key !== "intake") state.expanded.add(f.key);
      for (const k of ancestorsOf(tree, state.selected)) state.expanded.add(k);
      savePrefs(pid, prefs);
      refresh();
      if (!findNode(tree, state.selected)) local.openKey(tree[0].key);
    });
  }
  filter.addEventListener("input", refresh);

  // The divider between tree and preview: drag it, or use the arrow keys on it.
  const divider = h("div", { class: "explorer-divider", role: "separator", "aria-orientation": "vertical", "aria-label": t("Resize the file tree"), tabindex: "0", "aria-valuemin": "220", "aria-valuemax": "520", "aria-valuenow": String(prefs.width) });
  const setWidth = (w) => {
    prefs.width = Math.round(Math.min(520, Math.max(220, w)));
    explorer.style.setProperty("--tree-w", `${prefs.width}px`);
    divider.setAttribute("aria-valuenow", String(prefs.width));
  };
  divider.addEventListener("keydown", (event) => {
    const step = { ArrowLeft: -16, ArrowRight: 16 }[event.key];
    if (!step) return;
    event.preventDefault();
    setWidth(prefs.width + step);
    savePrefs(pid, prefs);
  });
  divider.addEventListener("pointerdown", (event) => {
    const startX = event.clientX;
    const startW = prefs.width;
    divider.setPointerCapture?.(event.pointerId);
    const move = (e) => setWidth(startW + e.clientX - startX);
    const up = () => {
      divider.removeEventListener("pointermove", move);
      divider.removeEventListener("pointerup", up);
      savePrefs(pid, prefs);
    };
    divider.addEventListener("pointermove", move);
    divider.addEventListener("pointerup", up);
  });

  const side = h(
    "aside",
    { class: "explorer-tree", "aria-label": t("Files") },
    h("div", { class: "explorer-tools" }, h("div", { class: "segmented", role: "group", "aria-label": t("Group documents") }, modeButtons), filter),
    treeHost,
  );
  explorer.append(side, divider, preview);
  clear(main).append(pageHeader(t("Documents"), t("Every deliverable as a file, with its versions and the intake it came from.")), explorer);
  redraw = treeView(treeHost, state, {
    select: (node) => {
      savePrefs(pid, prefs);
      show(node.key);
      if (node.kind !== "folder") explorer.dataset.view = "preview";
    },
    open: (node) => local.openKey(node.key),
    toggle: (key, open) => {
      if (open) state.expanded.add(key);
      else state.expanded.delete(key);
      savePrefs(pid, prefs);
    },
  });
  show(state.selected);
}
