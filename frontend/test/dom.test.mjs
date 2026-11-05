// dom.js primitive tests. Run with: node --test  (from the frontend directory)
import { test } from "node:test";
import assert from "node:assert/strict";
import { install } from "./dom-shim.js";

const env = install();
const dom = await import("../dom.js");

test("h builds elements with class, id, text and nested children", () => {
  const el = dom.h("div", { class: "x", id: "foo" }, dom.h("span", {}, "hi"), "world");
  assert.equal(el.tagName, "DIV");
  assert.equal(el.className, "x");
  assert.equal(el.id, "foo");
  assert.equal(el.textContent, "hiworld");
});

test("h skips null, undefined and false children", () => {
  const el = dom.h("div", {}, "a", null, undefined, false, "b");
  assert.equal(el.textContent, "ab");
});

test("h attaches event listeners from on* props", () => {
  let hit = 0;
  const btn = dom.h("button", { onClick: () => hit++ });
  btn.click();
  assert.equal(hit, 1);
});

test("badge shows an icon plus a word, never colour alone", () => {
  const b = dom.badge("done");
  assert.match(b.textContent, /Done/);
  assert.ok(b.className.includes("ok"));
  assert.ok(b.textContent.trim().length > "Done".length, "icon glyph precedes the word");
});

test("badge falls back gracefully for unknown status", () => {
  const b = dom.badge("nonsense");
  assert.match(b.textContent, /nonsense/);
  assert.ok(b.className.includes("idle"));
});

test("empty renders text and an optional action", () => {
  const plain = dom.empty("nothing here");
  assert.match(plain.textContent, /nothing here/);
  assert.equal(plain.querySelector("a"), null);

  const withAction = dom.empty("nothing", dom.h("a", { href: "#/x" }, "go"));
  assert.ok(withAction.querySelector("a"));
  assert.match(withAction.textContent, /go/);
});

test("table applies dense and stickyFirst options and renders all rows", () => {
  const t = dom.table(["A", "B"], [["1", "2"], ["3", "4"]], "cap", { dense: true, stickyFirst: true });
  assert.ok(t.className.includes("dense"));
  assert.ok(t.className.includes("sticky-first"));
  assert.equal(t.querySelectorAll("tbody tr").length, 2);
  assert.equal(t.querySelectorAll("th").length, 2);
});

test("errorBox renders a working retry button only when given a handler", () => {
  let retried = 0;
  const withRetry = dom.errorBox("boom", () => retried++);
  const btn = withRetry.querySelector("button");
  assert.ok(btn);
  btn.click();
  assert.equal(retried, 1);

  const noRetry = dom.errorBox("boom");
  assert.equal(noRetry.querySelector("button"), null);
});

test("skeleton renders a title bar plus the requested number of rows", () => {
  const sk = dom.skeleton(4);
  // one title bar + 4 rows = 5 bars
  assert.equal(sk.querySelectorAll(".sk-bar").length, 5);
});

test("liveDot pairs a word with the pulse so colour is not the only signal", () => {
  const on = dom.liveDot(true, "Live");
  assert.match(on.textContent, /Live/);
  assert.ok(on.className.includes("on"));
  const off = dom.liveDot(false, "Paused");
  assert.ok(off.className.includes("off"));
});
