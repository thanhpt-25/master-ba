// The Documents tree (spec 26 section 6): folders and files like a file manager.
// buildTree, filterTree and visibleRows are pure so the tests can walk them without a DOM;
// treeView draws them as a WAI-ARIA tree with roving focus.

import { badge, clear, h, icon } from "../dom.js";
import { N_, t } from "../i18n.js";
import { PHASES } from "./journey.js";

// The phase whose folder holds a document type, and the file name it shows.
const PHASE_OF = { BRD: "brd", SRS: "srs", BASIC_DESIGN: "basic", TEST_IT: "basic", TEST_ST: "basic", DETAIL_DESIGN: "detail", TEST_UT: "detail", TEST_UAT: "detail" };
export const FILE_NAMES = {
  BRD: N_("Business requirements definition"),
  SRS: N_("System requirements definition"),
  BASIC_DESIGN: N_("Basic design document"),
  DETAIL_DESIGN: N_("Detail design document"),
  TEST_IT: N_("Integration test specification"),
  TEST_ST: N_("System test specification"),
  TEST_UT: N_("Unit test specification"),
  TEST_UAT: N_("Acceptance test specification"),
};
// Inside a folder: the design document first, then its tests from the widest level down.
const ORDER = ["BRD", "SRS", "BASIC_DESIGN", "DETAIL_DESIGN", "TEST_UAT", "TEST_ST", "TEST_IT", "TEST_UT"];
const DESIGN = new Set(["BRD", "SRS", "BASIC_DESIGN", "DETAIL_DESIGN"]);
const ATTENTION = new Set(["in_review"]);

function fileNode(entry) {
  const d = entry.document;
  const versions = [...(entry.versions ?? [d.version])].sort((a, b) => b - a);
  return {
    key: d.id,
    kind: "doc",
    id: d.id,
    type: d.type,
    label: t(FILE_NAMES[d.type] ?? d.type),
    status: d.status,
    version: d.version,
    items: entry.items ?? null,
    children: versions.map((v) => ({ key: `${d.id}/v${v}`, kind: "version", id: d.id, version: v, label: `v${v}`, latest: v === d.version, children: [] })),
  };
}

function folder(key, label, files) {
  return {
    key,
    kind: "folder",
    label,
    children: files,
    count: files.length,
    attention: files.filter((f) => ATTENTION.has(f.status)).length,
  };
}

// docs: the GET /documents rows; intakes: the GET /intake rows; mode: "phase" or "kind".
export function buildTree(docs, intakes = [], mode = "phase") {
  const files = docs.map(fileNode).sort((a, b) => ORDER.indexOf(a.type) - ORDER.indexOf(b.type) || a.id.localeCompare(b.id));
  const folders = mode === "kind"
    ? [
        folder("kind:design", t("Design documents"), files.filter((f) => DESIGN.has(f.type))),
        folder("kind:test", t("Test specifications"), files.filter((f) => !DESIGN.has(f.type))),
      ]
    : PHASES.map((phase, i) => folder(`phase:${phase.key}`, `${String(i + 1).padStart(2, "0")} ${t(phase.title)}`, files.filter((f) => PHASE_OF[f.type] === phase.key)));
  folders.push({
    ...folder("intake", t("Intake"), intakes.map((file) => ({ key: `intake:${file.name}`, kind: "intake", name: file.name, label: file.name, size: file.size, lines: file.lines, children: [] }))),
  });
  return folders;
}

// Keeps the files whose name or document id contains the query, with their folders.
export function filterTree(nodes, query) {
  const q = String(query ?? "").trim().toLowerCase();
  if (!q) return nodes;
  const hit = (node) => `${node.label} ${node.id ?? ""}`.toLowerCase().includes(q);
  return nodes
    .map((f) => ({ ...f, children: f.children.filter(hit).map((c) => ({ ...c })) }))
    .filter((f) => f.children.length || hit(f));
}

// The rows a reader can see, in order, with their depth; folders and files open when expanded.
export function visibleRows(nodes, expanded, level = 1, parent = null) {
  const rows = [];
  for (const node of nodes) {
    rows.push({ node, level, parent });
    if (node.children.length && expanded.has(node.key)) rows.push(...visibleRows(node.children, expanded, level + 1, node.key));
  }
  return rows;
}

// The folder key and file key that lead to a key, so a deep link opens its folders.
export function ancestorsOf(nodes, key) {
  for (const f of nodes) {
    if (f.key === key) return [];
    for (const file of f.children) {
      if (file.key === key) return [f.key];
      if (file.children.some((v) => v.key === key)) return [f.key, file.key];
    }
  }
  return [];
}

export function findNode(nodes, key) {
  for (const f of nodes) {
    if (f.key === key) return f;
    for (const file of f.children) {
      if (file.key === key) return file;
      const version = file.children.find((v) => v.key === key);
      if (version) return version;
    }
  }
  return null;
}

const ROW_ICON = { folder: "folder", doc: "sheet", version: "dot", intake: "file" };

