// Spec 26: the command palette's matching, the rail label and the V drawing's grid.
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

install();
const i18n = await import("../i18n.js");
i18n.setLang("en");
const { filterCommands, fold, railLabel, openPalette } = await import("../palette.js");
const { vLayout, testLevelState, RIGHT } = await import("../views/overview.js");

const commands = [
  { id: "p1", group: "Projects", label: "PRJ-001", hint: "koyo-mfg", run() {} },
  { id: "p2", group: "Projects", label: "PRJ-002", hint: "default", run() {} },
  { id: "docs", group: "PRJ-001", label: "Documents", keywords: ["PRJ-001"], run() {} },
  { id: "theme", group: "Actions", label: "Change colour theme", run() {} },
];
const ids = (list) => list.map((c) => c.id);

test("an empty query lists every command in order", () => {
  assert.deepEqual(ids(filterCommands(commands, "  ")), ["p1", "p2", "docs", "theme"]);
});

test("every word must match the label, hint or keywords", () => {
  assert.deepEqual(ids(filterCommands(commands, "koyo")), ["p1"]);
  assert.deepEqual(ids(filterCommands(commands, "prj 001")), ["p1", "docs"]);
  assert.deepEqual(ids(filterCommands(commands, "colour nope")), []);
});

test("a label that starts with the query ranks first", () => {
  assert.deepEqual(ids(filterCommands(commands, "doc")), ["docs"]);
  assert.deepEqual(ids(filterCommands(commands, "001")), ["p1", "docs"]);
  assert.deepEqual(ids(filterCommands(commands, "theme")), ["theme"]);
});

test("matching ignores case and full-width letters", () => {
  assert.equal(fold("ＰＲＪ－００１"), "prj-001");
  assert.deepEqual(ids(filterCommands(commands, "ＰＲＪ－００２")), ["p2"]);
});

test("the rail shows the project's trailing number", () => {
  assert.equal(railLabel("PRJ-001"), "001");
  assert.equal(railLabel("ACME-12345"), "345");
  assert.equal(railLabel("demo"), "DEM");
});

test("the V pairs each design phase with its test level on one row, without overlap", () => {
  for (let i = 0; i < 4; i++) {
    const at = vLayout(i);
    assert.equal(at.row, i + 1);
    // Nodes are three columns wide on twelve: the left node ends where the pair line starts.
    assert.equal(at.left + 3, at.pairFrom);
    assert.equal(at.right, at.pairTo);
    assert.ok(at.left + 3 <= at.right, `row ${i} overlaps`);
    assert.ok(at.right + 3 <= 13);
  }
  // The last row's nodes touch at the vertex: no pair line is drawn there.
  assert.equal(vLayout(3).pairFrom, vLayout(3).pairTo);
});

test("a test level is done once its design stage wrote its document", () => {
  const stages = [{ stage: "basic", status: "done", documents: [{ id: "DOC-TEST_IT-0001", version: 1, status: "draft" }] }];
  assert.equal(testLevelState(RIGHT[2], stages).status, "done");
  assert.equal(testLevelState(RIGHT[1], stages).status, "not_started");
  assert.equal(testLevelState(RIGHT[0], stages).status, "planned");
  assert.equal(testLevelState(RIGHT[3], [{ stage: "detail", status: "escalated", documents: [] }]).status, "escalated");
});

test("the palette runs the chosen command with Enter and closes", () => {
  let ran = null;
  const list = [
    { id: "a", group: "G", label: "Alpha", run: () => { ran = "a"; } },
    { id: "b", group: "G", label: "Beta", run: () => { ran = "b"; } },
  ];
  openPalette(list);
  const input = document.getElementById("palette-input");
  assert.ok(input, "the palette has its search field");
  input.value = "bet";
  input.dispatchEvent(new Event("input"));
  input.dispatchEvent(Object.assign(new Event("keydown"), { key: "Enter", preventDefault() {} }));
  assert.equal(ran, "b");
  assert.equal(document.getElementById("palette-input"), null);
});
