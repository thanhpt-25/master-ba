// Template library helpers (spec 29): coverage labels and when a set may be applied.
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

install();
(await import("../i18n.js")).setLang("en");
const { canApply, kindLabel, setLabel } = await import("../views/library.js");

test("data kinds read as words, unknown ones by their name", () => {
  assert.equal(kindLabel("list:$trace"), "Traceability");
  assert.equal(kindLabel("header:$document.author"), "Author");
  assert.equal(kindLabel("section:background"), "Background and purpose");
  assert.equal(kindLabel("section:other"), "Section other");
  assert.equal(kindLabel("field:priority"), "Column priority");
  assert.equal(kindLabel("odd"), "odd");
});

test("a set with gaps needs the tick, the set in use needs no apply", () => {
  assert.equal(canApply(null, true, "default"), false);
  assert.equal(canApply({ set: "acme", gaps: 0 }, false, "default"), true);
  assert.equal(canApply({ set: "acme", gaps: 3 }, false, "default"), false);
  assert.equal(canApply({ set: "acme", gaps: 3 }, true, "default"), true);
  assert.equal(canApply({ set: "default", gaps: 0 }, false, "default"), false);
});

test("the built-in set has a name, others show title and id", () => {
  assert.equal(setLabel({ id: "default", builtin: true }), "MasterBA standard");
  assert.equal(setLabel({ id: "acme", title: "ACME" }), "ACME (acme)");
  assert.equal(setLabel({ id: "acme", title: null }), "acme");
});