// Draws the tree into `host`. state: { nodes, expanded:Set, selected, focused }.
// on: { select(node), open(node), toggle(key, open) }. Returns a redraw function.
export function treeView(host, state, on) {
  const tree = h("ul", { class: "tree", role: "tree", "aria-label": t("Documents") });
  let rows = [];

  const draw = (focus = false) => {
    rows = visibleRows(state.nodes, state.expanded);
    if (!rows.some((r) => r.node.key === state.focused)) state.focused = rows.find((r) => r.node.key === state.selected)?.node.key ?? rows[0]?.node.key ?? null;
    clear(tree);
    for (const { node, level } of rows) {
      const open = state.expanded.has(node.key);
      const hasKids = node.children.length > 0;
      const meta = [];
      if (node.kind === "folder") {
        if (node.attention) meta.push(h("span", { class: "tree-count warn", title: t("{n} in review", { n: node.attention }) }, String(node.attention)));
        else if (node.count) meta.push(h("span", { class: "tree-count" }, String(node.count)));
      } else if (node.kind === "doc") {
        meta.push(badge(node.status));
      } else if (node.kind === "version") {
        if (node.latest) meta.push(h("span", { class: "tree-note" }, t("Latest")));
      } else if (node.kind === "intake") {
        meta.push(h("span", { class: "tree-note" }, t("{n} lines", { n: node.lines })));
      }
      const item = h("li", {
        role: "treeitem",
        id: `tree-${cssKey(node.key)}`,
        "data-key": node.key,
        "aria-level": String(level),
        "aria-expanded": hasKids ? String(open) : null,
        "aria-selected": node.key === state.selected ? "true" : "false",
        tabindex: node.key === state.focused ? "0" : "-1",
        class: `tree-item kind-${node.kind}`,
        style: `--level:${level}`,
      },
      h("span", { class: "tree-twist", "aria-hidden": "true" }, hasKids ? icon("chevron", 12) : null),
      h("span", { class: `tree-icon ${node.kind}${open ? " open" : ""}`, "aria-hidden": "true" }, icon(ROW_ICON[node.kind], 15)),
      h("span", { class: "tree-label" }, node.label),
      node.kind === "doc" ? h("span", { class: "sr-only" }, ` ${node.id}`) : null,
      h("span", { class: "tree-meta" }, meta));
      tree.append(item);
    }
    if (focus) tree.querySelector('[tabindex="0"]')?.focus({ preventScroll: false });
  };

  const rowOf = (key) => rows.findIndex((r) => r.node.key === key);
  const moveTo = (index) => {
    if (index < 0 || index >= rows.length) return;
    state.focused = rows[index].node.key;
    draw(true);
  };
  const activate = (node) => {
    state.selected = node.key;
    state.focused = node.key;
    on.select(node);
    draw(true);
  };
  let typed = "";
  let typedAt = 0;

  tree.addEventListener("click", (event) => {
    const item = event.target.closest?.("[role=treeitem]");
    if (!item) return;
    const node = rows[rowOf(item.dataset.key)]?.node;
    if (!node) return;
    if (node.children.length && (event.target.closest(".tree-twist") || node.kind === "folder")) {
      const open = !state.expanded.has(node.key);
      on.toggle(node.key, open);
    }
    activate(node);
  });
  tree.addEventListener("dblclick", (event) => {
    const item = event.target.closest?.("[role=treeitem]");
    const node = item ? rows[rowOf(item.dataset.key)]?.node : null;
    if (node && node.kind !== "folder") on.open(node);
  });
  tree.addEventListener("keydown", (event) => {
    const index = rowOf(state.focused);
    const current = rows[index];
    if (!current) return;
    const node = current.node;
    const key = event.key;
    if (key === "ArrowDown") moveTo(index + 1);
    else if (key === "ArrowUp") moveTo(index - 1);
    else if (key === "Home") moveTo(0);
    else if (key === "End") moveTo(rows.length - 1);
    else if (key === "ArrowRight") {
      if (node.children.length && !state.expanded.has(node.key)) { on.toggle(node.key, true); draw(true); }
      else if (node.children.length) moveTo(index + 1);
    } else if (key === "ArrowLeft") {
      if (node.children.length && state.expanded.has(node.key)) { on.toggle(node.key, false); draw(true); }
      else if (current.parent) moveTo(rowOf(current.parent));
    } else if (key === "Enter" || key === " ") {
      if (node.kind === "folder") on.toggle(node.key, !state.expanded.has(node.key));
      activate(node);
    } else if (key.length === 1 && /\S/.test(key) && !event.ctrlKey && !event.metaKey && !event.altKey) {
      // Type-ahead: jump to the next visible row whose name starts with the typed letters.
      const now = Date.now();
      typed = now - typedAt < 700 ? typed + key.toLowerCase() : key.toLowerCase();
      typedAt = now;
      const order = [...rows.slice(index + 1), ...rows.slice(0, index + 1)];
      const match = order.find((r) => r.node.label.toLowerCase().replace(/^\d+\s+/, "").startsWith(typed) || String(r.node.id ?? "").toLowerCase().startsWith(typed));
      if (match) moveTo(rowOf(match.node.key));
    } else return;
    event.preventDefault();
  });

  clear(host).append(tree);
  draw();
  return draw;
}

// Keys hold "/" and ":"; ids must not.
export function cssKey(key) {
  return String(key).replace(/[^A-Za-z0-9_-]/g, "_");
}
