// Spec 26 section 6: the Documents tree, its filter, keyboard rows and deep links.
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

install();
const i18n = await import("../i18n.js");
i18n.setLang("en");
const { ancestorsOf, buildTree, filterTree, findNode, visibleRows } = await import("../views/explorer.js");
const { hashFor, selectionFromRest } = await import("../views/documents.js");

const doc = (id, type, version = 1, status = "draft") => ({
  document: { id, type, version, status },
  versions: Array.from({ length: version }, (_, i) => i + 1),
  items: 3,
});
const docs = [
  doc("DOC-TEST_UT-0001", "TEST_UT"),
  doc("DOC-BRD-0001", "BRD", 2, "in_review"),
  doc("DOC-TEST_IT-0001", "TEST_IT"),
  doc("DOC-BASIC_DESIGN-0001", "BASIC_DESIGN"),
  doc("DOC-TEST_ST-0001", "TEST_ST"),
  doc("DOC-SRS-0001", "SRS"),
  doc("DOC-DETAIL_DESIGN-0001", "DETAIL_DESIGN"),
];
const intakes = [{ name: "timesheet.md", size: 2048, lines: 40 }];
const keys = (nodes) => nodes.map((n) => n.key);

test("by phase: four numbered phase folders in V order, then the intake folder", () => {
  const tree = buildTree(docs, intakes);
  assert.deepEqual(keys(tree), ["phase:brd", "phase:srs", "phase:basic", "phase:detail", "intake"]);
  assert.equal(tree[0].label, "01 BRD");
  assert.ok(tree[3].label.startsWith("04 "));
  // The design document first, then its tests from the widest level down.
  assert.deepEqual(tree[2].children.map((f) => f.id), ["DOC-BASIC_DESIGN-0001", "DOC-TEST_ST-0001", "DOC-TEST_IT-0001"]);
  assert.deepEqual(tree[3].children.map((f) => f.id), ["DOC-DETAIL_DESIGN-0001", "DOC-TEST_UT-0001"]);
  assert.deepEqual(keys(tree[4].children), ["intake:timesheet.md"]);
});

test("folders count their files and the files in review", () => {
  const [brd, srs] = buildTree(docs, intakes);
  assert.equal(brd.count, 1);
  assert.equal(brd.attention, 1);
  assert.equal(srs.attention, 0);
});

test("a file's children are its versions, newest first", () => {
  const brd = buildTree(docs)[0].children[0];
  assert.equal(brd.label, "Business requirements definition");
  assert.deepEqual(brd.children.map((v) => v.label), ["v2", "v1"]);
  assert.equal(brd.children[0].latest, true);
  assert.equal(brd.children[1].latest, false);
});

test("by kind: design documents, test specifications, then the intake folder", () => {
  const tree = buildTree(docs, intakes, "kind");
  assert.deepEqual(keys(tree), ["kind:design", "kind:test", "intake"]);
  assert.equal(tree[0].children.length, 4);
  assert.deepEqual(tree[1].children.map((f) => f.type), ["TEST_ST", "TEST_IT", "TEST_UT"]);
});

test("the filter keeps matching files with their folder and drops empty folders", () => {
  const tree = buildTree(docs, intakes);
  assert.deepEqual(keys(filterTree(tree, "unit")), ["phase:detail"]);
  assert.deepEqual(filterTree(tree, "TEST_IT")[0].children.map((f) => f.id), ["DOC-TEST_IT-0001"]);
  assert.deepEqual(keys(filterTree(tree, "timesheet")), ["intake"]);
  assert.equal(filterTree(tree, "  "), tree);
});

test("visible rows follow the open folders, with level and parent for the keyboard", () => {
  const tree = buildTree(docs, intakes);
  const closed = visibleRows(tree, new Set());
  assert.equal(closed.length, 5);
  const open = visibleRows(tree, new Set(["phase:brd", "DOC-BRD-0001"]));
  assert.deepEqual(open.slice(0, 5).map((r) => [r.node.key, r.level, r.parent]), [
    ["phase:brd", 1, null],
    ["DOC-BRD-0001", 2, "phase:brd"],
    ["DOC-BRD-0001/v2", 3, "DOC-BRD-0001"],
    ["DOC-BRD-0001/v1", 3, "DOC-BRD-0001"],
    ["phase:srs", 1, null],
  ]);
});

test("a deep link finds its node and the folders that lead to it", () => {
  const tree = buildTree(docs, intakes);
  assert.deepEqual(ancestorsOf(tree, "DOC-BRD-0001/v1"), ["phase:brd", "DOC-BRD-0001"]);
  assert.deepEqual(ancestorsOf(tree, "intake:timesheet.md"), ["intake"]);
  assert.equal(findNode(tree, "DOC-BRD-0001/v1").version, 1);
  assert.equal(findNode(tree, "nope"), null);
});

test("URLs round-trip a file, a version, a folder and an intake file", () => {
  const tree = buildTree(docs, intakes);
  for (const key of ["DOC-SRS-0001", "DOC-BRD-0001/v1", "phase:basic", "intake:timesheet.md"]) {
    const hash = hashFor("PRJ-001", findNode(tree, key));
    const rest = hash.replace("#/p/PRJ-001/documents/", "").split("/").map(decodeURIComponent);
    assert.equal(selectionFromRest(rest), key, hash);
  }
  assert.equal(selectionFromRest([]), null);
});
